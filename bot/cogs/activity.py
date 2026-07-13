"""Discord Activity 실행 명령.

현재 Discord 애플리케이션에 연결된 Activity를 리액션 랩으로 실행한다.
Activity URL Mapping과 Enable Activities 설정은 Discord Developer Portal에서
같은 애플리케이션에 구성되어 있어야 한다.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class ActivityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="리액션랩",
        description="디스코드 안에서 리액션 랩 반응속도 게임을 실행합니다.",
    )
    async def reaction_lab(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.launch_activity()
        except discord.HTTPException:
            logger.exception("리액션 랩 Activity 실행 실패")
            message = (
                "리액션 랩을 열지 못했어요. "
                "이 봇 애플리케이션의 Activities 활성화와 URL Mapping을 확인해 주세요."
            )
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ActivityCog(bot))
