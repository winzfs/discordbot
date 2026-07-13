"""고정 모집 패널과 개별 모집 게시물 버튼."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .render import panel_embed, recruit_embed
from .store import RecruitState, RecruitStore

logger = logging.getLogger(__name__)
DEFAULT_EXPIRE_SECONDS = 90 * 60


async def refresh_panel(bot: commands.Bot, store: RecruitStore, guild_id: int) -> None:
    config = store.get_panel(guild_id)
    if not config:
        return

    channel = bot.get_channel(int(config.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        return

    try:
        message = await channel.fetch_message(int(config.get("panel_message_id", 0)))
        await message.edit(embed=panel_embed(store, guild_id), view=RecruitPanelView(bot, store))
    except (discord.NotFound, discord.Forbidden):
        try:
            message = await channel.send(
                embed=panel_embed(store, guild_id),
                view=RecruitPanelView(bot, store),
            )
        except discord.HTTPException:
            logger.exception("모집 패널 재생성 실패: guild=%s", guild_id)
            return
        store.set_panel(guild_id, channel.id, message.id)
    except discord.HTTPException:
        logger.exception("모집 패널 갱신 실패: guild=%s", guild_id)


class RecruitPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot, store: RecruitStore) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.store = store

    @discord.ui.button(
        label="파티 모집하기",
        emoji="📣",
        style=discord.ButtonStyle.success,
        custom_id="recruit:panel:create",
    )
    async def open_builder(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("서버 안에서만 사용할 수 있습니다.", ephemeral=True)
            return
        if self.store.find_user_recruit(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                "이미 참가 중인 모집이 있습니다. 기존 모집을 정리한 뒤 다시 시도해 주세요.",
                ephemeral=True,
            )
            return

        # 순환 import를 피하기 위해 버튼을 누르는 시점에 불러온다.
        from .builder import RecruitBuilderView

        builder = RecruitBuilderView(self.bot, self.store, interaction)
        await interaction.response.send_message(embed=builder.embed(), view=builder, ephemeral=True)

    @discord.ui.button(
        label="목록 새로고침",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:panel:refresh",
    )
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True)
        await refresh_panel(self.bot, self.store, interaction.guild.id)
        await interaction.followup.send("모집 목록을 새로고침했습니다.", ephemeral=True)


class RecruitPostView(discord.ui.View):
    def __init__(self, bot: commands.Bot, store: RecruitStore, state: RecruitState) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.store = store
        self.state = state
        self._sync_buttons()

        voice_channel_id = state.get("voice_channel_id")
        if voice_channel_id:
            self.add_item(
                discord.ui.Button(
                    label="음성방 이동",
                    emoji="🔊",
                    style=discord.ButtonStyle.link,
                    url=f"https://discord.com/channels/{state['guild_id']}/{voice_channel_id}",
                    row=1,
                )
            )

    def _sync_buttons(self) -> None:
        full = len(self.state.get("member_ids", [])) >= int(self.state["max_members"])
        self.join_button.disabled = self.state.get("closed", False) or full
        self.close_button.label = "재개" if self.state.get("closed", False) else "마감"
        self.close_button.emoji = "🔓" if self.state.get("closed", False) else "🔒"

    def _can_manage(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == int(self.state["host_id"]):
            return True
        return isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages

    async def _edit(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        if interaction.message:
            await interaction.message.edit(embed=recruit_embed(self.state), view=self)
        await refresh_panel(self.bot, self.store, int(self.state["guild_id"]))

    @discord.ui.button(
        label="참가",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="recruit:post:join",
        row=0,
    )
    async def join_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
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

    @discord.ui.button(
        label="참가 취소",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:post:leave",
        row=0,
    )
    async def leave_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
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

    @discord.ui.button(
        label="마감",
        emoji="🔒",
        style=discord.ButtonStyle.primary,
        custom_id="recruit:post:close",
        row=0,
    )
    async def close_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
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

    @discord.ui.button(
        label="삭제",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="recruit:post:delete",
        row=0,
    )
    async def delete_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
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
