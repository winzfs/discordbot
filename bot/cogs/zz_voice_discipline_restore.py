"""Apply the final integrated voice-management view without blocking startup."""
from __future__ import annotations

import logging

from discord.ext import commands

from bot.cogs import voice_audit
from bot.voice_discipline import dm_patch, ui

logger = logging.getLogger(__name__)


def install_final_panel() -> None:
    """Make the original /음성관리패널 render the integrated discipline view.

    The original command resolves ``voice_audit.VoiceAuditView`` when the
    command is executed, so no Cog lookup or private command callback patching
    is required.  This also keeps extension loading safe if Cog registration
    order changes.
    """
    ui.install_patch()
    dm_patch.install_patch()
    voice_audit.VoiceAuditView = dm_patch.ReliableDisciplineVoiceAuditView


class VoiceDisciplineRestoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        install_final_panel()
        logger.info(
            "음성관리패널 최종 통합 View 적용 완료: "
            "3회 경고 명단 + DM 안내문 + 소프트밴"
        )


async def setup(bot: commands.Bot) -> None:
    # Never search for VoiceAuditCog here. Extension setup order can differ
    # between deployments, and failing this compatibility patch must not stop
    # the entire bot from starting.
    await bot.add_cog(VoiceDisciplineRestoreCog(bot))
