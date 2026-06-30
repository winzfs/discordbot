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

        super().__init__(
            command_prefix=commands.when_mentioned_or(settings.command_prefix),
            intents=intents,
            help_command=None,
        )
        self.settings = settings

    async def setup_hook(self) -> None:
        await self._load_extensions()

    async def on_ready(self) -> None:
        if self.user is None:
            return

        logger.info(
            "봇 로그인 완료: %s (%s), 서버 %s개",
            self.user,
            self.user.id,
            len(self.guilds),
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
