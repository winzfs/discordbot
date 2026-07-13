"""파티 모집의 개인 대시보드, 관리, 수정, 확인 화면."""
from __future__ import annotations

from typing import Any, Callable

import discord
from discord.ext import commands

from .render import (
    ACCENT_COLOR,
    CLOSED_COLOR,
    SUCCESS_COLOR,
    compact_party_text,
    member_count,
    member_mentions,
    mode_emoji,
    party_link,
    progress_bar,
    role_emoji,
    status_info,
)
from .store import RecruitState, RecruitStore
from .views import delete_recruit_post, refresh_panel, refresh_recruit_post

NOTICE_COLORS = {
    "success": SUCCESS_COLOR,
    "warning": 0xFEE75C,
    "danger": 0xED4245,
    "info": 0x5865F2,
}
NOTICE_ICONS = {
    "success": "✅",
    "warning": "⚠️",
    "danger": "🗑️",
    "info": "ℹ️",
}
DEFAULT_EXPIRE_SECONDS = 90 * 60


class RecruitNoticeView(discord.ui.LayoutView):
    """짧은 결과와 안내를 앱 카드처럼 표시한다."""

    def __init__(self, title: str, description: str, *, kind: str = "info") -> None:
        super().__init__(timeout=180)
        icon = NOTICE_ICONS.get(kind, NOTICE_ICONS["info"])
        color = NOTICE_COLORS.get(kind, NOTICE_COLORS["info"])
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(f"## {icon} {title}\n{description}"),
                accent_color=color,
            )
        )


class _DashboardCreateButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="새 파티 만들기", emoji="➕", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, RecruitDashboardView):
            return
        from .builder import RecruitBuilderView

        await interaction.response.edit_message(
            view=RecruitBuilderView(view.bot, view.store, interaction)
        )


class _DashboardManageButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="관리 화면", emoji="⚙️", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, RecruitDashboardView):
            return
        state = view.current_state()
        if state is None:
            await interaction.response.edit_message(
                view=RecruitDashboardView(view.bot, view.store, view.guild_id, view.user_id)
            )
            return
        await interaction.response.edit_message(
            view=RecruitManageView(view.bot, view.store, state, interaction.user.id)
        )


class _DashboardLeaveButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="파티 나가기", emoji="↩️", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, RecruitDashboardView):
            return
        state = view.current_state()
        if state is None:
            await interaction.response.edit_message(
                view=RecruitDashboardView(view.bot, view.store, view.guild_id, view.user_id)
            )
            return
        await interaction.response.edit_message(
            view=RecruitLeaveConfirmView(
                view.bot,
                view.store,
                state,
                interaction.user.id,
            )
        )


class _DashboardRefreshButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="새로고침", emoji="🔄", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitDashboardView):
            await interaction.response.edit_message(
                view=RecruitDashboardView(view.bot, view.store, view.guild_id, view.user_id)
            )


class RecruitDashboardView(discord.ui.LayoutView):
    """사용자에게만 표시되는 내 파티 홈 화면."""

    def __init__(
        self,
        bot: commands.Bot,
        store: RecruitStore,
        guild_id: int,
        user_id: int,
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.store = store
        self.guild_id = guild_id
        self.user_id = user_id
        self._build()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("본인의 파티 화면만 조작할 수 있습니다.", ephemeral=True)
        return False

    def current_state(self) -> RecruitState | None:
        return self.store.find_user_recruit(self.guild_id, self.user_id)

    def _build(self) -> None:
        state = self.current_state()
        container = discord.ui.Container(accent_color=ACCENT_COLOR)
        container.add_item(
            discord.ui.TextDisplay(
                "# 👤 MY PARTY\n"
                "참가 중인 파티와 내가 만든 모집을 개인 화면에서 관리합니다."
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

        if state is None:
            container.add_item(
                discord.ui.TextDisplay(
                    "## 💤 현재 참가 중인 파티가 없어요\n"
                    "새 모집을 만들거나 공개 모집 글에서 참가할 수 있습니다."
                )
            )
            container.add_item(discord.ui.ActionRow(_DashboardCreateButton(), _DashboardRefreshButton()))
        else:
            is_host = self.user_id == int(state["host_id"])
            role = "파티장" if is_host else "참가자"
            container.add_item(
                discord.ui.TextDisplay(
                    f"**내 상태**　`{role}`\n"
                    f"{compact_party_text(state)}"
                )
            )
            container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
            buttons: list[discord.ui.Button] = [
                discord.ui.Button(
                    label="모집 글 열기",
                    emoji="↗️",
                    style=discord.ButtonStyle.link,
                    url=party_link(state),
                )
            ]
            if is_host:
                buttons.append(_DashboardManageButton())
            else:
                buttons.append(_DashboardLeaveButton())
            buttons.append(_DashboardRefreshButton())
            container.add_item(discord.ui.ActionRow(*buttons))
            container.add_item(
                discord.ui.TextDisplay(
                    "-# 이 화면은 나에게만 보입니다 · 공개 모집 글과 상태가 실시간으로 연결됩니다"
                )
            )
        self.add_item(container)


class _ManageEditButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="정보 수정", emoji="✏️", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitManageView):
            await interaction.response.edit_message(
                view=RecruitEditView(
                    view.bot,
                    view.store,
                    view.state,
                    view.viewer_id,
                    interaction,
                )
            )


class _ManageToggleButton(discord.ui.Button):
    def __init__(self, closed: bool) -> None:
        super().__init__(
            label="모집 재개" if closed else "모집 마감",
            emoji="🔓" if closed else "🔒",
            style=discord.ButtonStyle.success if closed else discord.ButtonStyle.secondary,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitManageView):
            await view.toggle(interaction)


class _ManageExtendButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="90분 연장", emoji="⏱️", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitManageView):
            await view.extend(interaction)


class _ManageVoiceButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="현재 음성방 연결", emoji="🔊", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitManageView):
            await view.sync_voice(interaction)


class _ManageDeleteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="모집 삭제", emoji="🗑️", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitManageView):
            await interaction.response.edit_message(
                view=RecruitDeleteConfirmView(
                    view.bot,
                    view.store,
                    view.state,
                    view.viewer_id,
                )
            )


class _ManageBackButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="내 파티로", emoji="←", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitManageView):
            await interaction.response.edit_message(
                view=RecruitDashboardView(
                    view.bot,
                    view.store,
                    int(view.state["guild_id"]),
                    view.viewer_id,
                )
            )


class RecruitManageView(discord.ui.LayoutView):
    """파티장과 관리자에게만 열리는 운영 화면."""

    def __init__(
        self,
        bot: commands.Bot,
        store: RecruitStore,
        state: RecruitState,
        viewer_id: int,
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.store = store
        self.state = state
        self.viewer_id = viewer_id
        self._build()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == int(self.state["host_id"]):
            return True
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages:
            return True
        await interaction.response.send_message("파티장 또는 관리자만 사용할 수 있습니다.", ephemeral=True)
        return False

    def _build(self) -> None:
        count, maximum = member_count(self.state)
        status_icon, status_text, accent = status_info(self.state)
        voice_channel_id = self.state.get("voice_channel_id")
        container = discord.ui.Container(accent_color=accent)
        container.add_item(
            discord.ui.TextDisplay(
                "# ⚙️ PARTY CONTROL\n"
                f"**{status_icon} {status_text}**　`{count}/{maximum}명`　"
                f"`{progress_bar(count, maximum)}`"
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.TextDisplay(
                f"**{mode_emoji(str(self.state['mode']))} 모드**　{self.state['mode']}\n"
                f"**🏆 티어**　{self.state['tier']}\n"
                f"**{role_emoji(str(self.state['role']))} 역할**　{self.state['role']}\n"
                f"**🔊 음성방**　{f'<#{voice_channel_id}>' if voice_channel_id else '연결되지 않음'}\n"
                f"**⏱️ 만료**　<t:{self.state['expires_at']}:R>"
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(discord.ui.TextDisplay(f"## 👥 참가자\n{member_mentions(self.state)}"))
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        container.add_item(
            discord.ui.ActionRow(
                _ManageEditButton(),
                _ManageToggleButton(bool(self.state.get("closed", False))),
                _ManageExtendButton(),
                _ManageVoiceButton(),
            )
        )
        container.add_item(
            discord.ui.ActionRow(
                discord.ui.Button(
                    label="공개 글 열기",
                    emoji="↗️",
                    style=discord.ButtonStyle.link,
                    url=party_link(self.state),
                ),
                _ManageBackButton(),
                _ManageDeleteButton(),
            )
        )
        container.add_item(
            discord.ui.TextDisplay(
                "-# 수정 사항은 공개 모집 글과 고정 모집 허브에 즉시 반영됩니다"
            )
        )
        self.add_item(container)

    async def _save_and_redraw(self, interaction: discord.Interaction) -> None:
        self.store.save()
        await refresh_recruit_post(self.bot, self.store, self.state)
        await refresh_panel(self.bot, self.store, int(self.state["guild_id"]))
        await interaction.edit_original_response(
            view=RecruitManageView(
                self.bot,
                self.store,
                self.state,
                self.viewer_id,
            )
        )

    async def toggle(self, interaction: discord.Interaction) -> None:
        count, maximum = member_count(self.state)
        if self.state.get("closed", False):
            if count >= maximum:
                await interaction.response.send_message(
                    view=RecruitNoticeView(
                        "재개할 수 없어요",
                        "현재 인원이 정원과 같아서 먼저 목표 인원을 늘려야 합니다.",
                        kind="warning",
                    ),
                    ephemeral=True,
                )
                return
            self.state["closed"] = False
            self.state["closed_reason"] = ""
            self.state["expires_at"] = self.store.now() + DEFAULT_EXPIRE_SECONDS
        else:
            self.state["closed"] = True
            self.state["closed_reason"] = "파티장 마감"

        await interaction.response.defer(ephemeral=True)
        await self._save_and_redraw(interaction)

    async def extend(self, interaction: discord.Interaction) -> None:
        baseline = max(self.store.now(), int(self.state.get("expires_at", 0)))
        self.state["expires_at"] = baseline + DEFAULT_EXPIRE_SECONDS
        await interaction.response.defer(ephemeral=True)
        await self._save_and_redraw(interaction)

    async def sync_voice(self, interaction: discord.Interaction) -> None:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        voice = member.voice if member else None
        if voice is None or voice.channel is None:
            await interaction.response.send_message(
                view=RecruitNoticeView(
                    "음성방을 찾지 못했어요",
                    "먼저 연결할 음성 채널에 입장한 뒤 다시 눌러 주세요.",
                    kind="warning",
                ),
                ephemeral=True,
            )
            return
        self.state["voice_channel_id"] = voice.channel.id
        await interaction.response.defer(ephemeral=True)
        await self._save_and_redraw(interaction)


class _EditSelect(discord.ui.Select):
    def __init__(
        self,
        editor: "RecruitEditView",
        *,
        attribute_name: str,
        placeholder: str,
        specs: tuple[Any, ...],
        converter: Callable[[str], Any] = str,
    ) -> None:
        from .builder import select_options

        selected = str(getattr(editor, attribute_name))
        super().__init__(
            placeholder=placeholder,
            options=select_options(specs, selected),
        )
        self.attribute_name = attribute_name
        self.converter = converter

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, RecruitEditView):
            return
        setattr(view, self.attribute_name, self.converter(self.values[0]))
        view.rebuild()
        await interaction.response.edit_message(view=view)


class RecruitEditNoteModal(discord.ui.Modal, title="파티 설명 수정"):
    def __init__(self, editor: "RecruitEditView") -> None:
        super().__init__()
        self.editor = editor
        self.note_input = discord.ui.TextInput(
            placeholder="예: 마이크 자유, 2~3판 예정, 편하게 하실 분",
            default=editor.note or None,
            required=False,
            max_length=180,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(
            discord.ui.Label(
                text="모집 메모",
                description="파티 분위기와 플레이 계획을 알려 주세요.",
                component=self.note_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.editor.note = str(self.note_input.value).strip()
        self.editor.rebuild()
        await interaction.response.send_message(
            view=RecruitNoticeView("메모를 반영했어요", "저장 버튼을 누르면 공개 글에 적용됩니다.", kind="success"),
            ephemeral=True,
        )
        try:
            await self.editor.source_interaction.edit_original_response(view=self.editor)
        except discord.HTTPException:
            pass


class _EditNoteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="메모 수정", emoji="💬", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitEditView):
            await interaction.response.send_modal(RecruitEditNoteModal(view))


class _EditSaveButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="변경 저장", emoji="💾", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitEditView):
            await view.save(interaction)


class _EditBackButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="취소", emoji="←", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitEditView):
            await interaction.response.edit_message(
                view=RecruitManageView(
                    view.bot,
                    view.store,
                    view.state,
                    view.viewer_id,
                )
            )


class RecruitEditView(discord.ui.LayoutView):
    """공개 모집 정보를 선택 메뉴로 수정한다."""

    def __init__(
        self,
        bot: commands.Bot,
        store: RecruitStore,
        state: RecruitState,
        viewer_id: int,
        source_interaction: discord.Interaction,
    ) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.store = store
        self.state = state
        self.viewer_id = viewer_id
        self.source_interaction = source_interaction
        self.mode = str(state["mode"])
        self.tier = str(state["tier"])
        self.role = str(state["role"])
        self.max_members = int(state["max_members"])
        self.note = str(state.get("note") or "")
        self.rebuild()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == int(self.state["host_id"]):
            return True
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages:
            return True
        await interaction.response.send_message("파티장 또는 관리자만 수정할 수 있습니다.", ephemeral=True)
        return False

    def rebuild(self) -> None:
        from .builder import MODE_OPTIONS, ROLE_OPTIONS, SIZE_OPTIONS, TIER_OPTIONS

        self.clear_items()
        note_text = self.note or "작성하지 않음"
        container = discord.ui.Container(accent_color=ACCENT_COLOR)
        container.add_item(
            discord.ui.TextDisplay(
                "# ✏️ EDIT PARTY\n"
                "선택 내용을 확인하고 저장하면 공개 모집 글이 바로 갱신됩니다."
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.TextDisplay(
                f"**{mode_emoji(self.mode)} 모드**　{self.mode}\n"
                f"**🏆 티어**　{self.tier}\n"
                f"**{role_emoji(self.role)} 역할**　{self.role}\n"
                f"**👥 목표 인원**　{self.max_members}명\n"
                f"**💬 메모**　{note_text}"
            )
        )
        container.add_item(discord.ui.ActionRow(_EditSelect(self, attribute_name="mode", placeholder="게임 모드", specs=MODE_OPTIONS)))
        container.add_item(discord.ui.ActionRow(_EditSelect(self, attribute_name="tier", placeholder="티어 범위", specs=TIER_OPTIONS)))
        container.add_item(discord.ui.ActionRow(_EditSelect(self, attribute_name="role", placeholder="필요 역할", specs=ROLE_OPTIONS)))
        container.add_item(
            discord.ui.ActionRow(
                _EditSelect(
                    self,
                    attribute_name="max_members",
                    placeholder="목표 인원",
                    specs=SIZE_OPTIONS,
                    converter=int,
                )
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        container.add_item(discord.ui.ActionRow(_EditNoteButton(), _EditBackButton(), _EditSaveButton()))
        self.add_item(container)

    async def save(self, interaction: discord.Interaction) -> None:
        current = len(self.state.get("member_ids", []))
        if self.max_members < current:
            await interaction.response.send_message(
                view=RecruitNoticeView(
                    "인원을 줄일 수 없어요",
                    f"현재 참가자가 {current}명이어서 목표 인원은 {current}명 이상이어야 합니다.",
                    kind="warning",
                ),
                ephemeral=True,
            )
            return

        self.state.update(
            {
                "mode": self.mode,
                "tier": self.tier,
                "role": self.role,
                "max_members": self.max_members,
                "note": self.note,
            }
        )
        if self.state.get("closed_reason") == "정원 마감" and current < self.max_members:
            self.state["closed"] = False
            self.state["closed_reason"] = ""

        self.store.save()
        await interaction.response.defer(ephemeral=True)
        await refresh_recruit_post(self.bot, self.store, self.state)
        await refresh_panel(self.bot, self.store, int(self.state["guild_id"]))
        await interaction.edit_original_response(
            view=RecruitManageView(
                self.bot,
                self.store,
                self.state,
                self.viewer_id,
            )
        )


class _ConfirmDeleteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="정말 삭제", emoji="🗑️", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitDeleteConfirmView):
            await view.confirm(interaction)


class _CancelDeleteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="돌아가기", emoji="←", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitDeleteConfirmView):
            await interaction.response.edit_message(
                view=RecruitManageView(view.bot, view.store, view.state, view.viewer_id)
            )


class RecruitDeleteConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        bot: commands.Bot,
        store: RecruitStore,
        state: RecruitState,
        viewer_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.store = store
        self.state = state
        self.viewer_id = viewer_id
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "# 🗑️ DELETE PARTY\n"
                    "이 모집을 삭제하면 참가자 목록과 공개 글이 함께 사라집니다.\n\n"
                    f"{compact_party_text(state)}"
                ),
                discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
                discord.ui.ActionRow(_CancelDeleteButton(), _ConfirmDeleteButton()),
                accent_color=NOTICE_COLORS["danger"],
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == int(self.state["host_id"]):
            return True
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages:
            return True
        await interaction.response.send_message("파티장 또는 관리자만 삭제할 수 있습니다.", ephemeral=True)
        return False

    async def confirm(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        self.store.remove(int(self.state["message_id"]))
        await delete_recruit_post(self.bot, self.state)
        await refresh_panel(self.bot, self.store, int(self.state["guild_id"]))
        await interaction.edit_original_response(
            view=RecruitNoticeView(
                "모집을 삭제했어요",
                "공개 모집 글과 참가자 정보가 정리되었습니다.",
                kind="success",
            )
        )


class _ConfirmLeaveButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="파티 나가기", emoji="↩️", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitLeaveConfirmView):
            await view.confirm(interaction)


class _CancelLeaveButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="계속 참가", emoji="←", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitLeaveConfirmView):
            await interaction.response.edit_message(
                view=RecruitDashboardView(
                    view.bot,
                    view.store,
                    int(view.state["guild_id"]),
                    view.user_id,
                )
            )


class RecruitLeaveConfirmView(discord.ui.LayoutView):
    def __init__(
        self,
        bot: commands.Bot,
        store: RecruitStore,
        state: RecruitState,
        user_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.store = store
        self.state = state
        self.user_id = user_id
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "# ↩️ LEAVE PARTY\n"
                    "참가를 취소하면 자리가 다시 열리고 파티장에게 즉시 반영됩니다.\n\n"
                    f"{compact_party_text(state)}"
                ),
                discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
                discord.ui.ActionRow(_CancelLeaveButton(), _ConfirmLeaveButton()),
                accent_color=CLOSED_COLOR,
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("본인의 참가만 취소할 수 있습니다.", ephemeral=True)
        return False

    async def confirm(self, interaction: discord.Interaction) -> None:
        if self.user_id == int(self.state["host_id"]):
            await interaction.response.edit_message(
                view=RecruitNoticeView(
                    "파티장은 나갈 수 없어요",
                    "관리 화면에서 모집을 삭제해 주세요.",
                    kind="warning",
                )
            )
            return
        if self.user_id not in self.state.get("member_ids", []):
            await interaction.response.edit_message(
                view=RecruitNoticeView(
                    "이미 참가가 취소됐어요",
                    "현재 이 파티의 참가자 목록에 없습니다.",
                    kind="info",
                )
            )
            return

        self.state["member_ids"].remove(self.user_id)
        if self.state.get("closed_reason") == "정원 마감":
            self.state["closed"] = False
            self.state["closed_reason"] = ""
        self.store.save()

        await interaction.response.defer(ephemeral=True)
        await refresh_recruit_post(self.bot, self.store, self.state)
        await refresh_panel(self.bot, self.store, int(self.state["guild_id"]))
        await interaction.edit_original_response(
            view=RecruitNoticeView(
                "파티에서 나왔어요",
                "참가 취소가 공개 모집 글에 반영되었습니다.",
                kind="success",
            )
        )
