"""Keep report panels created by the first report-system version functional."""
from __future__ import annotations

import discord
from discord.ext import commands

from bot.cogs.report_system import ReportModal


class LegacyReportPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="멤버 신고하기",
        emoji="🚨",
        style=discord.ButtonStyle.danger,
        custom_id="report:create",
    )
    async def create_report(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ReportModal())


class LegacyReportPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        bot.add_view(LegacyReportPanelView())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LegacyReportPanelCog(bot))
