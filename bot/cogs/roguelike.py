"""100-stage Overwatch-themed auto-combat campaign."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.games.watchpoint.content import GAME_VERSION
from bot.games.watchpoint.repository import WatchpointRepository
from bot.games.watchpoint.service import WatchpointService
from bot.games.watchpoint.ui import HeadquartersView, headquarters_embed

logger = logging.getLogger(__name__)


class RoguelikeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.repository = WatchpointRepository()
        self.service = WatchpointService(self.repository)

    async def cog_load(self) -> None:
        await asyncio.to_thread(self.repository.ensure_schema)
        logger.info(
            "watchpoint protocol loaded version=%s storage=supabase stages=100",
            GAME_VERSION,
        )

    @app_commands.command(
        name="로그라이크",
        description="100스테이지 워치포인트 프로토콜 작전본부를 엽니다.",
    )
    @app_commands.guild_only()
    async def roguelike(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            snapshot = await asyncio.to_thread(
                self.service.headquarters,
                interaction.user.id,
            )
            embed = headquarters_embed(interaction.user, snapshot)
            view = HeadquartersView(
                self.service,
                interaction.user.id,
                bool(snapshot["run"]),
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as exc:
            logger.exception(
                "watchpoint headquarters failed user=%s",
                interaction.user.id,
            )
            await interaction.followup.send(
                f"❌ 작전본부를 불러오지 못했습니다: `{type(exc).__name__}`",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoguelikeCog(bot))
