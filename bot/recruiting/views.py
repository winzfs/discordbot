"""Components V2 기반 고정 모집 패널과 개별 모집 게시물."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .render import (
    ACCENT_COLOR,
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

logger = logging.getLogger(__name__)
DEFAULT_EXPIRE_SECONDS = 90 * 60


def _v2_edit_kwargs(view: discord.ui.LayoutView) -> dict[str, object]:
    """기존 content/embed 메시지를 V2 레이아웃으로 안전하게 교체한다."""
    return {
        "content": None,
        "embed": None,
        "attachments": [],
        "view": view,
    }


async def refresh_panel(bot: commands.Bot, store: RecruitStore, guild_id: int) -> None:
    config = store.get_panel(guild_id)
    if not config:
        return

    channel = bot.get_channel(int(config.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        return

    view = RecruitPanelView(bot, store, guild_id)
    try:
        message = await channel.fetch_message(int(config.get("panel_message_id", 0)))
        await message.edit(**_v2_edit_kwargs(view))
    except (discord.NotFound, discord.Forbidden):
        try:
            message = await channel.send(view=view)
        except discord.HTTPException:
            logger.exception("모집 패널 재생성 실패: guild=%s", guild_id)
            return
        store.set_panel(guild_id, channel.id, message.id)
    except discord.HTTPException:
        logger.exception("모집 패널 갱신 실패: guild=%s", guild_id)


class _PanelCreateButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="파티 모집하기",
            emoji="📣",
            style=discord.ButtonStyle.success,
            custom_id="recruit:panel:create",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitPanelView):
            await view.open_builder(interaction)


class _PanelRefreshButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="목록 새로고침",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            custom_id="recruit:panel:refresh",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitPanelView):
            await view.refresh(interaction)


class RecruitPanelView(discord.ui.LayoutView):
    def __init__(self, bot: commands.Bot, store: RecruitStore, guild_id: int | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.store = store
        self.guild_id = guild_id
        self._build()

    def _build(self) -> None:
        active = self.store.open_for_guild(self.guild_id) if self.guild_id else []
        container = discord.ui.Container(accent_color=ACCENT_COLOR)
        container.add_item(
            discord.ui.TextDisplay(
                "## 🎮 오버워치 파티 모집\n"
                "> 조건을 고르고 모집 글을 만들면 참가자와 현황이 실시간으로 정리됩니다."
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

        if active:
            container.add_item(
                discord.ui.TextDisplay(f"### 🔥 지금 모집 중 · **{len(active)}건**")
            )
            for state in active[:8]:
                container.add_item(
                    discord.ui.Section(
                        compact_party_text(state),
                        accessory=discord.ui.Button(
                            label="모집글 열기",
                            emoji="↗️",
                            style=discord.ButtonStyle.link,
                            url=party_link(state),
                        ),
                    )
                )
            if len(active) > 8:
                container.add_item(
                    discord.ui.TextDisplay(f"-# 화면에 표시되지 않은 모집이 {len(active) - 8}건 더 있습니다.")
                )
        else:
            container.add_item(
                discord.ui.TextDisplay(
                    "### 💤 현재 모집 중인 파티가 없습니다\n"
                    "아래 버튼을 눌러 첫 파티를 열어보세요. 설정은 1분도 걸리지 않습니다."
                )
            )

        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        container.add_item(
            discord.ui.ActionRow(
                _PanelCreateButton(),
                _PanelRefreshButton(),
            )
        )
        container.add_item(
            discord.ui.TextDisplay(
                "-# 모집 글은 90분 뒤 자동 정리됩니다 · 한 사람은 한 파티에만 참가할 수 있습니다"
            )
        )
        self.add_item(container)

    async def open_builder(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if self.store.find_user_recruit(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                "이미 참가 중인 모집이 있습니다. 기존 모집을 정리한 뒤 다시 시도해 주세요.",
                ephemeral=True,
            )
            return

        from .builder import RecruitBuilderView

        builder = RecruitBuilderView(self.bot, self.store, interaction)
        await interaction.response.send_message(view=builder, ephemeral=True)

    async def refresh(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_panel(self.bot, self.store, interaction.guild.id)
        await interaction.followup.send("모집 목록을 새로고침했습니다.", ephemeral=True)


class _PostJoinButton(discord.ui.Button):
    def __init__(self, disabled: bool) -> None:
        super().__init__(
            label="참가",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id="recruit:post:join",
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitPostView):
            await view.join(interaction)


class _PostLeaveButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="참가 취소",
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            custom_id="recruit:post:leave",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitPostView):
            await view.leave(interaction)


class _PostToggleButton(discord.ui.Button):
    def __init__(self, closed: bool) -> None:
        super().__init__(
            label="재개" if closed else "마감",
            emoji="🔓" if closed else "🔒",
            style=discord.ButtonStyle.primary,
            custom_id="recruit:post:close",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitPostView):
            await view.toggle_closed(interaction)


class _PostDeleteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="삭제",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            custom_id="recruit:post:delete",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, RecruitPostView):
            await view.delete(interaction)


class RecruitPostView(discord.ui.LayoutView):
    def __init__(self, bot: commands.Bot, store: RecruitStore, state: RecruitState) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.store = store
        self.state = state
        self._build()

    def _build(self) -> None:
        count, maximum = member_count(self.state)
        status_icon, status_text, accent_color = status_info(self.state)
        note = str(self.state.get("note") or "편하게 참가하고 함께 플레이해요.")

        container = discord.ui.Container(accent_color=accent_color)
        container.add_item(
            discord.ui.TextDisplay(
                f"## {mode_emoji(str(self.state['mode']))} {self.state['mode']} 파티\n"
                f"> {note}"
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.TextDisplay(
                f"**{status_icon} {status_text}**  ·  **{count}/{maximum}명**\n"
                f"`{progress_bar(count, maximum)}`"
            )
        )
        container.add_item(
            discord.ui.TextDisplay(
                f"**🏆 티어**  {self.state['tier']}\n"
                f"**{role_emoji(str(self.state['role']))} 필요한 역할**  {self.state['role']}\n"
                f"**👑 파티장**  <@{self.state['host_id']}>"
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            discord.ui.TextDisplay(f"### 👥 참가자\n{member_mentions(self.state)}")
        )
        container.add_item(
            discord.ui.TextDisplay(
                f"-# 생성 <t:{self.state['created_at']}:R> · 자동 만료 <t:{self.state['expires_at']}:R>"
            )
        )

        closed = bool(self.state.get("closed", False))
        full = count >= maximum
        buttons: list[discord.ui.Button] = [
            _PostJoinButton(disabled=closed or full),
            _PostLeaveButton(),
            _PostToggleButton(closed=closed),
        ]
        voice_channel_id = self.state.get("voice_channel_id")
        if voice_channel_id:
            buttons.append(
                discord.ui.Button(
                    label="음성방 이동",
                    emoji="🔊",
                    style=discord.ButtonStyle.link,
                    url=f"https://discord.com/channels/{self.state['guild_id']}/{voice_channel_id}",
                )
            )
        buttons.append(_PostDeleteButton())

        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        container.add_item(discord.ui.ActionRow(*buttons))
        container.add_item(
            discord.ui.TextDisplay(
                "-# 참가가 확정된 경우에만 눌러 주세요 · 마감과 삭제는 파티장 또는 관리자만 가능합니다"
            )
        )
        self.add_item(container)

    def _can_manage(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == int(self.state["host_id"]):
            return True
        return isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages

    async def _edit(self, interaction: discord.Interaction) -> None:
        if interaction.message:
            replacement = RecruitPostView(self.bot, self.store, self.state)
            await interaction.message.edit(**_v2_edit_kwargs(replacement))
        await refresh_panel(self.bot, self.store, int(self.state["guild_id"]))

    async def join(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        if not self.store.is_open(self.state):
            await interaction.response.send_message("이미 마감되었거나 만료된 모집입니다.", ephemeral=True)
            return
        if interaction.user.id in self.state["member_ids"]:
            await interaction.response.send_message("이미 이 파티에 참가 중입니다.", ephemeral=True)
            return

        other = self.store.find_user_recruit(interaction.guild.id, interaction.user.id)
        if other and int(other["message_id"]) != int(self.state["message_id"]):
            await interaction.response.send_message("다른 모집에 참가 중입니다.", ephemeral=True)
            return
        if len(self.state["member_ids"]) >= int(self.state["max_members"]):
            await interaction.response.send_message("파티 정원이 가득 찼습니다.", ephemeral=True)
            return

        self.state["member_ids"].append(interaction.user.id)
        if len(self.state["member_ids"]) >= int(self.state["max_members"]):
            self.state["closed"] = True
            self.state["closed_reason"] = "정원 마감"
        self.store.save()
        await interaction.response.defer()
        await self._edit(interaction)

        if self.state.get("closed_reason") == "정원 마감" and interaction.channel:
            try:
                await interaction.channel.send(
                    f"🎉 <@{self.state['host_id']}> 파티 정원이 모두 찼습니다.",
                    reference=interaction.message,
                    mention_author=False,
                    delete_after=30,
                )
            except discord.HTTPException:
                pass

    async def leave(self, interaction: discord.Interaction) -> None:
        user_id = interaction.user.id
        if user_id == int(self.state["host_id"]):
            await interaction.response.send_message("파티장은 모집 글을 삭제해 주세요.", ephemeral=True)
            return
        if user_id not in self.state["member_ids"]:
            await interaction.response.send_message("이 파티에 참가 중이 아닙니다.", ephemeral=True)
            return

        self.state["member_ids"].remove(user_id)
        if self.state.get("closed_reason") == "정원 마감":
            self.state["closed"] = False
            self.state["closed_reason"] = ""
        self.store.save()
        await interaction.response.defer()
        await self._edit(interaction)

    async def toggle_closed(self, interaction: discord.Interaction) -> None:
        if not self._can_manage(interaction):
            await interaction.response.send_message("파티장 또는 관리자만 상태를 변경할 수 있습니다.", ephemeral=True)
            return

        if self.state.get("closed", False):
            if len(self.state["member_ids"]) >= int(self.state["max_members"]):
                await interaction.response.send_message("정원이 가득 차 있어 재개할 수 없습니다.", ephemeral=True)
                return
            self.state["closed"] = False
            self.state["closed_reason"] = ""
            self.state["expires_at"] = self.store.now() + DEFAULT_EXPIRE_SECONDS
        else:
            self.state["closed"] = True
            self.state["closed_reason"] = "파티장 마감"

        self.store.save()
        await interaction.response.defer()
        await self._edit(interaction)

    async def delete(self, interaction: discord.Interaction) -> None:
        if not self._can_manage(interaction):
            await interaction.response.send_message("파티장 또는 관리자만 삭제할 수 있습니다.", ephemeral=True)
            return

        self.store.remove(int(self.state["message_id"]))
        await interaction.response.defer()
        try:
            if interaction.message:
                await interaction.message.delete()
        finally:
            await refresh_panel(self.bot, self.store, int(self.state["guild_id"]))
