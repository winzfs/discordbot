"""cogs/welcome.py — 신규 유저 환영 메시지"""
from __future__ import annotations
import os as _os
_DIR = _os.path.dirname(_os.path.abspath(__file__))
_DATA_DIR = _os.path.dirname(_DIR)
import json
import os
import discord
from discord import app_commands
from discord.ext import commands
from utils.embeds import _ow_footer

WELCOME_CONFIG_FILE = _os.path.join(_DATA_DIR, "welcome_config.json")
_welcome_config: dict = {}  # {guild_id: {channel_id, message, title, color}}

DEFAULT_MESSAGE = "{mention}님, 환영합니다!\n\n오버워치 커뮤니티에 오신 것을 환영해요.\n`/start` 명령어로 RPG를 시작해보세요! 🎮"
DEFAULT_COLOR   = 0xFF6B00

PLACEHOLDERS = (
    "`{mention}` — 유저 멘션\n"
    "`{name}` — 유저 닉네임\n"
    "`{server}` — 서버 이름\n"
    "`{count}` — 현재 멤버 수"
)

def _load():
    global _welcome_config
    if os.path.exists(WELCOME_CONFIG_FILE):
        try:
            _welcome_config = json.load(open(WELCOME_CONFIG_FILE, encoding="utf-8"))
        except Exception:
            _welcome_config = {}

def _save():
    json.dump(_welcome_config, open(WELCOME_CONFIG_FILE, "w", encoding="utf-8"), ensure_ascii=False)

def _apply(template: str, member: discord.Member) -> str:
    return (template
        .replace("{mention}", member.mention)
        .replace("{name}",    member.display_name)
        .replace("{server}",  member.guild.name)
        .replace("{count}",   str(member.guild.member_count))
    )


# ── 미리보기 + 설정 뷰 ────────────────────────────────────────────────────────

class WelcomeSetupView(discord.ui.View):
    def __init__(self, guild_id: str, cfg: dict):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.cfg      = cfg

    @discord.ui.button(label="📝 메시지 수정",  style=discord.ButtonStyle.primary,   row=0)
    async def edit_message(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(WelcomeEditModal(self, "message"))

    @discord.ui.button(label="🎨 색상 변경",    style=discord.ButtonStyle.secondary, row=0)
    async def edit_color(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(WelcomeEditModal(self, "color"))

    @discord.ui.button(label="✅ 활성화",        style=discord.ButtonStyle.success,   row=1)
    async def enable(self, interaction: discord.Interaction, _):
        self.cfg["enabled"] = True
        _welcome_config[self.guild_id] = self.cfg
        _save()
        await interaction.response.send_message(
            embed=discord.Embed(title="✅ 환영 메시지 활성화됨", color=0x4CAF50),
            ephemeral=True,
        )

    @discord.ui.button(label="⛔ 비활성화",      style=discord.ButtonStyle.danger,    row=1)
    async def disable(self, interaction: discord.Interaction, _):
        self.cfg["enabled"] = False
        _welcome_config[self.guild_id] = self.cfg
        _save()
        await interaction.response.send_message(
            embed=discord.Embed(title="⛔ 환영 메시지 비활성화됨", color=0x9E9E9E),
            ephemeral=True,
        )

    @discord.ui.button(label="👀 미리보기",      style=discord.ButtonStyle.primary,   row=1)
    async def preview(self, interaction: discord.Interaction, _):
        embed = _build_welcome_embed(self.cfg, interaction.user)
        await interaction.response.send_message(
            content=f"**[미리보기]** {interaction.user.mention}",
            embed=embed,
            ephemeral=True,
        )

    async def refresh(self, interaction: discord.Interaction):
        embed = _build_setup_embed(self.cfg, interaction.guild.name if interaction.guild else "")
        await interaction.edit_original_response(embed=embed, view=self)


class WelcomeEditModal(discord.ui.Modal):
    input = discord.ui.TextInput(
        label="내용 입력",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    def __init__(self, parent: WelcomeSetupView, field: str):
        self.parent = parent
        self.field  = field
        titles = {"message": "메시지 수정", "color": "색상 변경 (HEX)"}
        hints  = {
            "message": parent.cfg.get("message", DEFAULT_MESSAGE),
            "color":   hex(parent.cfg.get("color", DEFAULT_COLOR)),
        }
        self.input.default     = hints[field]
        self.input.placeholder = hints[field][:100]
        if field == "color":
            self.input.style   = discord.TextStyle.short
            self.input.max_length = 10
        super().__init__(title=titles[field])

    async def on_submit(self, interaction: discord.Interaction):
        val = self.input.value.strip()
        if self.field == "color":
            try:
                color = int(val.replace("#", "").replace("0x", ""), 16)
            except ValueError:
                await interaction.response.send_message("❌ 올바른 HEX 색상을 입력하세요. 예: `FF6B00`", ephemeral=True)
                return
            self.parent.cfg["color"] = color
        else:
            self.parent.cfg[self.field] = val

        _welcome_config[self.parent.guild_id] = self.parent.cfg
        _save()
        await interaction.response.defer(ephemeral=True)
        await self.parent.refresh(interaction)
        await interaction.followup.send("✅ 저장되었습니다.", ephemeral=True)


# ── 임베드 빌더 ───────────────────────────────────────────────────────────────

def _build_welcome_embed(cfg: dict, member: discord.Member) -> discord.Embed:
    message = _apply(cfg.get("message", DEFAULT_MESSAGE), member)
    color   = cfg.get("color", DEFAULT_COLOR)
    embed   = discord.Embed(description=message, color=color)
    return embed


def _build_setup_embed(cfg: dict, guild_name: str = "") -> discord.Embed:
    status  = "✅ 활성화" if cfg.get("enabled", True) else "⛔ 비활성화"
    ch_id   = cfg.get("channel_id")
    ch_str  = f"<#{ch_id}>" if ch_id else "미설정"
    message = cfg.get("message", DEFAULT_MESSAGE)
    color   = cfg.get("color",   DEFAULT_COLOR)

    embed = discord.Embed(
        title="⚙️ 환영 메시지 설정",
        color=color,
    )
    embed.add_field(name="상태",   value=status,             inline=True)
    embed.add_field(name="채널",   value=ch_str,             inline=True)
    embed.add_field(name="색상",   value=hex(color),         inline=True)
    embed.add_field(name="메시지", value=message,            inline=False)
    embed.add_field(name="📌 사용 가능한 변수", value=PLACEHOLDERS, inline=False)
    embed.set_footer(text=guild_name)
    return embed


# ── Welcome Cog ───────────────────────────────────────────────────────────────

class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _load()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = str(member.guild.id)
        cfg      = _welcome_config.get(guild_id, {})
        if not cfg.get("enabled", False):
            return
        ch_id = cfg.get("channel_id")
        if not ch_id:
            return
        channel = self.bot.get_channel(ch_id)
        if not channel:
            return
        embed = _build_welcome_embed(cfg, member)
        await channel.send(content=member.mention, embed=embed)

    # ── /환영채널설정 ─────────────────────────────────────────────────────────

    @app_commands.command(name="환영채널설정", description="[관리자] 신규 유저 환영 메시지 채널 및 내용을 설정합니다.")
    @app_commands.default_permissions(administrator=True)
    async def welcome_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        cfg      = _welcome_config.get(guild_id, {
            "channel_id": interaction.channel_id,
            "message":    DEFAULT_MESSAGE,
            "color":      DEFAULT_COLOR,
            "enabled":    True,
        })
        cfg["channel_id"] = interaction.channel_id
        _welcome_config[guild_id] = cfg
        _save()

        embed = _build_setup_embed(cfg, interaction.guild.name if interaction.guild else "")
        view  = WelcomeSetupView(guild_id, cfg)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
