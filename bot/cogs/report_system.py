"""Member reports delivered to one configured staff channel."""
from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs import voice_audit

logger = logging.getLogger(__name__)
REPORT_PANEL_CUSTOM_ID = "report:create:v2"
REPORT_CLAIM_CUSTOM_ID = "report:claim:v2"
REPORT_RESOLVE_CUSTOM_ID = "report:resolve:v2"
REPORT_REJECT_CUSTOM_ID = "report:reject:v2"


def ensure_schema() -> None:
    """Create or migrate report tables without requiring a category or role."""
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists public.discordbot_report_config (
                guild_id bigint primary key,
                report_channel_id bigint,
                updated_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            "alter table public.discordbot_report_config add column if not exists report_channel_id bigint"
        )
        cur.execute(
            "alter table public.discordbot_report_config alter column category_id drop not null"
        )
        cur.execute(
            "alter table public.discordbot_report_config alter column staff_role_id drop not null"
        )
        cur.execute(
            """
            create table if not exists public.discordbot_reports (
                id bigserial primary key,
                guild_id bigint not null,
                channel_id bigint,
                message_id bigint unique,
                reporter_id bigint not null,
                target_id bigint,
                target_text text not null,
                reason text not null,
                details text,
                status text not null default 'open',
                claimed_by bigint,
                resolved_by bigint,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            "alter table public.discordbot_reports add column if not exists message_id bigint"
        )
        cur.execute(
            "create unique index if not exists discordbot_reports_message_id_uq on public.discordbot_reports(message_id) where message_id is not null"
        )


def set_report_channel(guild_id: int, channel_id: int) -> None:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into public.discordbot_report_config(guild_id,report_channel_id,updated_at)
            values(%s,%s,%s)
            on conflict(guild_id)
            do update set report_channel_id=excluded.report_channel_id,
                          updated_at=excluded.updated_at
            """,
            (guild_id, channel_id, voice_audit.now()),
        )


def get_report_channel_id(guild_id: int) -> int | None:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            "select report_channel_id from public.discordbot_report_config where guild_id=%s",
            (guild_id,),
        )
        row = cur.fetchone()
    return int(row["report_channel_id"]) if row and row["report_channel_id"] else None


def create_report_record(
    guild_id: int,
    channel_id: int,
    reporter_id: int,
    target_id: int | None,
    target_text: str,
    reason: str,
    details: str,
) -> int:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into public.discordbot_reports
            (guild_id,channel_id,reporter_id,target_id,target_text,reason,details,status,created_at,updated_at)
            values(%s,%s,%s,%s,%s,%s,%s,'open',%s,%s)
            returning id
            """,
            (
                guild_id,
                channel_id,
                reporter_id,
                target_id,
                target_text,
                reason,
                details,
                voice_audit.now(),
                voice_audit.now(),
            ),
        )
        return int(cur.fetchone()["id"])


def attach_report_message(report_id: int, message_id: int) -> None:
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            "update public.discordbot_reports set message_id=%s,updated_at=%s where id=%s",
            (message_id, voice_audit.now(), report_id),
        )


def get_report_by_message(message_id: int) -> dict | None:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute("select * from public.discordbot_reports where message_id=%s", (message_id,))
        return cur.fetchone()


def update_report_status(
    message_id: int,
    status: str,
    *,
    claimed_by: int | None = None,
    resolved_by: int | None = None,
) -> None:
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update public.discordbot_reports
            set status=%s,
                claimed_by=coalesce(%s,claimed_by),
                resolved_by=coalesce(%s,resolved_by),
                updated_at=%s
            where message_id=%s
            """,
            (status, claimed_by, resolved_by, voice_audit.now(), message_id),
        )


def parse_user_id(value: str) -> int | None:
    match = re.search(r"(\d{15,22})", value)
    return int(match.group(1)) if match else None


def is_staff(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return isinstance(member, discord.Member) and (
        member.id == voice_audit.ADMIN_USER_ID
        or member.guild_permissions.manage_guild
        or member.guild_permissions.moderate_members
    )


def status_text(status: str, actor_id: int | None = None) -> str:
    mapping = {
        "open": "🟡 접수됨 · 담당자 대기",
        "claimed": "🔵 처리 중",
        "resolved": "🟢 처리 완료",
        "rejected": "⚫ 신고 기각",
    }
    text = mapping.get(status, status)
    return f"{text}\n담당 운영진: <@{actor_id}>" if actor_id else text


class ReportModal(discord.ui.Modal):
    def __init__(self) -> None:
        super().__init__(title="멤버 신고 접수", timeout=300)
        self.target = discord.ui.TextInput(
            label="신고 대상",
            placeholder="닉네임, 멘션 또는 사용자 ID",
            min_length=1,
            max_length=100,
        )
        self.reason = discord.ui.TextInput(
            label="신고 사유",
            placeholder="욕설, 분쟁 유도, 괴롭힘 등 핵심 사유",
            min_length=2,
            max_length=300,
        )
        self.details = discord.ui.TextInput(
            label="상세 내용 및 증거",
            placeholder="발생 시각, 채널, 상황, 메시지 링크 등을 적어 주세요.",
            style=discord.TextStyle.paragraph,
            min_length=5,
            max_length=1800,
        )
        self.add_item(self.target)
        self.add_item(self.reason)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if interaction.guild is None:
            await interaction.followup.send("서버 안에서만 신고할 수 있습니다.", ephemeral=True)
            return

        try:
            channel_id = await asyncio.to_thread(get_report_channel_id, interaction.guild.id)
            if channel_id is None:
                await interaction.followup.send(
                    "신고 채널이 아직 설정되지 않았습니다. 관리자에게 알려 주세요.",
                    ephemeral=True,
                )
                return

            channel = interaction.guild.get_channel(channel_id) or await interaction.client.fetch_channel(channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                await interaction.followup.send(
                    "설정된 신고 채널을 사용할 수 없습니다. 관리자에게 알려 주세요.",
                    ephemeral=True,
                )
                return

            target_text = str(self.target.value).strip()
            target_id = parse_user_id(target_text)
            report_id = await asyncio.to_thread(
                create_report_record,
                interaction.guild.id,
                channel.id,
                interaction.user.id,
                target_id,
                target_text,
                str(self.reason.value).strip(),
                str(self.details.value).strip(),
            )

            target_display = (
                f"<@{target_id}> (`{target_id}`)"
                if target_id
                else discord.utils.escape_markdown(target_text)
            )
            embed = discord.Embed(title=f"🚨 멤버 신고 #{report_id}", color=0xED4245)
            embed.description = "신고 패널을 통해 접수된 관리자 확인용 신고입니다."
            embed.add_field(
                name="신고자",
                value=f"{interaction.user.mention} (`{interaction.user.id}`)",
                inline=False,
            )
            embed.add_field(name="신고 대상", value=target_display, inline=False)
            embed.add_field(name="신고 사유", value=str(self.reason.value)[:1024], inline=False)
            embed.add_field(name="상세 내용 및 증거", value=str(self.details.value)[:1024], inline=False)
            embed.add_field(name="처리 상태", value=status_text("open"), inline=False)
            embed.set_footer(text="허위 신고는 제재될 수 있습니다.")

            message = await channel.send(
                embed=embed,
                view=ReportManageView(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await asyncio.to_thread(attach_report_message, report_id, message.id)
            await interaction.followup.send(
                f"✅ 신고가 접수되었습니다. 신고 번호는 **#{report_id}**입니다.",
                ephemeral=True,
            )
        except discord.Forbidden:
            logger.exception("신고 채널 전송 권한 부족")
            await interaction.followup.send(
                "봇이 신고 채널을 보거나 메시지를 보낼 권한이 없습니다.",
                ephemeral=True,
            )
        except Exception as exc:
            logger.exception("신고 접수 실패", exc_info=exc)
            await interaction.followup.send(
                f"❌ 신고 접수 중 오류가 발생했습니다: `{type(exc).__name__}`",
                ephemeral=True,
            )


class ReportPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="멤버 신고하기",
        emoji="🚨",
        style=discord.ButtonStyle.danger,
        custom_id=REPORT_PANEL_CUSTOM_ID,
    )
    async def create_report(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ReportModal())


class ReportManageView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_staff(interaction):
            return True
        await interaction.response.send_message("운영진만 처리할 수 있습니다.", ephemeral=True)
        return False

    async def _change_status(
        self,
        interaction: discord.Interaction,
        *,
        status: str,
        color: int,
    ) -> None:
        if interaction.message is None:
            await interaction.response.send_message("신고 메시지를 찾을 수 없습니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        report = await asyncio.to_thread(get_report_by_message, interaction.message.id)
        if report is None:
            await interaction.followup.send("신고 DB 기록을 찾을 수 없습니다.", ephemeral=True)
            return

        claimed_by = interaction.user.id if status == "claimed" else None
        resolved_by = interaction.user.id if status in {"resolved", "rejected"} else None
        await asyncio.to_thread(
            update_report_status,
            interaction.message.id,
            status,
            claimed_by=claimed_by,
            resolved_by=resolved_by,
        )

        embed = interaction.message.embeds[0].copy() if interaction.message.embeds else discord.Embed()
        field_index = next(
            (index for index, field in enumerate(embed.fields) if field.name == "처리 상태"),
            None,
        )
        value = status_text(status, interaction.user.id)
        if field_index is None:
            embed.add_field(name="처리 상태", value=value, inline=False)
        else:
            embed.set_field_at(field_index, name="처리 상태", value=value, inline=False)
        embed.color = color

        for child in self.children:
            child.disabled = status in {"resolved", "rejected"}
        await interaction.message.edit(embed=embed, view=self)
        await interaction.followup.send("신고 처리 상태를 변경했습니다.", ephemeral=True)

    @discord.ui.button(
        label="담당하기",
        emoji="🙋",
        style=discord.ButtonStyle.primary,
        custom_id=REPORT_CLAIM_CUSTOM_ID,
    )
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._change_status(interaction, status="claimed", color=0x5865F2)

    @discord.ui.button(
        label="처리 완료",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id=REPORT_RESOLVE_CUSTOM_ID,
    )
    async def resolve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._change_status(interaction, status="resolved", color=0x57F287)

    @discord.ui.button(
        label="신고 기각",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        custom_id=REPORT_REJECT_CUSTOM_ID,
    )
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._change_status(interaction, status="rejected", color=0x747F8D)


class ReportSystemCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(ReportPanelView())
        bot.add_view(ReportManageView())

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        try:
            await asyncio.to_thread(ensure_schema)
        except Exception:
            logger.exception("신고 기능 DB 초기화 실패")

    @app_commands.command(name="신고설정", description="[관리자] 신고 내용이 전송될 채널을 설정합니다.")
    @app_commands.describe(channel="신고 내용이 전송될 관리자 채널")
    async def report_settings(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if not is_staff(interaction):
            await interaction.response.send_message("운영진만 설정할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await asyncio.to_thread(set_report_channel, interaction.guild.id, channel.id)
            await interaction.followup.send(
                f"✅ 신고 채널을 {channel.mention}(으)로 설정했습니다.",
                ephemeral=True,
            )
        except Exception as exc:
            logger.exception("신고 채널 설정 실패", exc_info=exc)
            await interaction.followup.send(
                f"❌ 신고 채널 설정 실패: `{type(exc).__name__}`",
                ephemeral=True,
            )

    @app_commands.command(name="신고패널", description="[관리자] 현재 채널에 신고 패널을 설치합니다.")
    async def report_panel(self, interaction: discord.Interaction) -> None:
        if not is_staff(interaction):
            await interaction.response.send_message("운영진만 설치할 수 있습니다.", ephemeral=True)
            return
        embed = discord.Embed(title="🚨 멤버 신고", color=0xED4245)
        embed.description = (
            "아래 버튼을 눌러 운영진에게 멤버를 신고할 수 있습니다.\n"
            "신고 내용은 설정된 관리자 채널로만 전송됩니다.\n\n"
            "신고 대상, 사유, 발생 상황과 증거를 가능한 자세히 적어 주세요."
        )
        embed.set_footer(text="허위 신고 또는 악의적인 반복 신고는 제재될 수 있습니다.")
        await interaction.response.send_message(embed=embed, view=ReportPanelView())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReportSystemCog(bot))
