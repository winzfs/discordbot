"""cogs/guide.py — 서버 이용 가이드"""
from __future__ import annotations
import os as _os
_DIR = _os.path.dirname(_os.path.abspath(__file__))
_DATA_DIR = _os.path.dirname(_DIR)
import json
import os
import discord
from discord import app_commands
from discord.ext import commands

GUIDE_FILE = _os.path.join(_DATA_DIR, "guide_config.json")
_guide: dict = {}

# 기본 가이드 데이터
DEFAULT_SECTIONS = [
    {
        "title": "👋 서버 소개",
        "content": "오버워치를 함께 즐기는 커뮤니티 서버입니다.\n함께 게임하고 정보를 공유해요!",
    },
    {
        "title": "📋 이용 규칙",
        "content": "1. 서로 존중하는 언어를 사용해주세요.\n2. 욕설 및 비하 발언은 금지입니다.\n3. 스팸 및 도배는 삼가주세요.\n4. 광고 및 홍보는 허가된 채널에서만 가능합니다.",
    },
    {
        "title": "🎮 주요 기능",
        "content": "`/모집` — 파티 모집 시작\n`/운세` — 오늘의 운세 확인\n`/mbti` — MBTI 역할 선택\n`/배틀태그` — 배틀태그 등록 및 공유\n`/생일등록` — 생일 등록",
    },
    {
        "title": "📢 채널 안내",
        "content": "#공지 — 서버 공지사항\n#구인구직 — 파티 모집 현황\n#생일 — 생일 등록 및 축하\n#레딧 — 오버워치 최신 소식",
    },
]


def _load():
    global _guide
    if os.path.exists(GUIDE_FILE):
        try:
            _guide = json.load(open(GUIDE_FILE, encoding="utf-8"))
        except Exception:
            _guide = {}

def _save():
    json.dump(_guide, open(GUIDE_FILE, "w", encoding="utf-8"), ensure_ascii=False)

def _get_guild_guide(guild_id: str) -> dict:
    return _guide.get(guild_id, {
        "title":    "📖 서버 이용 가이드",
        "color":    0xFF6B00,
        "footer":   "",
        "sections": DEFAULT_SECTIONS.copy(),
    })


def build_guide_embed(guild_id: str, guild: discord.Guild | None = None) -> discord.Embed:
    data     = _get_guild_guide(guild_id)
    sections = data.get("sections", DEFAULT_SECTIONS)
    color    = data.get("color", 0xFF6B00)
    title    = data.get("title", "📖 서버 이용 가이드")
    footer   = data.get("footer", "")

    embed = discord.Embed(title=title, color=color)
    for sec in sections:
        if sec.get("title") and sec.get("content"):
            embed.add_field(name=sec["title"], value=sec["content"], inline=False)
    if footer:
        embed.set_footer(text=footer)
    elif guild:
        embed.set_footer(text=guild.name)
    return embed


class GuideTitleModal(discord.ui.Modal, title="가이드 제목 수정"):
    guide_title = discord.ui.TextInput(label="가이드 제목", placeholder="예: 📖 서버 이용 가이드", max_length=100, required=True)
    footer = discord.ui.TextInput(label="하단 푸터", placeholder="예: 서버명 | 문의는 운영진에게", max_length=100, required=False)

    def __init__(self, guild_id: str, view: "GuideEditView"):
        super().__init__()
        data = _get_guild_guide(guild_id)
        self.guide_title.default = data.get("title", "📖 서버 이용 가이드")
        self.footer.default = data.get("footer", "")
        self.guild_id = guild_id
        self.parent = view

    async def on_submit(self, interaction: discord.Interaction):
        data = _get_guild_guide(self.guild_id)
        data["title"] = self.guide_title.value.strip()
        data["footer"] = self.footer.value.strip()
        _guide[self.guild_id] = data
        _save()
        await interaction.response.defer(ephemeral=True)
        await self.parent.refresh(interaction)
        await interaction.followup.send("✅ 제목과 푸터가 수정되었습니다.", ephemeral=True)


class SectionEditModal(discord.ui.Modal):
    sec_title = discord.ui.TextInput(label="섹션 제목", placeholder="예: 📋 이용 규칙", max_length=100, required=True)
    sec_content = discord.ui.TextInput(label="섹션 내용", style=discord.TextStyle.paragraph, placeholder="내용을 입력하세요...", max_length=1000, required=True)

    def __init__(self, guild_id: str, idx: int | None, view: "GuideEditView"):
        self.idx = idx
        self.guild_id = guild_id
        self.parent = view
        data = _get_guild_guide(guild_id)
        sections = data.get("sections", [])
        if idx is not None and idx < len(sections):
            self.sec_title.default = sections[idx]["title"]
            self.sec_content.default = sections[idx]["content"]
            super().__init__(title="섹션 수정")
        else:
            super().__init__(title="섹션 추가")

    async def on_submit(self, interaction: discord.Interaction):
        data = _get_guild_guide(self.guild_id)
        sections = data.get("sections", [])
        section = {"title": self.sec_title.value.strip(), "content": self.sec_content.value.strip()}
        if self.idx is not None and self.idx < len(sections):
            sections[self.idx] = section
        else:
            sections.append(section)
        data["sections"] = sections
        _guide[self.guild_id] = data
        _save()
        await interaction.response.defer(ephemeral=True)
        await self.parent.refresh(interaction)
        await interaction.followup.send("✅ 섹션이 저장되었습니다.", ephemeral=True)


class GuideEditView(discord.ui.View):
    def __init__(self, guild_id: str, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()
        data = _get_guild_guide(self.guild_id)
        sections = data.get("sections", [])

        btn_title = discord.ui.Button(label="✏️ 제목·푸터 수정", style=discord.ButtonStyle.primary, row=0)
        btn_title.callback = self._edit_title
        self.add_item(btn_title)
        btn_color = discord.ui.Button(label="🎨 색상 변경", style=discord.ButtonStyle.secondary, row=0)
        btn_color.callback = self._edit_color
        self.add_item(btn_color)
        btn_add = discord.ui.Button(label=f"➕ 섹션 추가 ({len(sections)}/25)", style=discord.ButtonStyle.success, disabled=len(sections) >= 25, row=0)
        btn_add.callback = self._add_section
        self.add_item(btn_add)

        if sections:
            edit_opts = [discord.SelectOption(label=sec["title"][:50], value=str(i), emoji="✏️") for i, sec in enumerate(sections)]
            sel_edit = discord.ui.Select(placeholder="✏️ 수정할 섹션 선택...", options=edit_opts, row=1)
            sel_edit.callback = self._edit_section
            self.add_item(sel_edit)
            del_opts = [discord.SelectOption(label=sec["title"][:50], value=str(i), emoji="🗑️") for i, sec in enumerate(sections)]
            sel_del = discord.ui.Select(placeholder="🗑️ 삭제할 섹션 선택...", options=del_opts, row=2)
            sel_del.callback = self._del_section
            self.add_item(sel_del)
            if len(sections) > 1:
                move_opts = [discord.SelectOption(label=sec["title"][:50], value=str(i), emoji="🔼") for i, sec in enumerate(sections)]
                sel_up = discord.ui.Select(placeholder="🔼 위로 이동할 섹션 선택...", options=move_opts, row=3)
                sel_up.callback = self._move_up
                self.add_item(sel_up)

        btn_reset = discord.ui.Button(label="🔄 기본값으로 초기화", style=discord.ButtonStyle.danger, row=4)
        btn_reset.callback = self._reset
        self.add_item(btn_reset)

    async def refresh(self, interaction: discord.Interaction):
        self._build()
        embed = build_guide_embed(self.guild_id, self.guild)
        await interaction.edit_original_response(embed=embed, view=self)

    async def _edit_title(self, interaction: discord.Interaction):
        await interaction.response.send_modal(GuideTitleModal(self.guild_id, self))

    async def _edit_color(self, interaction: discord.Interaction):
        options = [
            discord.SelectOption(label="🟠 오렌지", value="0xFF6B00"),
            discord.SelectOption(label="🔵 블루", value="0x2196F3"),
            discord.SelectOption(label="🟣 퍼플", value="0x9C27B0"),
            discord.SelectOption(label="🔴 레드", value="0xF44336"),
            discord.SelectOption(label="🟢 그린", value="0x4CAF50"),
            discord.SelectOption(label="🩷 핑크", value="0xFF69B4"),
            discord.SelectOption(label="⚫ 다크", value="0x2C2F33"),
            discord.SelectOption(label="🩵 하늘", value="0x00BCD4"),
        ]
        view = discord.ui.View(timeout=60)
        sel = discord.ui.Select(placeholder="색상을 선택하세요...", options=options)

        async def _cb(inter):
            data = _get_guild_guide(self.guild_id)
            data["color"] = int(inter.data["values"][0], 16)
            _guide[self.guild_id] = data
            _save()
            self._build()
            embed = build_guide_embed(self.guild_id, self.guild)
            await inter.response.edit_message(embed=embed, view=self)
            await inter.followup.send("✅ 색상이 변경되었습니다.", ephemeral=True)

        sel.callback = _cb
        view.add_item(sel)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def _add_section(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SectionEditModal(self.guild_id, None, self))

    async def _edit_section(self, interaction: discord.Interaction):
        idx = int(interaction.data["values"][0])
        await interaction.response.send_modal(SectionEditModal(self.guild_id, idx, self))

    async def _del_section(self, interaction: discord.Interaction):
        idx = int(interaction.data["values"][0])
        data = _get_guild_guide(self.guild_id)
        sections = data.get("sections", [])
        if 0 <= idx < len(sections):
            sections.pop(idx)
            data["sections"] = sections
            _guide[self.guild_id] = data
            _save()
        await interaction.response.defer(ephemeral=True)
        await self.refresh(interaction)
        await interaction.followup.send("🗑️ 섹션이 삭제되었습니다.", ephemeral=True)

    async def _move_up(self, interaction: discord.Interaction):
        idx = int(interaction.data["values"][0])
        data = _get_guild_guide(self.guild_id)
        sections = data.get("sections", [])
        if idx > 0:
            sections[idx], sections[idx - 1] = sections[idx - 1], sections[idx]
            data["sections"] = sections
            _guide[self.guild_id] = data
            _save()
        await interaction.response.defer(ephemeral=True)
        await self.refresh(interaction)
        await interaction.followup.send("✅ 섹션 순서가 변경되었습니다.", ephemeral=True)

    async def _reset(self, interaction: discord.Interaction):
        _guide[self.guild_id] = {"title": "📖 서버 이용 가이드", "color": 0xFF6B00, "footer": "", "sections": DEFAULT_SECTIONS.copy()}
        _save()
        await interaction.response.defer(ephemeral=True)
        await self.refresh(interaction)
        await interaction.followup.send("✅ 기본값으로 초기화되었습니다.", ephemeral=True)


class GuideCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _load()

    @app_commands.command(name="가이드", description="서버 이용 가이드를 확인합니다.")
    async def guide(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        embed = build_guide_embed(guild_id, interaction.guild)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="가이드편집", description="[관리자] 서버 이용 가이드를 편집합니다.")
    @app_commands.default_permissions(administrator=True)
    async def guide_edit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        embed = build_guide_embed(guild_id, interaction.guild)
        view = GuideEditView(guild_id, interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuideCog(bot))
