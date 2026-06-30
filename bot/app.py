import logging
from pathlib import Path

import discord
from discord.ext import commands

from bot.config import Settings

logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = settings.message_content_intent
        intents.members = settings.members_intent
        intents.voice_states = True

        super().__init__(
            command_prefix=commands.when_mentioned_or(settings.command_prefix),
            intents=intents,
            help_command=None,
        )
        self.settings = settings
        self._guild_commands_synced = False

    async def setup_hook(self) -> None:
        await self._load_extensions()
        logger.info("확장 모듈 로드 완료, 길드 전용 명령어 동기화 대기")

    async def on_ready(self) -> None:
        if self.user is None:
            return

        if not self._guild_commands_synced:
            await self._sync_guild_only_commands()
            self._guild_commands_synced = True

        logger.info(
            "봇 로그인 완료: %s (%s), 서버 %s개, 길드 명령어 동기화=%s",
            self.user,
            self.user.id,
            len(self.guilds),
            self._guild_commands_synced,
        )

    async def _sync_guild_only_commands(self) -> None:
        """현재 명령어를 각 서버에 즉시 등록하고 전역 명령어는 제거한다."""
        for guild in self.guilds:
            guild_object = discord.Object(id=guild.id)
            try:
                self.tree.clear_commands(guild=guild_object)
                self.tree.copy_global_to(guild=guild_object)
                synced = await self.tree.sync(guild=guild_object)
            except discord.HTTPException:
                logger.exception("길드 명령어 동기화 실패: %s (%s)", guild.name, guild.id)
            else:
                logger.info(
                    "길드 명령어 동기화 완료: %s (%s), %s개",
                    guild.name,
                    guild.id,
                    len(synced),
                )

        try:
            self.tree.clear_commands(guild=None)
            removed = await self.tree.sync()
        except discord.HTTPException:
            logger.exception("전역 명령어 제거 실패")
        else:
            logger.info("전역 명령어 제거 완료: 원격 전역 명령어 %s개", len(removed))

    async def _load_extensions(self) -> None:
        cogs_dir = Path(__file__).parent / "cogs"

        for file_path in sorted(cogs_dir.glob("*.py")):
            if file_path.name.startswith("_"):
                continue

            extension = f"bot.cogs.{file_path.stem}"

            try:
                await self.load_extension(extension)
            except Exception:
                logger.exception("확장 모듈 로드 실패: %s", extension)
                raise
            else:
                logger.info("확장 모듈 로드 완료: %s", extension)
