"""Install three-warning DM notice and soft-ban controls."""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from bot.voice_discipline import dm_patch, store, ui

logger = logging.getLogger(__name__)


class VoiceDisciplineCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        ui.install_patch()
        dm_patch.install_patch()
        logger.info(
            "음성 관리 패치 적용 완료: DM 안내문 안정화 + 3회 경고 DM 안내 + 재입장 가능한 소프트밴"
        )


async def setup(bot: commands.Bot) -> None:
    try:
        await asyncio.to_thread(store.ensure_schema)
    except Exception:
        logger.exception("음성 소프트밴 설정 테이블 초기화 실패")
    await bot.add_cog(VoiceDisciplineCog(bot))
