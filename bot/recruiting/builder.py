"""Components V2 기반 파티 생성 설정 화면."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import discord
from discord.ext import commands

from .render import ACCENT_COLOR, SUCCESS_COLOR, mode_emoji, role_emoji
from .store import RecruitState, RecruitStore
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


def select_options(specs: tuple[OptionSpec, ...], selected: str) -> list[discord.SelectOption]:
    """생성/수정 화면이 공유하는 선택지 생성기."""
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


class RecruitNoteModal(discord.ui.Modal, title="파티 설명 작성"):
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
                text="모집 메모",
                description="파티 분위기나 플레이 계획을 적어 주세요.",
                component=self.note_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.builder.note = str(self.note_input.value).strip()
        self.builder.rebuild()
        from .manage import RecruitNoticeView

        await interaction.response.send_message(
            view=RecruitNoticeView(
                "파티 설명을 저장했어요",
                "생성 전 미리보기에도 바로 반영되었습니다.",
                kind="success",
            ),
            ephemeral=True,
        )
        try:
            await self.builder.source_interaction.edit_original_response(view=self.builder)
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
            options=select_options(specs, selected),
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
        await interaction.response.edit_message(view=view)


class _BuilderNoteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="파티 설명",
            emoji="💬",
            style=discord.ButtonStyle.secondary,
            custom_id="recruit:builder:note",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitBuilderView):
            await interaction.response.send_modal(RecruitNoteModal(view))


class _BuilderCancelButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="취소",
            emoji="←",
            style=discord.ButtonStyle.secondary,
            custom_id="recruit:builder:cancel",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, RecruitBuilderView) or interaction.guild is None:
            return
        from .manage import RecruitDashboardView

        await interaction.response.edit_message(
            view=RecruitDashboardView(
                view.bot,
                view.store,
                interaction.guild.id,
                interaction.user.id,
            )
        )


class _BuilderCreateButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="모집 시작",
            emoji="📣",
            style=discord.ButtonStyle.success,
            custom_id="recruit:builder:create",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitBuilderView):
            await view.create_recruit(interaction)


class _SuccessManageButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="관리 화면", emoji="⚙️", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, RecruitSuccessView):
            return
        from .manage import RecruitManageView

        await interaction.response.edit_message(
            view=RecruitManageView(
                view.bot,
                view.store,
                view.state,
                interaction.user.id,
            )
        )


class RecruitSuccessView(discord.ui.LayoutView):
    def __init__(
        self,
        bot: commands.Bot,
        store: RecruitStore,
        state: RecruitState,
        channel_mention: str,
        jump_url: str,
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.store = store
        self.state = state
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "# ✅ PARTY CREATED\n"
                    f"{channel_mention}에 모집을 등록했어요. 이제 참가 현황을 기다리면 됩니다."
                ),
                discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
                discord.ui.TextDisplay(
                    f"**{mode_emoji(str(state['mode']))} 모드**　{state['mode']}\n"
                    f"**🏆 티어**　{state['tier']}\n"
                    f"**{role_emoji(str(state['role']))} 역할**　{state['role']}\n"
                    f"**👥 목표 인원**　{state['max_members']}명"
                ),
                discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
                discord.ui.ActionRow(
                    discord.ui.Button(
                        label="공개 글 열기",
                        emoji="↗️",
                        style=discord.ButtonStyle.link,
                        url=jump_url,
                    ),
                    _SuccessManageButton(),
                ),
                accent_color=SUCCESS_COLOR,
            )
        )


class RecruitBuilderView(discord.ui.LayoutView):
    """모집 생성 과정을 한 화면에서 처리하는 개인 설정 화면."""

    def __init__(
        self,
        bot: commands.Bot,
        store: RecruitStore,
        source_interaction: discord.Interaction,
    ) -> None:
        super().__init__(timeout=600)
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
        await interaction.response.send_message("이 설정 화면은 모집을 시작한 사람만 사용할 수 있습니다.", ephemeral=True)
        return False

    def rebuild(self) -> None:
        self.clear_items()
        note_text = self.note or "작성하지 않음"
        container = discord.ui.Container(accent_color=ACCENT_COLOR)
        container.add_item(
            discord.ui.TextDisplay(
                "# ➕ CREATE PARTY\n"
                "`1 모드`　›　`2 티어`　›　`3 역할`　›　`4 인원`　›　`5 생성`"
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.TextDisplay(
                "## 미리보기\n"
                f"**{mode_emoji(self.mode)} 모드**　{self.mode}\n"
                f"**🏆 티어**　{self.tier}\n"
                f"**{role_emoji(self.role)} 필요한 역할**　{self.role}\n"
                f"**👥 목표 인원**　{self.max_members}명\n"
                f"**💬 파티 설명**　{note_text}"
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.ActionRow(
                _BuilderSelect(
                    self,
                    attribute_name="mode",
                    placeholder="1 · 게임 모드 선택",
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
                    placeholder="2 · 티어 범위 선택",
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
                    placeholder="3 · 필요한 역할 선택",
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
                    placeholder="4 · 목표 인원 선택",
                    specs=SIZE_OPTIONS,
                    converter=int,
                    custom_id="recruit:builder:size",
                )
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        container.add_item(
            discord.ui.ActionRow(
                _BuilderNoteButton(),
                _BuilderCancelButton(),
                _BuilderCreateButton(),
            )
        )
        container.add_item(
            discord.ui.TextDisplay(
                "-# 파티장은 첫 참가자로 자동 포함됩니다 · 생성 후 관리 화면에서 수정과 연장이 가능합니다"
            )
        )
        self.add_item(container)

    async def create_recruit(self, interaction: discord.Interaction) -> None:
        from .manage import RecruitDashboardView, RecruitNoticeView

        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if self.store.find_user_recruit(interaction.guild.id, interaction.user.id):
            await interaction.response.edit_message(
                view=RecruitDashboardView(
                    self.bot,
                    self.store,
                    interaction.guild.id,
                    interaction.user.id,
                )
            )
            return

        target_channel = self._resolve_target_channel(interaction)
        if target_channel is None:
            await interaction.response.send_message(
                view=RecruitNoticeView(
                    "모집 채널을 찾지 못했어요",
                    "관리자가 모집 패널을 설치했는지 확인해 주세요.",
                    kind="warning",
                ),
                ephemeral=True,
            )
            return

        created_at = self.store.now()
        voice_state = interaction.user.voice
        voice_channel_id = voice_state.channel.id if voice_state and voice_state.channel else None
        state: RecruitState = {
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
            message = await target_channel.send(view=RecruitPostView(self.bot, self.store, state))
        except discord.HTTPException:
            await interaction.edit_original_response(
                view=RecruitNoticeView(
                    "모집 글을 만들지 못했어요",
                    "봇의 메시지 전송 권한과 채널 접근 권한을 확인해 주세요.",
                    kind="danger",
                )
            )
            return

        state["message_id"] = message.id
        self.store.add(state)
        await refresh_panel(self.bot, self.store, interaction.guild.id)
        await interaction.edit_original_response(
            view=RecruitSuccessView(
                self.bot,
                self.store,
                state,
                target_channel.mention,
                message.jump_url,
            )
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
