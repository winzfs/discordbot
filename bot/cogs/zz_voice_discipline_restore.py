"""Load the three-warning discipline UI last and expose a standalone command."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs import voice_audit
from bot.voice_discipline import dm_patch, service, store, ui

logger = logging.getLogger(__name__)


class ThreeWarningManageView(discord.ui.View):
    def __init__(self, cog: voice_audit.VoiceAuditCog) -> None:
        super().__init__(timeout=600)
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if voice_audit.authorized(interaction):
            return True
        await voice_audit.deny(interaction)
        return False

    @discord.ui.button(
        label="DM 안내문 설정",
        emoji="✉️",
        style=discord.ButtonStyle.primary,
    )
    async def dm_notice(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(
            dm_patch.ReliableSoftbanNoticeModal(interaction.guild.id)
        )

    @discord.ui.button(
        label="DM 발송 후 소프트밴",
        emoji="🚪",
        style=discord.ButtonStyle.danger,
    )
    async def softban(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            members = await self.cog.fetch_all_members(interaction.guild)
            targets = await asyncio.to_thread(
                service.get_softban_targets,
                interaction.guild,
                members,
            )
            if not targets:
                await interaction.followup.send(
                    "현재 누적 경고 3회 이상 대상이 없습니다.",
                    ephemeral=True,
                )
                return

            actionable = [
                target
                for target in targets
                if service.softban_block_reason(interaction.guild, target.member) is None
            ]
            if not actionable:
                await interaction.followup.send(
                    "3회 경고 대상은 있지만 서버 소유자·지정 관리자·역할 우선순위 문제로 "
                    "처리 가능한 멤버가 없습니다.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="⚠️ 3회 경고 소프트밴 최종 확인",
                color=0xED4245,
            )
            embed.description = (
                f"전체 대상 **{len(targets)}명**, 실제 처리 가능 **{len(actionable)}명**입니다.\n\n"
                "확인 버튼을 누르면 설정된 안내문을 각 대상에게 **DM으로 먼저 발송**한 뒤 "
                "**밴 → 즉시 밴 해제**하여 서버에서 내보냅니다.\n"
                "DM이 닫혀 있으면 실패로 기록하고 소프트밴은 계속 진행합니다."
            )
            await interaction.followup.send(
                embed=embed,
                view=ui.SoftbanConfirmView(self.cog),
                ephemeral=True,
            )
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)


class VoiceDisciplineRestoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # This file is prefixed with zz_ so it loads after every other cog.
        # Reapply both patches here to guarantee the final voice panel class.
        ui.install_patch()
        dm_patch.install_patch()
        logger.info(
            "3회 경고 관리 최종 복구 패치 적용: 패널 버튼 + 독립 /경고3회관리 명령어"
        )

    @app_commands.command(
        name="경고3회관리",
        description="[전용 관리자] 경고 3회 대상 확인, DM 설정 및 소프트밴을 실행합니다.",
    )
    async def three_warning_manage(self, interaction: discord.Interaction) -> None:
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
        cog = self.bot.get_cog("VoiceAuditCog")
        if not isinstance(cog, voice_audit.VoiceAuditCog):
            await interaction.followup.send(
                "음성 관리 모듈을 찾을 수 없습니다. 봇 재시작 로그를 확인해 주세요.",
                ephemeral=True,
            )
            return

        try:
            members = await cog.fetch_all_members(interaction.guild)
            targets = await asyncio.to_thread(
                service.get_softban_targets,
                interaction.guild,
                members,
            )
            template = await asyncio.to_thread(
                store.get_dm_message,
                interaction.guild.id,
            )
            embeds = await asyncio.to_thread(
                ui.target_embeds,
                interaction.guild,
                targets,
                template,
            )
            await interaction.followup.send(
                embeds=embeds,
                view=ThreeWarningManageView(cog),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceDisciplineRestoreCog(bot))
