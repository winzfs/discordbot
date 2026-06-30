"""오버워치 파티 모집 시스템."""
from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

CONFIG_FILE = Path("recruit_config.json")
CONFIG: dict[str, dict] = {}
ACTIVE: dict[int, "RecruitView"] = {}
KST = datetime.timezone(datetime.timedelta(hours=9))


def load_config() -> None:
    global CONFIG
    try:
        CONFIG = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        CONFIG = {}


def save_config() -> None:
    CONFIG_FILE.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")


def board_embed() -> discord.Embed:
    posts = [view for view in ACTIVE.values() if not view.closed]
    embed = discord.Embed(title=f"📋 파티 모집 목록 — {len(posts)}건", color=0xFF6B00)
    if not posts:
        embed.description = "현재 활성 모집이 없습니다. `/모집` 명령어로 모집을 시작하세요."
    for view in posts[:10]:
        embed.add_field(
            name=f"{view.mode} · {len(view.members)}/{view.max_members}명",
            value=(
                f"파티장: {view.host.mention}\n"
                f"티어: {view.tier}\n"
                f"역할: {view.role}\n"
                f"[모집 글로 이동]({view.message.jump_url})"
            ),
            inline=False,
        )
    embed.set_footer(text=f"업데이트 {datetime.datetime.now(KST).strftime('%H:%M')} KST")
    return embed


async def refresh_board(bot: commands.Bot, guild_id: int) -> None:
    config = CONFIG.get(str(guild_id))
    if not config:
        return
    channel = bot.get_channel(config["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(config["message_id"])
        await message.edit(embed=board_embed())
    except (discord.NotFound, discord.Forbidden):
        message = await channel.send(embed=board_embed())
        config["message_id"] = message.id
        save_config()


class RecruitView(discord.ui.View):
    def __init__(self, bot: commands.Bot, host: discord.Member, mode: str, tier: str, role: str, max_members: int):
        super().__init__(timeout=3600)
        self.bot = bot
        self.host = host
        self.mode = mode
        self.tier = tier
        self.role = role
        self.max_members = max_members
        self.members: list[discord.Member] = [host]
        self.message: discord.Message | None = None
        self.closed = False

    def embed(self) -> discord.Embed:
        embed = discord.Embed(title=f"🎮 {self.mode} 파티 모집", color=0x5865F2)
        embed.add_field(name="티어", value=self.tier, inline=True)
        embed.add_field(name="구하는 역할", value=self.role, inline=True)
        embed.add_field(name="인원", value=f"{len(self.members)}/{self.max_members}", inline=True)
        embed.add_field(
            name="참여자",
            value="\n".join(f"{index + 1}. {member.mention}" for index, member in enumerate(self.members)),
            inline=False,
        )
        embed.set_footer(text="마감됨" if self.closed else f"파티장: {self.host.display_name}")
        return embed

    @discord.ui.button(label="참가", emoji="✅", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.closed or len(self.members) >= self.max_members:
            await interaction.response.send_message("모집이 마감됐습니다.", ephemeral=True)
            return
        if interaction.user in self.members:
            await interaction.response.send_message("이미 참가 중입니다.", ephemeral=True)
            return
        self.members.append(interaction.user)
        if len(self.members) >= self.max_members:
            self.closed = True
        await interaction.response.defer()
        await self.message.edit(embed=self.embed(), view=self)
        await refresh_board(self.bot, interaction.guild_id)

    @discord.ui.button(label="참가 취소", emoji="❌", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user == self.host:
            await interaction.response.send_message("파티장은 모집을 삭제해 주세요.", ephemeral=True)
            return
        if interaction.user in self.members:
            self.members.remove(interaction.user)
        await interaction.response.defer()
        await self.message.edit(embed=self.embed(), view=self)
        await refresh_board(self.bot, interaction.guild_id)

    @discord.ui.button(label="마감", emoji="🔒", style=discord.ButtonStyle.primary)
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user != self.host:
            await interaction.response.send_message("파티장만 마감할 수 있습니다.", ephemeral=True)
            return
        self.closed = True
        await interaction.response.defer()
        await self.message.edit(embed=self.embed(), view=self)
        await refresh_board(self.bot, interaction.guild_id)

    @discord.ui.button(label="삭제", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user != self.host and not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("파티장 또는 관리자만 삭제할 수 있습니다.", ephemeral=True)
            return
        ACTIVE.pop(self.message.id, None)
        await interaction.response.defer()
        await self.message.delete()
        await refresh_board(self.bot, interaction.guild_id)

    async def on_timeout(self) -> None:
        self.closed = True
        if self.message:
            ACTIVE.pop(self.message.id, None)
            try:
                await self.message.delete()
                await refresh_board(self.bot, self.message.guild.id)
            except discord.HTTPException:
                pass


class RecruitCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        load_config()

    @app_commands.command(name="모집", description="오버워치 파티원을 모집합니다.")
    @app_commands.describe(모드="경쟁전, 빠른 대전 등", 티어="모집 티어", 역할="구하는 역할", 인원="최대 인원")
    async def recruit(
        self,
        interaction: discord.Interaction,
        모드: str,
        티어: str = "무관",
        역할: str = "무관",
        인원: app_commands.Range[int, 2, 6] = 6,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        view = RecruitView(self.bot, interaction.user, 모드, 티어, 역할, 인원)
        await interaction.response.send_message("모집 글을 생성했습니다.", ephemeral=True)
        message = await interaction.channel.send(embed=view.embed(), view=view)
        view.message = message
        ACTIVE[message.id] = view
        await refresh_board(self.bot, interaction.guild_id)

    @app_commands.command(name="모집채널설정", description="[관리자] 이 채널을 모집 게시판 채널로 설정합니다.")
    @app_commands.default_permissions(administrator=True)
    async def setup_board(self, interaction: discord.Interaction) -> None:
        message = await interaction.channel.send(embed=board_embed())
        CONFIG[str(interaction.guild_id)] = {"channel_id": interaction.channel_id, "message_id": message.id}
        save_config()
        try:
            await message.pin()
        except discord.Forbidden:
            pass
        await interaction.response.send_message("모집 게시판을 설정했습니다.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RecruitCog(bot))
