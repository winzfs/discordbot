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
        """현재 명령어를 각 서버에 즉시 등록한다.

        전역 명령어의 일괄 덮어쓰기는 수행하지 않는다. Discord Activity가
        활성화된 앱에는 삭제할 수 없는 PRIMARY_ENTRY_POINT 명령이 존재하며,
        빈 목록으로 전역 명령을 동기화하면 API 오류 50240이 발생한다.
        길드 명령은 같은 이름의 전역 명령보다 우선하므로 서버 내 사용에는
        영향이 없다.
        """
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

        logger.info(
            "전역 명령어 일괄 정리 건너뜀: Discord Activity Entry Point 보호"
        )

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
