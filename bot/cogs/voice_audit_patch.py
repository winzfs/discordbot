"""Patch voice audit panel channel selection to include announcement channels."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from bot.cogs import voice_audit

logger = logging.getLogger(__name__)


class AnnouncementReportChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: voice_audit.VoiceAuditCog):
        super().__init__(
            placeholder="주간 경고자 명단을 보낼 공지 채널 선택",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=1,
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0]
        if not hasattr(channel, "id") or not hasattr(channel, "mention"):
            await interaction.response.send_message(
                "텍스트/공지사항 채널만 설정할 수 있습니다.",
                ephemeral=True,
            )
            return
        await asyncio.to_thread(
            self.cog.set_report_channel_id,
            interaction.guild.id,
            channel.id,
        )
        await interaction.response.send_message(
            f"✅ 경고자 명단 공지 채널을 {channel.mention}(으)로 설정했습니다.",
            ephemeral=True,
        )


class VoiceAuditPatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        voice_audit.ReportChannelSelect = AnnouncementReportChannelSelect
        logger.info("음성 관리 패널 공지사항 채널 선택 패치 적용 완료")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceAuditPatchCog(bot))
