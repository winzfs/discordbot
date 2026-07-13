"""파티 조건 선택과 모집 게시물 생성 UI."""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from .render import EMBED_COLOR, recruit_embed
from .store import RecruitStore
from .views import RecruitPostView, refresh_panel

DEFAULT_EXPIRE_SECONDS = 90 * 60

MODE_OPTIONS = [
    discord.SelectOption(label="경쟁전", emoji="🏆"),
    discord.SelectOption(label="빠른 대전", emoji="⚡"),
    discord.SelectOption(label="스타디움", emoji="🏟️"),
    discord.SelectOption(label="아케이드", emoji="🕹️"),
    discord.SelectOption(label="내전 / 사용자 지정", emoji="🎯"),
]
TIER_OPTIONS = [
    discord.SelectOption(label="티어 무관", value="무관", emoji="🌐"),
    discord.SelectOption(label="브론즈 ~ 실버", emoji="🥉"),
    discord.SelectOption(label="골드 ~ 플래티넘", emoji="🥇"),
    discord.SelectOption(label="다이아몬드 ~ 마스터", emoji="💎"),
    discord.SelectOption(label="그랜드마스터 이상", emoji="👑"),
]
ROLE_OPTIONS = [
    discord.SelectOption(label="역할 무관", value="무관", emoji="🔄"),
    discord.SelectOption(label="돌격", emoji="🛡️"),
    discord.SelectOption(label="공격", emoji="⚔️"),
    discord.SelectOption(label="지원", emoji="➕"),
    discord.SelectOption(label="자유 역할", emoji="🎲"),
]
SIZE_OPTIONS = [
    discord.SelectOption(label=f"{size}인 파티", value=str(size), emoji="👥")
    for size in range(2, 6)
]


class RecruitNoteModal(discord.ui.Modal, title="모집 메모 작성"):
    note = discord.ui.TextInput(
        label="간단한 설명",
        placeholder="예: 마이크 자유, 2~3판 예정, 편하게 하실 분",
        required=False,
        max_length=180,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, builder: "RecruitBuilderView") -> None:
        super().__init__()
        self.builder = builder
        self.note.default = builder.note

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.builder.note = str(self.note.value).strip()
        await interaction.response.send_message("모집 메모를 저장했습니다.", ephemeral=True)
        try:
            await self.builder.source_interaction.edit_original_response(
                embed=self.builder.embed(),
                view=self.builder,
            )
        except discord.HTTPException:
            pass


class _BuilderSelect(discord.ui.Select):
    attribute_name: str
    convert = staticmethod(lambda value: value)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert isinstance(self.view, RecruitBuilderView)
        setattr(self.view, self.attribute_name, self.convert(self.values[0]))
        await interaction.response.edit_message(embed=self.view.embed(), view=self.view)


class ModeSelect(_BuilderSelect):
    attribute_name = "mode"

    def __init__(self) -> None:
        super().__init__(placeholder="1. 게임 모드 선택", options=MODE_OPTIONS, row=0)


class TierSelect(_BuilderSelect):
    attribute_name = "tier"

    def __init__(self) -> None:
        super().__init__(placeholder="2. 티어 범위 선택", options=TIER_OPTIONS, row=1)


class RoleSelect(_BuilderSelect):
    attribute_name = "role"

    def __init__(self) -> None:
        super().__init__(placeholder="3. 필요한 역할 선택", options=ROLE_OPTIONS, row=2)


class SizeSelect(_BuilderSelect):
    attribute_name = "max_members"
    convert = staticmethod(int)

    def __init__(self) -> None:
        super().__init__(placeholder="4. 목표 인원 선택", options=SIZE_OPTIONS, row=3)


class RecruitBuilderView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        store: RecruitStore,
        source_interaction: discord.Interaction,
    ) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.store = store
        self.source_interaction = source_interaction
        self.owner_id = source_interaction.user.id
        self.mode = "경쟁전"
        self.tier = "무관"
        self.role = "무관"
        self.max_members = 5
        self.note = ""
        self.add_item(ModeSelect())
        self.add_item(TierSelect())
        self.add_item(RoleSelect())
        self.add_item(SizeSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("이 설정창은 모집을 시작한 사람만 사용할 수 있습니다.", ephemeral=True)
        return False

    def embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📝 파티 모집 설정",
            description="조건을 정한 뒤 모집 글을 생성하세요.",
            color=EMBED_COLOR,
        )
        embed.add_field(name="모드", value=self.mode, inline=True)
        embed.add_field(name="티어", value=self.tier, inline=True)
        embed.add_field(name="필요 역할", value=self.role, inline=True)
        embed.add_field(name="목표 인원", value=f"{self.max_members}명", inline=True)
        embed.add_field(name="메모", value=self.note or "없음", inline=False)
        embed.set_footer(text="파티장은 참가자 1명으로 자동 포함됩니다.")
        return embed

    @discord.ui.button(label="메모 작성", emoji="✏️", style=discord.ButtonStyle.secondary, row=4)
    async def add_note(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RecruitNoteModal(self))

    @discord.ui.button(label="모집 글 생성", emoji="📣", style=discord.ButtonStyle.success, row=4)
    async def create_recruit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if self.store.find_user_recruit(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                "이미 참가 중인 모집이 있습니다. 기존 모집을 정리한 뒤 다시 시도해 주세요.",
                ephemeral=True,
            )
            return

        target_channel = self._resolve_target_channel(interaction)
        if target_channel is None:
            await interaction.response.send_message("모집 글을 올릴 텍스트 채널을 찾지 못했습니다.", ephemeral=True)
            return

        created_at = self.store.now()
        voice_state = interaction.user.voice
        voice_channel_id = voice_state.channel.id if voice_state and voice_state.channel else None
        state: dict[str, Any] = {
            "guild_id": interaction.guild.id,
            "channel_id": target_channel.id,
            "message_id": 0,
            "host_id": interaction.user.id,
            "mode": self.mode,
            "tier": self.tier,
            "role": self.role,
            "max_members": self.max_members,
            "member_ids": [interaction.user.id],
            "note": self.note,
            "voice_channel_id": voice_channel_id,
            "created_at": created_at,
            "expires_at": created_at + DEFAULT_EXPIRE_SECONDS,
            "closed": False,
            "closed_reason": "",
        }

        await interaction.response.defer(ephemeral=True)
        try:
            view = RecruitPostView(self.bot, self.store, state)
            message = await target_channel.send(embed=recruit_embed(state), view=view)
        except discord.HTTPException:
            await interaction.followup.send("모집 글 생성에 실패했습니다. 봇 권한을 확인해 주세요.", ephemeral=True)
            return

        state["message_id"] = message.id
        self.store.add(state)
        await refresh_panel(self.bot, self.store, interaction.guild.id)

        success = discord.Embed(
            title="✅ 모집 글을 생성했습니다",
            description=f"[{target_channel.mention}에서 모집 글 보기]({message.jump_url})",
            color=0x57F287,
        )
        await interaction.edit_original_response(embed=success, view=None)

    def _resolve_target_channel(self, interaction: discord.Interaction) -> discord.TextChannel | None:
        if interaction.guild is None:
            return None
        config = self.store.get_panel(interaction.guild.id)
        if config:
            channel = self.bot.get_channel(int(config.get("channel_id", 0)))
            if isinstance(channel, discord.TextChannel):
                return channel
        return interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
