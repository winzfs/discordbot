"""MBTI 역할 선택 시스템."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

MBTI_TYPES = (
    "INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
    "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP",
)
ROLE_PREFIX = "MBTI · "


async def assign_mbti(member: discord.Member, value: str) -> str:
    current = [role for role in member.roles if role.name.startswith(ROLE_PREFIX)]
    selected = discord.utils.get(member.guild.roles, name=f"{ROLE_PREFIX}{value}")
    if selected is None:
        selected = await member.guild.create_role(name=f"{ROLE_PREFIX}{value}", reason="MBTI 역할 자동 생성")

    if selected in current:
        await member.remove_roles(selected, reason="MBTI 역할 해제")
        return f"{value} 역할을 해제했습니다."

    if current:
        await member.remove_roles(*current, reason="MBTI 역할 변경")
    await member.add_roles(selected, reason="MBTI 역할 선택")
    return f"{value} 역할을 부여했습니다."


class MBTISelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=value, value=value) for value in MBTI_TYPES]
        super().__init__(placeholder="MBTI를 선택하세요", options=options, custom_id="mbti:select")

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        message = await assign_mbti(interaction.user, self.values[0])
        await interaction.response.send_message(message, ephemeral=True)


class MBTIView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MBTISelect())

    @discord.ui.button(label="MBTI 역할 해제", style=discord.ButtonStyle.danger, custom_id="mbti:remove")
    async def remove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        roles = [role for role in interaction.user.roles if role.name.startswith(ROLE_PREFIX)]
        if roles:
            await interaction.user.remove_roles(*roles, reason="MBTI 역할 해제")
        await interaction.response.send_message("MBTI 역할을 해제했습니다.", ephemeral=True)


class MBTICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(MBTIView())

    @app_commands.command(name="mbti", description="MBTI 역할을 선택합니다.")
    async def mbti(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🧠 MBTI 역할 선택",
            description="드롭다운에서 MBTI를 선택하세요. 같은 항목을 다시 선택하면 해제됩니다.",
            color=0x7B68EE,
        )
        await interaction.response.send_message(embed=embed, view=MBTIView(), ephemeral=True)

    @app_commands.command(name="mbti해제", description="현재 MBTI 역할을 해제합니다.")
    async def remove_mbti(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        roles = [role for role in interaction.user.roles if role.name.startswith(ROLE_PREFIX)]
        if roles:
            await interaction.user.remove_roles(*roles, reason="MBTI 역할 해제")
        await interaction.response.send_message("MBTI 역할을 해제했습니다.", ephemeral=True)

    @app_commands.command(name="mbti채널설정", description="[관리자] 이 채널에 MBTI 선택 패널을 게시합니다.")
    @app_commands.default_permissions(administrator=True)
    async def setup_channel(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="당신의 MBTI는?", description="아래에서 MBTI 역할을 선택하세요.", color=0x7B68EE)
        await interaction.channel.send(embed=embed, view=MBTIView())
        await interaction.response.send_message("MBTI 패널을 게시했습니다.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MBTICog(bot))
