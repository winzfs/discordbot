"""Bind the live /음성관리패널 command to the final integrated view."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from bot.cogs import voice_audit
from bot.voice_discipline import dm_patch, service, ui

logger = logging.getLogger(__name__)


async def integrated_voice_panel(
    self: voice_audit.VoiceAuditCog,
    interaction: discord.Interaction,
) -> None:
    """Render the original voice panel with every warning-management control."""
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

        field_names = {field.name for field in embed.fields}
        if "3회 경고 소프트밴 대상" not in field_names:
            targets = await asyncio.to_thread(
                service.get_softban_targets,
                interaction.guild,
                members,
            )
            embed.add_field(
                name="3회 경고 소프트밴 대상",
                value=f"{len(targets)}명",
                inline=True,
            )
            embed.add_field(
                name="퇴장 방식",
                value="DM 후 소프트밴 · 즉시 해제",
                inline=True,
            )
            embed.add_field(
                name="주간 관리",
                value="재확인 · 공지 재전송 지원",
                inline=True,
            )

        view = dm_patch.ReliableDisciplineVoiceAuditView(self)
        labels = [
            getattr(item, "label", None) or getattr(item, "placeholder", None) or type(item).__name__
            for item in view.children
        ]
        logger.info("음성관리패널 버튼 검증: %s", labels)

        await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=True,
        )
    except Exception as exc:
        await voice_audit.db_error(interaction, exc)


class VoiceDisciplineRestoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._command_patched = False
        self._apply_view_patch()

    def _apply_view_patch(self) -> None:
        """Keep module-level lookups compatible with the integrated view."""
        ui.install_patch()
        dm_patch.install_patch()
        voice_audit.VoiceAuditView = dm_patch.ReliableDisciplineVoiceAuditView

    def _patch_live_command(self) -> bool:
        """Replace the callback on the command object actually used by Discord."""
        self._apply_view_patch()
        command = self.bot.tree.get_command("음성관리패널")
        if command is None:
            logger.warning("명령 트리에서 음성관리패널을 아직 찾지 못했습니다.")
            return False

        command._callback = integrated_voice_panel
        self._command_patched = True
        logger.info(
            "실제 /음성관리패널 콜백을 통합 패널로 교체했습니다: "
            "다음 경고 진행상황 + 주간 재확인/재전송 + 3회 경고/DM/소프트밴"
        )
        return True

    async def cog_load(self) -> None:
        # voice_audit.py가 먼저 로드된 일반적인 경우에는 여기서 바로 성공합니다.
        self._patch_live_command()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # 명령 동기화 및 모든 Cog 로드 이후 한 번 더 확정 적용합니다.
        if not self._command_patched:
            self._patch_live_command()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceDisciplineRestoreCog(bot))
