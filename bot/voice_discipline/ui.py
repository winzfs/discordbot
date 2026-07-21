"""Discord UI for three-warning DM notices and soft-ban controls."""
from __future__ import annotations

import asyncio
import logging

import discord

from bot.cogs import voice_audit, voice_audit_patch
from bot.voice_discipline import service, store

logger = logging.getLogger(__name__)
_GUILD_SOFTBAN_LOCKS: dict[int, asyncio.Lock] = {}


def target_embeds(
    guild: discord.Guild,
    targets: list[service.SoftbanTarget],
    template: str,
) -> list[discord.Embed]:
    header = discord.Embed(title="🚪 경고 3회 소프트밴 관리", color=0xED4245)
    header.description = (
        "경고가 3회 이상 누적된 멤버를 확인합니다.\n"
        "실행 시 **DM 안내 → 서버 밴 → 즉시 밴 해제** 순서로 처리되어 "
        "새 초대 링크로 다시 들어올 수 있습니다."
    )
    header.add_field(name="현재 대상", value=f"{len(targets)}명", inline=True)
    header.add_field(name="처리 후 경고", value="0회로 초기화", inline=True)
    header.add_field(name="DM 실패 시", value="실패를 기록하고 소프트밴 계속", inline=True)
    header.add_field(
        name="DM 안내문 미리보기",
        value=(template[:900] + ("…" if len(template) > 900 else "")) or "설정 없음",
        inline=False,
    )
    header.set_footer(text="사용 가능 변수: {member} · {server} · {warnings}")

    if not targets:
        header.add_field(name="대상 없음", value="현재 경고 3회 이상 멤버가 없습니다.", inline=False)
        return [header]

    lines = []
    for index, target in enumerate(targets, start=1):
        blocked = service.softban_block_reason(guild, target.member)
        status = f"처리 제외 · {blocked}" if blocked else "소프트밴 가능"
        lines.append(
            f"{index}. {target.member.mention} · **{target.member.display_name}** · "
            f"경고 **{target.warnings}회** · {status}"
        )

    embeds = [header]
    chunk: list[str] = []
    length = 0
    for line in lines:
        if chunk and length + len(line) + 1 > 3800:
            embeds.append(
                discord.Embed(
                    title=f"📋 3회 경고 대상 {len(embeds)}",
                    description="\n".join(chunk),
                    color=0x5865F2,
                )
            )
            chunk = []
            length = 0
        chunk.append(line)
        length += len(line) + 1
    if chunk:
        embeds.append(
            discord.Embed(
                title=f"📋 3회 경고 대상 {len(embeds)}",
                description="\n".join(chunk),
                color=0x5865F2,
            )
        )
    return embeds[:10]


def result_embed(result: dict[str, list[dict]]) -> discord.Embed:
    success = result["success"]
    embed = discord.Embed(
        title="✅ 3회 경고 소프트밴 처리 결과",
        color=0x57F287 if not result["unban_failed"] else 0xED4245,
    )
    embed.description = (
        f"소프트밴 완료 **{len(success)}명** · "
        f"DM 실패 **{len(result['dm_failed'])}명** · "
        f"처리 제외 **{len(result['skipped'])}명** · "
        f"밴 실패 **{len(result['ban_failed'])}명** · "
        f"경고 초기화 실패 **{len(result['reset_failed'])}명**"
    )
    embed.add_field(
        name="재입장 가능",
        value=f"즉시 밴 해제 완료 {len(success)}명 · 성공 대상의 경고는 0회로 초기화됨",
        inline=False,
    )

    if result["dm_failed"]:
        names = ", ".join(item["target"].member.display_name for item in result["dm_failed"][:20])
        embed.add_field(name="📨 DM 발송 실패", value=names[:1024], inline=False)
    if result["skipped"]:
        lines = [
            f"{item['target'].member.display_name}: {item['error']}"
            for item in result["skipped"][:15]
        ]
        embed.add_field(name="⏭️ 처리 제외", value="\n".join(lines)[:1024], inline=False)
    if result["ban_failed"]:
        lines = [
            f"{item['target'].member.display_name}: {item['error']}"
            for item in result["ban_failed"][:10]
        ]
        embed.add_field(name="❌ 밴 실패", value="\n".join(lines)[:1024], inline=False)
    if result["reset_failed"]:
        lines = [
            f"{item['target'].member.display_name}: {item['error']}"
            for item in result["reset_failed"][:10]
        ]
        embed.add_field(
            name="⚠️ 경고 초기화 실패 · 수동 확인 필요",
            value="\n".join(lines)[:1024],
            inline=False,
        )
    if result["unban_failed"]:
        lines = [
            f"{item['target'].member.display_name} ({item['target'].member.id}): {item['error']}"
            for item in result["unban_failed"][:10]
        ]
        embed.add_field(
            name="🚨 즉시 밴 해제 실패 · 수동 해제 필요",
            value="\n".join(lines)[:1024],
            inline=False,
        )
    return embed


class SoftbanNoticeModal(discord.ui.Modal):
    def __init__(self, guild_id: int, current_message: str):
        super().__init__(title="3회 경고 DM 안내문 설정", timeout=300)
        self.guild_id = guild_id
        self.notice = discord.ui.TextInput(
            label="밴 처리 전에 보낼 DM 안내문",
            style=discord.TextStyle.paragraph,
            default=current_message[: store.MAX_DM_TEMPLATE_LENGTH],
            min_length=1,
            max_length=store.MAX_DM_TEMPLATE_LENGTH,
            required=True,
        )
        self.add_item(self.notice)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await asyncio.to_thread(store.set_dm_message, self.guild_id, str(self.notice.value))
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)
            return
        await interaction.response.send_message(
            "✅ 3회 경고 대상에게 소프트밴 전에 보낼 DM 안내문을 저장했습니다.\n"
            "사용 가능 변수: `{member}` · `{server}` · `{warnings}`",
            ephemeral=True,
        )


class SoftbanConfirmView(discord.ui.View):
    def __init__(self, cog: voice_audit.VoiceAuditCog):
        super().__init__(timeout=60)
        self.cog = cog
        self.running = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if voice_audit.authorized(interaction):
            return True
        await voice_audit.deny(interaction)
        return False

    @discord.ui.button(label="DM 발송 후 소프트밴 실행", emoji="🚪", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.running:
            await interaction.response.send_message("이미 처리 중입니다.", ephemeral=True)
            return

        guild_lock = _GUILD_SOFTBAN_LOCKS.setdefault(interaction.guild.id, asyncio.Lock())
        if guild_lock.locked():
            await interaction.response.send_message(
                "이 서버의 3회 경고 소프트밴이 이미 처리 중입니다.",
                ephemeral=True,
            )
            return

        self.running = True
        for child in self.children:
            child.disabled = True
        self.stop()
        processing = discord.Embed(
            title="⏳ 3회 경고 대상 처리 중",
            description="대상별로 DM을 먼저 시도한 뒤 밴하고 즉시 밴을 해제하고 있습니다.",
            color=0xFEE75C,
        )
        await interaction.response.edit_message(embed=processing, view=self)

        try:
            async with guild_lock:
                members = await self.cog.fetch_all_members(interaction.guild)
                targets = await asyncio.to_thread(
                    service.get_softban_targets,
                    interaction.guild,
                    members,
                )
                template = await asyncio.to_thread(store.get_dm_message, interaction.guild.id)
                result = await service.execute_softbans(interaction.guild, targets, template)
            await interaction.edit_original_response(embed=result_embed(result), view=None)
        except Exception as exc:
            logger.exception("3회 경고 소프트밴 처리 실패", exc_info=exc)
            error_embed = discord.Embed(
                title="❌ 3회 경고 소프트밴 처리 실패",
                description=f"오류: `{type(exc).__name__}`",
                color=0xED4245,
            )
            await interaction.edit_original_response(embed=error_embed, view=None)

    @discord.ui.button(label="취소", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            content="소프트밴 실행을 취소했습니다.",
            embed=None,
            view=None,
        )


class DisciplineVoiceAuditView(voice_audit_patch.EnhancedVoiceAuditView):
    @discord.ui.button(label="3회 경고 명단", emoji="🚪", style=discord.ButtonStyle.secondary, row=3)
    async def three_warning_list(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            members = await self.cog.fetch_all_members(interaction.guild)
            targets = await asyncio.to_thread(service.get_softban_targets, interaction.guild, members)
            template = await asyncio.to_thread(store.get_dm_message, interaction.guild.id)
            embeds = await asyncio.to_thread(target_embeds, interaction.guild, targets, template)
            await interaction.followup.send(
                embeds=embeds,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)

    @discord.ui.button(label="DM 안내문 설정", emoji="✉️", style=discord.ButtonStyle.primary, row=3)
    async def dm_notice(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            current = await asyncio.to_thread(store.get_dm_message, interaction.guild.id)
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)
            return
        await interaction.response.send_modal(SoftbanNoticeModal(interaction.guild.id, current))

    @discord.ui.button(label="3회 소프트밴", emoji="⚠️", style=discord.ButtonStyle.danger, row=3)
    async def softban(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            members = await self.cog.fetch_all_members(interaction.guild)
            targets = await asyncio.to_thread(service.get_softban_targets, interaction.guild, members)
            if not targets:
                await interaction.followup.send("현재 경고 3회 이상 대상이 없습니다.", ephemeral=True)
                return

            actionable = [
                target
                for target in targets
                if service.softban_block_reason(interaction.guild, target.member) is None
            ]
            if not actionable:
                await interaction.followup.send(
                    "3회 경고 대상은 있지만 서버 소유자·지정 관리자·역할 우선순위 문제로 "
                    "현재 처리 가능한 멤버가 없습니다.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(title="⚠️ 3회 경고 소프트밴 최종 확인", color=0xED4245)
            embed.description = (
                f"전체 대상 **{len(targets)}명**, 실제 처리 가능 **{len(actionable)}명**입니다.\n\n"
                "확인 버튼을 누르면 각 멤버에게 설정된 DM을 먼저 보낸 뒤 "
                "**밴 → 즉시 밴 해제**하여 새 초대 링크로 재입장할 수 있게 합니다.\n"
                "DM이 닫혀 있어 발송에 실패해도 소프트밴은 계속되며, "
                "성공한 대상의 경고는 0회로 초기화됩니다."
            )
            await interaction.followup.send(
                embed=embed,
                view=SoftbanConfirmView(self.cog),
                ephemeral=True,
            )
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)


_ORIGINAL_PANEL_EMBED = getattr(
    voice_audit.VoiceAuditCog,
    "_discipline_original_panel_embed",
    voice_audit.VoiceAuditCog.panel_embed,
)


def discipline_panel_embed(
    self: voice_audit.VoiceAuditCog,
    guild: discord.Guild,
    members: list[discord.Member],
    database_name: str,
) -> discord.Embed:
    embed = _ORIGINAL_PANEL_EMBED(self, guild, members, database_name)
    saved = voice_audit.load_activity(guild.id)
    target_count = sum(
        1
        for member in members
        if member.id in saved
        and int(saved[member.id]["warning_count"] or 0) >= service.WARNING_THRESHOLD
    )
    embed.add_field(name="3회 경고 소프트밴 대상", value=f"{target_count}명", inline=True)
    embed.add_field(name="퇴장 방식", value="DM 후 소프트밴 · 즉시 해제", inline=True)
    return embed


def install_patch() -> None:
    voice_audit.VoiceAuditCog._discipline_original_panel_embed = _ORIGINAL_PANEL_EMBED
    voice_audit.VoiceAuditCog.panel_embed = discipline_panel_embed
    voice_audit.VoiceAuditView = DisciplineVoiceAuditView
