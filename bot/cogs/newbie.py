"""cogs/newbie.py — 입장 10일 이내 자동 뉴비 역할 부여/제거"""
from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime

NEWBIE_ROLE_NAME = "뉴비"
NEWBIE_DAYS = 10

class NewbieCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_newbie.start()

    def cog_unload(self):
        self.check_newbie.cancel()

    async def _get_or_create_role(self, guild: discord.Guild) -> discord.Role | None:
        role = discord.utils.get(guild.roles, name=NEWBIE_ROLE_NAME)
        if not role:
            try:
                role = await guild.create_role(
                    name=NEWBIE_ROLE_NAME,
                    color=discord.Color.green(),
                    reason="뉴비 자동 역할 생성"
                )
            except discord.Forbidden:
                return None
        return role

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return
        role = await self._get_or_create_role(member.guild)
        if role:
            try:
                await member.add_roles(role, reason="신규 입장 — 뉴비 역할 자동 부여")
            except discord.Forbidden:
                pass

    @tasks.loop(hours=1)
    async def check_newbie(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for guild in self.bot.guilds:
            role = discord.utils.get(guild.roles, name=NEWBIE_ROLE_NAME)
            if not role: continue
            for member in role.members:
                if member.bot: continue
                joined = member.joined_at
                if joined and (now - joined).days >= NEWBIE_DAYS:
                    try:
                        await member.remove_roles(role, reason=f"입장 {NEWBIE_DAYS}일 경과 — 뉴비 역할 제거")
                    except discord.Forbidden:
                        pass

    @check_newbie.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="뉴비역할동기화", description="[관리자] 현재 멤버 전체에 뉴비 역할을 일괄 적용/제거합니다.")
    @app_commands.default_permissions(administrator=True)
    async def sync_newbie(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        role  = await self._get_or_create_role(guild)
        if not role:
            await interaction.followup.send("❌ 역할 생성/접근 권한이 없습니다.", ephemeral=True)
            return

        now     = datetime.datetime.now(datetime.timezone.utc)
        added   = 0
        removed = 0

        for member in guild.members:
            if member.bot or not member.joined_at: continue
            days = (now - member.joined_at).days
            has_role = role in member.roles
            try:
                if days < NEWBIE_DAYS and not has_role:
                    await member.add_roles(role, reason="뉴비 역할 동기화")
                    added += 1
                elif days >= NEWBIE_DAYS and has_role:
                    await member.remove_roles(role, reason="뉴비 역할 동기화 — 10일 경과")
                    removed += 1
            except discord.Forbidden:
                pass

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 뉴비 역할 동기화 완료",
                description=(
                    f"**{NEWBIE_ROLE_NAME}** 역할 동기화 완료\n\n"
                    f"➕ 추가: **{added}명**\n"
                    f"➖ 제거: **{removed}명**"
                ),
                color=0x4CAF50,
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(NewbieCog(bot))
