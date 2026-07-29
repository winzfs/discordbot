"""Force the final integrated voice-management panel after every cog is loaded."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from bot.cogs import voice_audit
from bot.voice_discipline import dm_patch, ui

logger = logging.getLogger(__name__)


async def integrated_voice_panel(
    self: voice_audit.VoiceAuditCog,
    interaction: discord.Interaction,
) -> None:
    """Render the original voice panel with the three-warning controls included."""
    if not voice_audit.authorized(interaction):
        await voice_audit.deny(interaction)
        return
    if interaction.guild is None:
        await interaction.response.send_message(
            "서버 안에서만 사용할 수 있습니다.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        members = await self.fetch_all_members(interaction.guild)
        database_name = await asyncio.to_thread(voice_audit.verify_database)
        embed = await asyncio.to_thread(
            self.panel_embed,
            interaction.guild,
            members,
            database_name,
        )
        await interaction.followup.send(
            embed=embed,
            view=dm_patch.ReliableDisciplineVoiceAuditView(self),
            ephemeral=True,
        )
    except Exception as exc:
        await voice_audit.db_error(interaction, exc)


def install_final_panel(bot: commands.Bot) -> None:
    """Patch both the global view and the already-created slash-command callback."""
    ui.install_patch()
    dm_patch.install_patch()
    voice_audit.VoiceAuditView = dm_patch.ReliableDisciplineVoiceAuditView

    voice_cog = bot.get_cog("VoiceAuditCog")
    if not isinstance(voice_cog, voice_audit.VoiceAuditCog):
        raise RuntimeError("VoiceAuditCog를 찾을 수 없습니다")

    panel_command = next(
        (command for command in voice_cog.get_app_commands() if command.name == "음성관리패널"),
        None,
    )
    if panel_command is None:
        raise RuntimeError("음성관리패널 명령을 찾을 수 없습니다")

    # discord.py invokes Command._callback with its Cog binding. Patching the
    # command object itself prevents later global View assignments from hiding
    # the discipline controls.
    panel_command._callback = integrated_voice_panel


class VoiceDisciplineRestoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        install_final_panel(bot)
        logger.info(
            "음성관리패널 최종 고정 완료: 3회 경고 명단 + DM 안내문 + 소프트밴 통합"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceDisciplineRestoreCog(bot))
