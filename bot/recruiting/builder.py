"""Components V2 기반 파티 조건 선택과 모집 게시물 생성 UI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import discord
from discord.ext import commands

from .render import ACCENT_COLOR, SUCCESS_COLOR, mode_emoji, role_emoji
from .store import RecruitStore
from .views import RecruitPostView, refresh_panel

DEFAULT_EXPIRE_SECONDS = 90 * 60


@dataclass(frozen=True)
class OptionSpec:
    label: str
    value: str
    emoji: str
    description: str


MODE_OPTIONS = (
    OptionSpec("경쟁전", "경쟁전", "🏆", "티어를 맞춰 진지하게 플레이"),
    OptionSpec("빠른 대전", "빠른 대전", "⚡", "부담 없이 빠르게 매칭"),
    OptionSpec("스타디움", "스타디움", "🏟️", "스타디움 파티 모집"),
    OptionSpec("아케이드", "아케이드", "🕹️", "이벤트와 아케이드 모드"),
    OptionSpec("내전 / 사용자 지정", "내전 / 사용자 지정", "🎯", "내전과 사용자 지정 게임"),
)
TIER_OPTIONS = (
    OptionSpec("티어 무관", "무관", "🌐", "누구나 참가 가능"),
    OptionSpec("브론즈 ~ 실버", "브론즈 ~ 실버", "🥉", "브론즈와 실버 구간"),
    OptionSpec("골드 ~ 플래티넘", "골드 ~ 플래티넘", "🥇", "골드와 플래티넘 구간"),
    OptionSpec("다이아몬드 ~ 마스터", "다이아몬드 ~ 마스터", "💎", "다이아와 마스터 구간"),
    OptionSpec("그랜드마스터 이상", "그랜드마스터 이상", "👑", "그랜드마스터 이상"),
)
ROLE_OPTIONS = (
    OptionSpec("역할 무관", "무관", "🔄", "포지션 제한 없음"),
    OptionSpec("돌격", "돌격", "🛡️", "돌격 영웅을 구합니다"),
    OptionSpec("공격", "공격", "⚔️", "공격 영웅을 구합니다"),
    OptionSpec("지원", "지원", "➕", "지원 영웅을 구합니다"),
    OptionSpec("자유 역할", "자유 역할", "🎲", "자유 역할 모드"),
)
SIZE_OPTIONS = tuple(
    OptionSpec(f"{size}인 파티", str(size), "👥", f"파티장 포함 총 {size}명")
    for size in range(2, 6)
)


def _select_options(specs: tuple[OptionSpec, ...], selected: str) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(
            label=spec.label,
            value=spec.value,
            emoji=spec.emoji,
            description=spec.description,
            default=spec.value == selected,
        )
        for spec in specs
    ]


class RecruitNoteModal(discord.ui.Modal, title="모집 메모 작성"):
    def __init__(self, builder: "RecruitBuilderView") -> None:
        super().__init__()
        self.builder = builder
        self.note_input = discord.ui.TextInput(
            placeholder="예: 마이크 자유, 2~3판 예정, 편하게 하실 분",
            default=builder.note or None,
            required=False,
            max_length=180,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(
            discord.ui.Label(
                text="간단한 설명",
                description="파티 분위기나 플레이 계획을 적어 주세요.",
                component=self.note_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.builder.note = str(self.note_input.value).strip()
        self.builder.rebuild()
        await interaction.response.send_message("모집 메모를 저장했습니다.", ephemeral=True)
        try:
            await self.builder.source_interaction.edit_original_response(
                content=None,
                embed=None,
                attachments=[],
                view=self.builder,
            )
        except discord.HTTPException:
            pass


class _BuilderSelect(discord.ui.Select):
    def __init__(
        self,
        builder: "RecruitBuilderView",
        *,
        attribute_name: str,
        placeholder: str,
        specs: tuple[OptionSpec, ...],
        converter: Callable[[str], Any] = str,
        custom_id: str,
    ) -> None:
        selected = str(getattr(builder, attribute_name))
        super().__init__(
            placeholder=placeholder,
            options=_select_options(specs, selected),
            custom_id=custom_id,
        )
        self.attribute_name = attribute_name
        self.converter = converter

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, RecruitBuilderView):
            return
        setattr(view, self.attribute_name, self.converter(self.values[0]))
        view.rebuild()
        await interaction.response.edit_message(
            content=None,
            embed=None,
            attachments=[],
            view=view,
        )


class _BuilderNoteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="메모 작성",
            emoji="✏️",
            style=discord.ButtonStyle.secondary,
            custom_id="recruit:builder:note",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitBuilderView):
            await interaction.response.send_modal(RecruitNoteModal(view))


class _BuilderCreateButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="모집 글 생성",
            emoji="📣",
            style=discord.ButtonStyle.success,
            custom_id="recruit:builder:create",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitBuilderView):
            await view.create_recruit(interaction)


class RecruitSuccessView(discord.ui.LayoutView):
    def __init__(self, channel_mention: str, jump_url: str) -> None:
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "## ✅ 모집 글을 만들었어요\n"
                    f"{channel_mention}에 새 모집이 등록됐습니다. 참가 현황은 자동으로 갱신됩니다."
                ),
                discord.ui.ActionRow(
                    discord.ui.Button(
                        label="모집 글 바로가기",
                        emoji="↗️",
                        style=discord.ButtonStyle.link,
                        url=jump_url,
                    )
                ),
                accent_color=SUCCESS_COLOR,
            )
        )


class RecruitBuilderView(discord.ui.LayoutView):
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
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("이 설정창은 모집을 시작한 사람만 사용할 수 있습니다.", ephemeral=True)
        return False

    def rebuild(self) -> None:
        self.clear_items()
        note_text = self.note or "아직 작성하지 않았습니다."
        container = discord.ui.Container(accent_color=ACCENT_COLOR)
        container.add_item(
            discord.ui.TextDisplay(
                "## 📝 파티 모집 설정\n"
                "> 조건을 하나씩 고른 뒤 아래 **모집 글 생성** 버튼을 눌러 주세요."
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.TextDisplay(
                f"**{mode_emoji(self.mode)} 모드**  {self.mode}\n"
                f"**🏆 티어**  {self.tier}\n"
                f"**{role_emoji(self.role)} 필요한 역할**  {self.role}\n"
                f"**👥 목표 인원**  {self.max_members}명\n"
                f"**💬 메모**  {note_text}"
            )
        )
        container.add_item(
            discord.ui.ActionRow(
                _BuilderSelect(
                    self,
                    attribute_name="mode",
                    placeholder="1. 게임 모드 선택",
                    specs=MODE_OPTIONS,
                    custom_id="recruit:builder:mode",
                )
            )
        )
        container.add_item(
            discord.ui.ActionRow(
                _BuilderSelect(
                    self,
                    attribute_name="tier",
                    placeholder="2. 티어 범위 선택",
                    specs=TIER_OPTIONS,
                    custom_id="recruit:builder:tier",
                )
            )
        )
        container.add_item(
            discord.ui.ActionRow(
                _BuilderSelect(
                    self,
                    attribute_name="role",
                    placeholder="3. 필요한 역할 선택",
                    specs=ROLE_OPTIONS,
                    custom_id="recruit:builder:role",
                )
            )
        )
        container.add_item(
            discord.ui.ActionRow(
                _BuilderSelect(
                    self,
                    attribute_name="max_members",
                    placeholder="4. 목표 인원 선택",
                    specs=SIZE_OPTIONS,
                    converter=int,
                    custom_id="recruit:builder:size",
                )
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        container.add_item(discord.ui.ActionRow(_BuilderNoteButton(), _BuilderCreateButton()))
        container.add_item(
            discord.ui.TextDisplay(
                "-# 파티장은 첫 참가자로 자동 포함됩니다 · 생성된 글은 90분 뒤 자동 만료됩니다"
            )
        )
        self.add_item(container)

    async def create_recruit(self, interaction: discord.Interaction) -> None:
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
            message = await target_channel.send(view=view)
        except discord.HTTPException:
            await interaction.followup.send("모집 글 생성에 실패했습니다. 봇 권한을 확인해 주세요.", ephemeral=True)
            return

        state["message_id"] = message.id
        self.store.add(state)
        await refresh_panel(self.bot, self.store, interaction.guild.id)

        await interaction.edit_original_response(
            content=None,
            embed=None,
            attachments=[],
            view=RecruitSuccessView(target_channel.mention, message.jump_url),
        )

    def _resolve_target_channel(self, interaction: discord.Interaction) -> discord.TextChannel | None:
        if interaction.guild is None:
            return None
        config = self.store.get_panel(interaction.guild.id)
        if config:
            channel = self.bot.get_channel(int(config.get("channel_id", 0)))
            if isinstance(channel, discord.TextChannel):
                return channel
        return interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
