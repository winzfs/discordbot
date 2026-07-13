"""Voice audit production patches: announcement channels and warning-cycle progress."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import time

import discord
import psycopg
from discord.ext import commands

from bot.cogs import voice_audit

logger = logging.getLogger(__name__)
WARNING_SECONDS = voice_audit.WARNING_DAYS * 86400


def next_weekly_report_at(current: dt.datetime | None = None) -> dt.datetime:
    """Return the next Wednesday 10:00 KST automatic warning run."""
    current = current or voice_audit.now()
    days_ahead = (2 - current.weekday()) % 7
    candidate = (current + dt.timedelta(days=days_ahead)).replace(
        hour=10,
        minute=0,
        second=0,
        microsecond=0,
    )
    if candidate <= current:
        candidate += dt.timedelta(days=7)
    return candidate


def format_kst(value: dt.datetime | None) -> str:
    if value is None:
        return "기록 없음"
    return value.astimezone(voice_audit.KST).strftime("%m/%d %H:%M")


def enhanced_check_warnings(
    self: voice_audit.VoiceAuditCog,
    guild: discord.Guild,
    members: list[discord.Member],
    max_per_member: int = 1,
) -> list[dict]:
    """Award warnings from the latest warning/voice timestamp, with deadlock retry.

    Rules:
    - A warning starts a fresh seven-day cycle at the actual award time.
    - Any voice entry/exit after that warning resets the cycle to last_voice_at.
    - At most max_per_member warnings are awarded in one check.
    """
    voice_audit.upsert_members(guild.id, members)
    member_map = {member.id: member for member in members}

    for attempt in range(3):
        current = voice_audit.now()
        awarded: list[dict] = []
        try:
            with voice_audit.db() as conn, conn.cursor() as cur:
                cur.execute("select pg_try_advisory_xact_lock(%s) as locked", (guild.id,))
                if not cur.fetchone()["locked"]:
                    return []

                cur.execute(
                    """
                    select *
                    from public.discordbot_member_activity
                    where guild_id=%s
                    order by user_id
                    for update
                    """,
                    (guild.id,),
                )
                for row in cur.fetchall():
                    user_id = int(row["user_id"])
                    member = member_map.get(user_id)
                    if member is None:
                        continue

                    joined_at = voice_audit.member_joined_at(member)
                    if (current - joined_at).total_seconds() < WARNING_SECONDS:
                        continue

                    baseline = voice_audit.parse_time(row["baseline_at"]) or voice_audit.tracking_baseline(member)
                    last_voice = voice_audit.parse_time(row["last_voice_at"])
                    last_warning = voice_audit.parse_time(row["last_warning_at"])
                    reference = max(value for value in (baseline, last_voice, last_warning) if value)
                    overdue_cycles = math.floor((current - reference).total_seconds() / WARNING_SECONDS)
                    count = min(overdue_cycles, max_per_member)
                    if count <= 0:
                        continue

                    new_total = int(row["warning_count"]) + count
                    # Store the actual time the warning was awarded. The next cycle starts here.
                    cur.execute(
                        """
                        update public.discordbot_member_activity
                        set warning_count=warning_count+%s,
                            last_warning_at=%s,
                            updated_at=%s
                        where guild_id=%s and user_id=%s
                        """,
                        (count, current, current, guild.id, user_id),
                    )
                    for _ in range(count):
                        cur.execute(
                            """
                            insert into public.discordbot_warning_history
                            (guild_id,user_id,display_name,awarded_at,inactivity_days,reason)
                            values(%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                guild.id,
                                user_id,
                                member.display_name,
                                current,
                                voice_audit.WARNING_DAYS,
                                f"음성채널 {voice_audit.WARNING_DAYS}일 미접속",
                            ),
                        )
                    awarded.append(
                        {
                            "member": member,
                            "count": count,
                            "total": new_total,
                            "reference": reference,
                            "awarded_at": current,
                        }
                    )
            return awarded
        except psycopg.errors.DeadlockDetected:
            if attempt >= 2:
                raise
            time.sleep(0.25 * (attempt + 1))

    return []


def warning_progress_embeds(
    self: voice_audit.VoiceAuditCog,
    guild: discord.Guild,
    members: list[discord.Member],
) -> list[discord.Embed]:
    """Build administrator-only pages showing the next warning cycle."""
    voice_audit.upsert_members(guild.id, members)
    saved = voice_audit.load_activity(guild.id)
    current = voice_audit.now()
    report_at = next_weekly_report_at(current)

    rows: list[dict] = []
    for member in members:
        if member.bot:
            continue
        row = saved.get(member.id)
        if row is None:
            continue

        joined_at = voice_audit.member_joined_at(member)
        baseline = voice_audit.parse_time(row["baseline_at"]) or voice_audit.tracking_baseline(member)
        last_voice = voice_audit.parse_time(row["last_voice_at"])
        last_warning = voice_audit.parse_time(row["last_warning_at"])
        reference = max(value for value in (baseline, last_voice, last_warning) if value)
        due_at = reference + dt.timedelta(days=voice_audit.WARNING_DAYS)
        warnings = int(row["warning_count"])
        reconnected = bool(last_warning and last_voice and last_voice > last_warning)
        joined_eligible = (report_at - joined_at).total_seconds() >= WARNING_SECONDS
        due_next_report = joined_eligible and due_at <= report_at

        if warnings <= 0 and not due_next_report:
            continue

        if reconnected and not due_next_report:
            status = "excluded"
        elif due_next_report:
            status = "due"
        else:
            status = "counting"

        rows.append(
            {
                "member": member,
                "warnings": warnings,
                "last_warning": last_warning,
                "last_voice": last_voice,
                "reference": reference,
                "due_at": due_at,
                "status": status,
                "due_next_report": due_next_report,
                "reconnected": reconnected,
            }
        )

    priority = {"due": 0, "excluded": 1, "counting": 2}
    rows.sort(key=lambda item: (priority[item["status"]], item["due_at"], item["member"].id))

    warning_holders = [item for item in rows if item["warnings"] > 0]
    due_repeat = [item for item in warning_holders if item["due_next_report"]]
    reconnected_excluded = [
        item for item in warning_holders
        if item["reconnected"] and not item["due_next_report"]
    ]
    due_first = [item for item in rows if item["warnings"] == 0 and item["due_next_report"]]

    header = discord.Embed(title="⏳ 다음 경고 진행상황", color=0xFEE75C)
    header.description = (
        f"다음 자동 점검: **{report_at.strftime('%Y-%m-%d %H:%M')} KST**\n"
        "계산 기준은 `마지막 경고`, `최근 음성 접속`, `최초 기준일` 중 가장 최근 시각입니다.\n"
        "경고 뒤 음성채널에 접속하면 해당 접속 시각부터 7일을 다시 계산합니다."
    )
    header.add_field(name="현재 경고 보유", value=f"{len(warning_holders)}명", inline=True)
    header.add_field(name="다음 회차 추가 경고 예상", value=f"{len(due_repeat)}명", inline=True)
    header.add_field(name="접속으로 이번 회차 제외", value=f"{len(reconnected_excluded)}명", inline=True)
    header.add_field(name="신규 1차 경고 예상", value=f"{len(due_first)}명", inline=True)
    header.add_field(
        name="총 경고 예상",
        value=f"{len(due_repeat) + len(due_first)}명",
        inline=True,
    )
    header.set_footer(text=f"조회 {current.strftime('%Y-%m-%d %H:%M:%S')} KST")

    lines: list[str] = []
    for item in rows:
        member = item["member"]
        if item["status"] == "due":
            icon = "🔴"
            state = f"다음 점검 시 **{item['warnings'] + 1}차 경고 예정**"
        elif item["status"] == "excluded":
            icon = "🟢"
            state = "중간 접속 · **이번 회차 제외**"
        else:
            icon = "🟡"
            remaining = max(0, int((item["due_at"] - current).total_seconds()))
            state = f"재카운트 중 · {voice_audit.duration_text(remaining)} 남음"

        warning_text = f"현재 {item['warnings']}회" if item["warnings"] else "경고 없음"
        detail = (
            f"{icon} {member.mention} · {warning_text} · {state}\n"
            f"　기준 {format_kst(item['reference'])} → 7일 도달 {format_kst(item['due_at'])}"
        )
        if item["reconnected"]:
            detail += f" · 최근 접속 {format_kst(item['last_voice'])}"
        lines.append(detail)

    pages: list[discord.Embed] = [header]
    chunk: list[str] = []
    length = 0
    for line in lines:
        if chunk and length + len(line) + 1 > 3700:
            page = discord.Embed(
                title=f"📋 멤버별 경고 진행상황 {len(pages)}",
                description="\n".join(chunk),
                color=0x5865F2,
            )
            pages.append(page)
            chunk = []
            length = 0
        chunk.append(line)
        length += len(line) + 1
    if chunk:
        page = discord.Embed(
            title=f"📋 멤버별 경고 진행상황 {len(pages)}",
            description="\n".join(chunk),
            color=0x5865F2,
        )
        pages.append(page)

    total_pages = max(1, len(pages) - 1)
    for index, page in enumerate(pages[1:], start=1):
        page.set_footer(text=f"상세 {index}/{total_pages} · 최대 10개 임베드")
    return pages[:10]


class AnnouncementReportChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: voice_audit.VoiceAuditCog):
        super().__init__(
            placeholder="주간 경고자 명단을 보낼 공지 채널 선택",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=1,
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0]
        if not hasattr(channel, "id") or not hasattr(channel, "mention"):
            await interaction.response.send_message(
                "텍스트/공지사항 채널만 설정할 수 있습니다.",
                ephemeral=True,
            )
            return
        await asyncio.to_thread(
            self.cog.set_report_channel_id,
            interaction.guild.id,
            channel.id,
        )
        await interaction.response.send_message(
            f"✅ 경고자 명단 공지 채널을 {channel.mention}(으)로 설정했습니다.",
            ephemeral=True,
        )


class EnhancedVoiceAuditView(discord.ui.View):
    def __init__(self, cog: voice_audit.VoiceAuditCog):
        super().__init__(timeout=600)
        self.cog = cog
        self.add_item(AnnouncementReportChannelSelect(cog))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if voice_audit.authorized(interaction):
            return True
        await voice_audit.deny(interaction)
        return False

    @discord.ui.button(label="전체 멤버 현황", emoji="👥", style=discord.ButtonStyle.primary, row=0)
    async def members(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            members = await self.cog.fetch_all_members(interaction.guild)
            embed = await asyncio.to_thread(self.cog.member_embed, interaction.guild, members)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)

    @discord.ui.button(label="경고 현황", emoji="⚠️", style=discord.ButtonStyle.danger, row=0)
    async def warning_status(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            members = await self.cog.fetch_all_members(interaction.guild)
            embed = await asyncio.to_thread(self.cog.warning_embed, interaction.guild, members)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)

    @discord.ui.button(label="최근 입퇴장", emoji="🎙️", style=discord.ButtonStyle.secondary, row=0)
    async def recent(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            embed = await asyncio.to_thread(self.cog.recent_embed, interaction.guild)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)

    @discord.ui.button(label="즉시 경고 점검", emoji="🔍", style=discord.ButtonStyle.success, row=0)
    async def warnings(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            members = await self.cog.fetch_all_members(interaction.guild)
            awarded = await asyncio.to_thread(self.cog.check_warnings, interaction.guild, members, 1)
            await interaction.followup.send(
                f"새 경고 **{len(awarded)}명 / {sum(item['count'] for item in awarded)}회**를 부여했습니다.",
                ephemeral=True,
            )
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)

    @discord.ui.button(label="Excel 출력", emoji="📊", style=discord.ButtonStyle.success, row=0)
    async def excel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            members = await self.cog.fetch_all_members(interaction.guild)
            file = await asyncio.to_thread(self.cog.make_excel, interaction.guild, members)
            await interaction.followup.send(file=file, ephemeral=True)
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)

    @discord.ui.button(label="다음 경고 진행상황", emoji="⏳", style=discord.ButtonStyle.primary, row=2)
    async def warning_progress(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            members = await self.cog.fetch_all_members(interaction.guild)
            embeds = await asyncio.to_thread(
                self.cog.warning_progress_embeds,
                interaction.guild,
                members,
            )
            await interaction.followup.send(
                embeds=embeds,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as exc:
            await voice_audit.db_error(interaction, exc)


class VoiceAuditPatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        voice_audit.ReportChannelSelect = AnnouncementReportChannelSelect
        voice_audit.VoiceAuditView = EnhancedVoiceAuditView
        voice_audit.VoiceAuditCog.check_warnings = enhanced_check_warnings
        voice_audit.VoiceAuditCog.warning_progress_embeds = warning_progress_embeds
        logger.info(
            "음성 관리 패치 적용 완료: 공지 채널 + 실제 경고 시각 7일 주기 + 진행상황 버튼"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceAuditPatchCog(bot))
