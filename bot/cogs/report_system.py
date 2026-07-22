"""Private member report tickets with persistent Discord UI."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs import voice_audit

logger = logging.getLogger(__name__)
REPORT_PANEL_CUSTOM_ID = "report:create"
REPORT_CLAIM_CUSTOM_ID = "report:claim"
REPORT_RESOLVE_CUSTOM_ID = "report:resolve"
REPORT_REJECT_CUSTOM_ID = "report:reject"
REPORT_CLOSE_CUSTOM_ID = "report:close"


@dataclass(slots=True)
class ReportConfig:
    category_id: int
    staff_role_id: int


def ensure_schema() -> None:
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists public.discordbot_report_config (
                guild_id bigint primary key,
                category_id bigint not null,
                staff_role_id bigint not null,
                updated_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            """
            create table if not exists public.discordbot_reports (
                id bigserial primary key,
                guild_id bigint not null,
                channel_id bigint unique,
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


def set_config(guild_id: int, category_id: int, staff_role_id: int) -> None:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into public.discordbot_report_config(guild_id,category_id,staff_role_id,updated_at)
            values(%s,%s,%s,%s)
            on conflict(guild_id)
            do update set category_id=excluded.category_id,
                          staff_role_id=excluded.staff_role_id,
                          updated_at=excluded.updated_at
            """,
            (guild_id, category_id, staff_role_id, voice_audit.now()),
        )


def get_config(guild_id: int) -> ReportConfig | None:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            "select category_id,staff_role_id from public.discordbot_report_config where guild_id=%s",
            (guild_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return ReportConfig(category_id=int(row["category_id"]), staff_role_id=int(row["staff_role_id"]))


def create_report_record(
    guild_id: int,
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
            (guild_id,reporter_id,target_id,target_text,reason,details,status,created_at,updated_at)
            values(%s,%s,%s,%s,%s,%s,'open',%s,%s)
            returning id
            """,
            (
                guild_id,
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


def attach_report_channel(report_id: int, channel_id: int) -> None:
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            "update public.discordbot_reports set channel_id=%s,updated_at=%s where id=%s",
            (channel_id, voice_audit.now(), report_id),
        )


def get_report_by_channel(channel_id: int) -> dict | None:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute("select * from public.discordbot_reports where channel_id=%s", (channel_id,))
        return cur.fetchone()


def update_report_status(
    channel_id: int,
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
            where channel_id=%s
            """,
            (status, claimed_by, resolved_by, voice_audit.now(), channel_id),
        )


def parse_user_id(value: str) -> int | None:
    match = re.search(r"(\d{15,22})", value)
    return int(match.group(1)) if match else None


def safe_channel_name(report_id: int, reporter: discord.Member | discord.User) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9가-힣-]", "-", reporter.display_name).strip("-")
    cleaned = re.sub(r"-+", "-", cleaned)[:30] or str(reporter.id)
    return f"신고-{report_id}-{cleaned}"[:95]


def is_staff(interaction: discord.Interaction, staff_role_id: int | None = None) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_guild or member.guild_permissions.moderate_members:
        return True
    return bool(staff_role_id and any(role.id == staff_role_id for role in member.roles))


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
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("서버 안에서만 신고할 수 있습니다.", ephemeral=True)
            return

        try:
            config = await asyncio.to_thread(get_config, interaction.guild.id)
            if config is None:
                await interaction.followup.send("신고 기능 설정이 아직 완료되지 않았습니다.", ephemeral=True)
                return

            category = interaction.guild.get_channel(config.category_id)
            staff_role = interaction.guild.get_role(config.staff_role_id)
            if not isinstance(category, discord.CategoryChannel) or staff_role is None:
                await interaction.followup.send(
                    "설정된 신고 카테고리 또는 관리자 역할을 찾을 수 없습니다. 관리자에게 알려 주세요.",
                    ephemeral=True,
                )
                return

            target_text = str(self.target.value).strip()
            target_id = parse_user_id(target_text)
            report_id = await asyncio.to_thread(
                create_report_record,
                interaction.guild.id,
                interaction.user.id,
                target_id,
                target_text,
                str(self.reason.value).strip(),
                str(self.details.value).strip(),
            )

            bot_member = interaction.guild.me
            overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                ),
                staff_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True,
                ),
            }
            if bot_member is not None:
                overwrites[bot_member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True,
                    manage_messages=True,
                )

            channel = await interaction.guild.create_text_channel(
                safe_channel_name(report_id, interaction.user),
                category=category,
                topic=f"report_id={report_id}; reporter_id={interaction.user.id}; target_id={target_id or 0}",
                overwrites=overwrites,
                reason=f"멤버 신고 #{report_id} 접수",
            )
            await asyncio.to_thread(attach_report_channel, report_id, channel.id)

            target_display = f"<@{target_id}> (`{target_id}`)" if target_id else discord.utils.escape_markdown(target_text)
            embed = discord.Embed(title=f"🚨 멤버 신고 #{report_id}", color=0xED4245)
            embed.description = "신고 내용은 신고자와 운영진만 확인할 수 있습니다."
            embed.add_field(name="신고자", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
            embed.add_field(name="신고 대상", value=target_display, inline=False)
            embed.add_field(name="신고 사유", value=str(self.reason.value)[:1024], inline=False)
            embed.add_field(name="상세 내용 및 증거", value=str(self.details.value)[:1024], inline=False)
            embed.add_field(name="처리 상태", value="🟡 접수됨 · 담당자 대기", inline=False)
            embed.set_footer(text="허위 신고 또는 신고 내용의 외부 공유는 제재될 수 있습니다.")

            await channel.send(
                content=f"{interaction.user.mention} {staff_role.mention}",
                embed=embed,
                view=ReportManageView(),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
            await interaction.followup.send(
                f"✅ 신고가 접수되었습니다. 운영진과 대화할 수 있는 채널: {channel.mention}",
                ephemeral=True,
            )
        except discord.Forbidden:
            logger.exception("신고 채널 생성 권한 부족")
            await interaction.followup.send("신고 채널을 만들 권한이 봇에 없습니다.", ephemeral=True)
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
        if interaction.guild is None:
            return False
        try:
            config = await asyncio.to_thread(get_config, interaction.guild.id)
        except Exception:
            config = None
        if is_staff(interaction, config.staff_role_id if config else None):
            return True
        await interaction.response.send_message("운영진만 처리할 수 있습니다.", ephemeral=True)
        return False

    async def _update(
        self,
        interaction: discord.Interaction,
        *,
        status: str,
        label: str,
        color: int,
        close_after: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        report = await asyncio.to_thread(get_report_by_channel, interaction.channel_id)
        if report is None:
            await interaction.followup.send("이 채널의 신고 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        claimed_by = interaction.user.id if status == "claimed" else None
        resolved_by = interaction.user.id if status in {"resolved", "rejected"} else None
        await asyncio.to_thread(
            update_report_status,
            interaction.channel_id,
            status,
            claimed_by=claimed_by,
            resolved_by=resolved_by,
        )

        embed = discord.Embed(title=f"{label} 신고 처리 상태 변경", color=color)
        embed.description = f"담당 운영진: {interaction.user.mention}\n상태: **{status}**"
        await interaction.channel.send(embed=embed)

        if isinstance(interaction.channel, discord.TextChannel):
            prefix = {"claimed": "처리중", "resolved": "완료", "rejected": "기각"}.get(status)
            if prefix:
                base = re.sub(r"^(처리중|완료|기각)-", "", interaction.channel.name)
                try:
                    await interaction.channel.edit(name=f"{prefix}-{base}"[:95])
                except discord.HTTPException:
                    pass
            if close_after:
                reporter = interaction.guild.get_member(int(report["reporter_id"]))
                if reporter is not None:
                    try:
                        await interaction.channel.set_permissions(reporter, send_messages=False)
                    except discord.HTTPException:
                        pass

        await interaction.followup.send(f"✅ 신고 상태를 `{status}`(으)로 변경했습니다.", ephemeral=True)

    @discord.ui.button(
        label="담당하기",
        emoji="🙋",
        style=discord.ButtonStyle.primary,
        custom_id=REPORT_CLAIM_CUSTOM_ID,
    )
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._update(interaction, status="claimed", label="🙋", color=0x5865F2)

    @discord.ui.button(
        label="처리 완료",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id=REPORT_RESOLVE_CUSTOM_ID,
    )
    async def resolve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._update(interaction, status="resolved", label="✅", color=0x57F287, close_after=True)

    @discord.ui.button(
        label="신고 기각",
        emoji="⛔",
        style=discord.ButtonStyle.secondary,
        custom_id=REPORT_REJECT_CUSTOM_ID,
    )
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._update(interaction, status="rejected", label="⛔", color=0x747F8D, close_after=True)

    @discord.ui.button(
        label="채널 삭제",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id=REPORT_CLOSE_CUSTOM_ID,
    )
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message("5초 후 신고 채널을 삭제합니다.", ephemeral=True)
        await asyncio.sleep(5)
        if interaction.channel is not None:
            await interaction.channel.delete(reason=f"신고 채널 삭제: {interaction.user}")


class ReportSystemCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await asyncio.to_thread(ensure_schema)
        self.bot.add_view(ReportPanelView())
        self.bot.add_view(ReportManageView())

    @app_commands.command(name="신고설정", description="[관리자] 신고 티켓 카테고리와 운영진 역할을 설정합니다.")
    @app_commands.describe(category="신고 채널이 생성될 카테고리", staff_role="신고를 확인할 운영진 역할")
    @app_commands.default_permissions(manage_guild=True)
    async def report_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        staff_role: discord.Role,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("서버 관리 권한이 필요합니다.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await asyncio.to_thread(set_config, interaction.guild.id, category.id, staff_role.id)
            await interaction.followup.send(
                f"✅ 신고 기능 설정 완료\n카테고리: **{category.name}**\n운영진 역할: {staff_role.mention}",
                ephemeral=True,
            )
        except Exception as exc:
            logger.exception("신고 설정 저장 실패", exc_info=exc)
            await interaction.followup.send(f"설정 저장 실패: `{type(exc).__name__}`", ephemeral=True)

    @app_commands.command(name="신고패널", description="[관리자] 멤버 신고 접수 패널을 현재 채널에 설치합니다.")
    @app_commands.default_permissions(manage_guild=True)
    async def report_panel(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("서버 관리 권한이 필요합니다.", ephemeral=True)
            return
        config = await asyncio.to_thread(get_config, interaction.guild.id)
        if config is None:
            await interaction.response.send_message("먼저 `/신고설정`을 실행해 주세요.", ephemeral=True)
            return

        embed = discord.Embed(title="🚨 멤버 신고 접수", color=0xED4245)
        embed.description = (
            "서버 규칙 위반, 욕설, 괴롭힘, 분쟁 유도 등을 운영진에게 비공개로 신고할 수 있습니다.\n\n"
            "아래 버튼을 누른 뒤 신고 대상과 구체적인 상황을 작성해 주세요. "
            "신고가 접수되면 신고자와 운영진만 볼 수 있는 전용 채널이 생성됩니다."
        )
        embed.add_field(
            name="신고 전에 확인해 주세요",
            value="• 가능한 한 메시지 링크와 발생 시각을 포함해 주세요.\n• 허위·보복성 신고는 제재될 수 있습니다.\n• 신고 내용은 외부에 공유하지 마세요.",
            inline=False,
        )
        await interaction.channel.send(embed=embed, view=ReportPanelView())
        await interaction.response.send_message("✅ 신고 패널을 설치했습니다.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReportSystemCog(bot))
