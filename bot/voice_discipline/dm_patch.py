"""Reliability patch for DM notice editing and delivery visibility."""
from __future__ import annotations

import asyncio
import logging

import discord

from bot.cogs import voice_audit
from bot.voice_discipline import store, ui

logger = logging.getLogger(__name__)
_DM_MESSAGE_CACHE: dict[int, str] = {}
_ORIGINAL_RESULT_EMBED = ui.result_embed


class ReliableSoftbanNoticeModal(discord.ui.Modal):
    """Open immediately, then perform database work after the modal is submitted."""

    def __init__(self, guild_id: int):
        super().__init__(title="3회 경고 DM 안내문 설정", timeout=300)
        self.guild_id = guild_id
        cached = _DM_MESSAGE_CACHE.get(guild_id, store.DEFAULT_DM_MESSAGE)
        self.notice = discord.ui.TextInput(
            label="밴 처리 전에 보낼 DM 안내문",
            style=discord.TextStyle.paragraph,
            default=cached[: store.MAX_DM_TEMPLATE_LENGTH],
            min_length=1,
            max_length=store.MAX_DM_TEMPLATE_LENGTH,
            required=True,
        )
        self.add_item(self.notice)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        message = str(self.notice.value).strip()
        try:
            await asyncio.to_thread(store.set_dm_message, self.guild_id, message)
            saved = await asyncio.to_thread(store.get_dm_message, self.guild_id)
        except Exception as exc:
            logger.exception("DM 안내문 저장 실패", exc_info=exc)
            await interaction.edit_original_response(
                content=f"❌ DM 안내문 저장 실패\n오류: `{type(exc).__name__}`"
            )
            return

        _DM_MESSAGE_CACHE[self.guild_id] = saved
        await interaction.edit_original_response(
            content=(
                "✅ 3회 경고 소프트밴 DM 안내문을 저장하고 DB 재조회까지 확인했습니다.\n"
                "사용 가능 변수: `{member}` · `{server}` · `{warnings}`"
            )
        )


class ReliableDisciplineVoiceAuditView(ui.DisciplineVoiceAuditView):
    @discord.ui.button(label="DM 안내문 설정", emoji="✉️", style=discord.ButtonStyle.primary, row=3)
    async def dm_notice(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        # Discord component interactions must receive their initial response quickly.
        # Do not wait for a network database query before opening the modal.
        await interaction.response.send_modal(ReliableSoftbanNoticeModal(interaction.guild.id))


def delivery_result_embed(result: dict[str, list[dict]]) -> discord.Embed:
    embed = _ORIGINAL_RESULT_EMBED(result)
    dm_success = sum(1 for item in result["success"] if item.get("dm_sent"))
    dm_failed = len(result["dm_failed"])
    attempted = dm_success + dm_failed
    embed.add_field(
        name="📨 소프트밴 전 DM 발송 확인",
        value=(
            f"발송 시도 **{attempted}명** · 성공 **{dm_success}명** · 실패 **{dm_failed}명**\n"
            "DM은 각 대상의 밴 처리보다 먼저 실행됩니다. 실패한 대상은 위 실패 명단에 표시됩니다."
        ),
        inline=False,
    )
    return embed


def install_patch() -> None:
    ui.result_embed = delivery_result_embed
    voice_audit.VoiceAuditView = ReliableDisciplineVoiceAuditView
    logger.info("DM 안내문 즉시 모달 + 저장 재확인 + DM 발송 결과 표시 패치 적용 완료")
