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
        self._commands_synced = False
        self._legacy_guild_commands_cleared = False

    async def setup_hook(self) -> None:
        await self._load_extensions()
        synced = await self.tree.sync()
        self._commands_synced = True
        logger.info("전역 슬래시 명령어 동기화 완료: %s개", len(synced))

    async def on_ready(self) -> None:
        if self.user is None:
            return

        if not self._legacy_guild_commands_cleared:
            await self._clear_legacy_guild_commands()
            self._legacy_guild_commands_cleared = True

        logger.info(
            "봇 로그인 완료: %s (%s), 서버 %s개, 슬래시 동기화=%s",
            self.user,
            self.user.id,
            len(self.guilds),
            self._commands_synced,
        )

    async def _clear_legacy_guild_commands(self) -> None:
        """모든 서버에 남아 있는 예전 길드 전용 슬래시 명령어를 제거한다."""
        for guild in self.guilds:
            guild_object = discord.Object(id=guild.id)
            try:
                self.tree.clear_commands(guild=guild_object)
                await self.tree.sync(guild=guild_object)
            except discord.HTTPException:
                logger.exception("길드 전용 명령어 정리 실패: %s (%s)", guild.name, guild.id)
            else:
                logger.info("길드 전용 명령어 정리 완료: %s (%s)", guild.name, guild.id)

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
