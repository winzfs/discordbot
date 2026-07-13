"""오버워치 파티 모집 시스템 Cog."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.recruiting.builder import RecruitBuilderView
from bot.recruiting.store import RecruitStore
from bot.recruiting.views import RecruitPanelView, RecruitPostView, refresh_panel

logger = logging.getLogger(__name__)


class RecruitCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.store = RecruitStore()

    async def cog_load(self) -> None:
        self.bot.add_view(RecruitPanelView(self.bot, self.store))
        for state in self.store.recruits.values():
            if self.store.is_live(state) and int(state.get("message_id", 0)):
                self.bot.add_view(
                    RecruitPostView(self.bot, self.store, state),
                    message_id=int(state["message_id"]),
                )
        self.cleanup_expired.start()

    async def cog_unload(self) -> None:
        self.cleanup_expired.cancel()

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

        builder = RecruitBuilderView(self.bot, self.store, interaction)
        await interaction.response.send_message(view=builder, ephemeral=True)

    @app_commands.command(name="모집", description="설정창에서 오버워치 파티원을 모집합니다.")
    async def recruit(self, interaction: discord.Interaction) -> None:
        await self.open_builder(interaction)

    @app_commands.command(name="모집채널설정", description="[관리자] 현재 채널에 파티 모집 패널을 설치합니다.")
    @app_commands.default_permissions(administrator=True)
    async def setup_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("일반 텍스트 채널에서만 설치할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await self._delete_old_panel(interaction.guild.id)

        try:
            message = await interaction.channel.send(
                view=RecruitPanelView(self.bot, self.store, interaction.guild.id),
            )
        except discord.HTTPException:
            await interaction.followup.send("패널 생성에 실패했습니다. 봇 권한을 확인해 주세요.", ephemeral=True)
            return

        self.store.set_panel(interaction.guild.id, interaction.channel.id, message.id)
        try:
            await message.pin(reason="오버워치 파티 모집 패널")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await interaction.followup.send("이 채널에 Components V2 파티 모집 패널을 설치했습니다.", ephemeral=True)

    async def _delete_old_panel(self, guild_id: int) -> None:
        old_config = self.store.get_panel(guild_id)
        if not old_config:
            return
        old_channel = self.bot.get_channel(int(old_config.get("channel_id", 0)))
        if not isinstance(old_channel, discord.TextChannel):
            return
        try:
            old_message = await old_channel.fetch_message(int(old_config.get("panel_message_id", 0)))
            await old_message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def _migrate_existing_messages(self) -> None:
        """배포 전에 생성된 Embed + View 메시지를 Components V2로 자동 변환한다."""
        for guild_id in {int(value) for value in self.store.config.keys()}:
            await refresh_panel(self.bot, self.store, guild_id)

        for state in self.store.recruits.values():
            if not self.store.is_live(state):
                continue
            channel = self.bot.get_channel(int(state.get("channel_id", 0)))
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                message = await channel.fetch_message(int(state.get("message_id", 0)))
                await message.edit(
                    content=None,
                    embed=None,
                    attachments=[],
                    view=RecruitPostView(self.bot, self.store, state),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning("기존 모집 글 V2 변환 실패: message=%s", state.get("message_id"))

    @tasks.loop(minutes=1)
    async def cleanup_expired(self) -> None:
        expired = self.store.expired()
        if not expired:
            return

        affected_guilds: set[int] = set()
        for message_id, state in expired:
            self.store.recruits.pop(str(message_id), None)
            guild_id = int(state.get("guild_id", 0))
            affected_guilds.add(guild_id)
            channel = self.bot.get_channel(int(state.get("channel_id", 0)))
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        self.store.save()
        for guild_id in affected_guilds:
            await refresh_panel(self.bot, self.store, guild_id)

    @cleanup_expired.before_loop
    async def before_cleanup(self) -> None:
        await self.bot.wait_until_ready()
        await self._migrate_existing_messages()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RecruitCog(bot))
