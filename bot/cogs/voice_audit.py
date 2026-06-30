"""Supabase PostgreSQL 기반 음성채널 기록 및 관리자 패널."""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import math
import os
from zoneinfo import ZoneInfo

import discord
import psycopg
from discord import app_commands
from discord.ext import commands, tasks
from openpyxl import Workbook
from psycopg.rows import dict_row

ADMIN_USER_ID = 324558739921305602
WARNING_DAYS = 7
KST = ZoneInfo("Asia/Seoul")
DATABASE_URL = os.getenv("SUPABASE_DB_URL")


def now() -> dt.datetime:
    return dt.datetime.now(KST)


def db() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("SUPABASE_DB_URL 환경변수가 없습니다")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)


def parse_time(value):
    if value is None:
        return None
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def duration_text(seconds: int) -> str:
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}일")
    if hours:
        parts.append(f"{hours}시간")
    parts.append(f"{minutes}분")
    return " ".join(parts)


def verify_database() -> str:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("select current_database() as name, now() as checked_at")
            row = cur.fetchone()
            return str(row["name"])


def ensure_members(guild: discord.Guild) -> None:
    current = now()
    rows = [(guild.id, m.id, m.display_name, current, current) for m in guild.members if not m.bot]
    if not rows:
        return
    with db() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.discordbot_member_activity
                (guild_id,user_id,display_name,baseline_at,updated_at)
                values(%s,%s,%s,%s,%s)
                on conflict(guild_id,user_id)
                do update set display_name=excluded.display_name,updated_at=excluded.updated_at
                """,
                rows,
            )


def activity_rows(guild: discord.Guild) -> list[dict]:
    ensure_members(guild)
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from public.discordbot_member_activity where guild_id=%s", (guild.id,))
            saved = {int(r["user_id"]): r for r in cur.fetchall()}
    current = now()
    result = []
    for member in guild.members:
        if member.bot:
            continue
        row = saved.get(member.id)
        baseline = parse_time(row["baseline_at"]) if row else current
        last_voice = parse_time(row["last_voice_at"]) if row else None
        reference = last_voice or baseline or current
        result.append({
            "member": member,
            "last_voice": last_voice,
            "inactive_seconds": max(0, int((current - reference).total_seconds())),
            "warnings": int(row["warning_count"]) if row else 0,
        })
    return sorted(result, key=lambda r: r["inactive_seconds"], reverse=True)


def authorized(interaction: discord.Interaction) -> bool:
    return interaction.user.id == ADMIN_USER_ID


async def deny(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("이 기능은 지정된 관리자만 사용할 수 있습니다.", ephemeral=True)


async def db_error(interaction: discord.Interaction, exc: Exception) -> None:
    await interaction.followup.send(
        f"❌ Supabase DB 연결 실패\n오류: `{type(exc).__name__}`\nRailway의 `SUPABASE_DB_URL` 값을 확인해주세요.",
        ephemeral=True,
    )


class VoiceAuditView(discord.ui.View):
    def __init__(self, cog: "VoiceAuditCog"):
        super().__init__(timeout=600)
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if authorized(interaction):
            return True
        await deny(interaction)
        return False

    @discord.ui.button(label="전체 멤버 현황", emoji="👥", style=discord.ButtonStyle.primary)
    async def members(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            embed = await asyncio.to_thread(self.cog.member_embed, interaction.guild)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await db_error(interaction, exc)

    @discord.ui.button(label="최근 입퇴장", emoji="🎙️", style=discord.ButtonStyle.secondary)
    async def recent(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            embed = await asyncio.to_thread(self.cog.recent_embed, interaction.guild)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await db_error(interaction, exc)

    @discord.ui.button(label="즉시 경고 점검", emoji="🔍", style=discord.ButtonStyle.success)
    async def warnings(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            count = await asyncio.to_thread(self.cog.check_warnings, interaction.guild)
            await interaction.followup.send(f"새 경고 **{count}회**를 부여했습니다.", ephemeral=True)
        except Exception as exc:
            await db_error(interaction, exc)

    @discord.ui.button(label="Excel 출력", emoji="📊", style=discord.ButtonStyle.success)
    async def excel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            file = await asyncio.to_thread(self.cog.make_excel, interaction.guild)
            await interaction.followup.send(file=file, ephemeral=True)
        except Exception as exc:
            await db_error(interaction, exc)


class VoiceAuditCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[tuple[int, int], tuple[dt.datetime, int, str]] = {}
        self.warning_loop.start()

    def cog_unload(self):
        self.warning_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        current = now()
        for guild in self.bot.guilds:
            try:
                await asyncio.to_thread(ensure_members, guild)
            except Exception:
                continue
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot:
                        self.active[(guild.id, member.id)] = (current, channel.id, channel.name)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or before.channel == after.channel:
            return
        await asyncio.to_thread(self.record_voice_change, member, before, after)

    def record_voice_change(self, member, before, after):
        ensure_members(member.guild)
        current = now()
        key = (member.guild.id, member.id)
        if before.channel is not None:
            session = self.active.pop(key, None)
            if session:
                joined, channel_id, channel_name = session
                seconds = max(0, int((current - joined).total_seconds()))
                with db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """insert into public.discordbot_voice_sessions
                            (guild_id,user_id,display_name,channel_id,channel_name,joined_at,left_at,duration_seconds)
                            values(%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (member.guild.id,member.id,member.display_name,channel_id,channel_name,joined,current,seconds),
                        )
                        cur.execute(
                            """update public.discordbot_member_activity set last_voice_at=%s,updated_at=%s
                            where guild_id=%s and user_id=%s""",
                            (current,current,member.guild.id,member.id),
                        )
        if after.channel is not None:
            self.active[key] = (current, after.channel.id, after.channel.name)
            with db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """update public.discordbot_member_activity set last_voice_at=%s,updated_at=%s
                        where guild_id=%s and user_id=%s""",
                        (current,current,member.guild.id,member.id),
                    )

    def check_warnings(self, guild: discord.Guild) -> int:
        rows = activity_rows(guild)
        current = now()
        total = 0
        with db() as conn:
            with conn.cursor() as cur:
                for item in rows:
                    count = math.floor(item["inactive_seconds"] / (WARNING_DAYS * 86400)) - item["warnings"]
                    if count <= 0:
                        continue
                    member = item["member"]
                    cur.execute(
                        """update public.discordbot_member_activity
                        set warning_count=warning_count+%s,last_warning_at=%s,updated_at=%s
                        where guild_id=%s and user_id=%s""",
                        (count,current,current,guild.id,member.id),
                    )
                    for _ in range(count):
                        cur.execute(
                            """insert into public.discordbot_warning_history
                            (guild_id,user_id,display_name,awarded_at,inactivity_days,reason)
                            values(%s,%s,%s,%s,%s,%s)""",
                            (guild.id,member.id,member.display_name,current,WARNING_DAYS,"음성채널 7일 미접속"),
                        )
                    total += count
        return total

    def panel_embed(self, guild: discord.Guild, database_name: str) -> discord.Embed:
        rows = activity_rows(guild)
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) as count from public.discordbot_voice_sessions where guild_id=%s", (guild.id,))
                sessions = int(cur.fetchone()["count"])
        embed = discord.Embed(title="🎙️ 음성 활동 관리 패널", color=0x57F287)
        embed.description = "✅ **Supabase DB 연결 정상**"
        embed.add_field(name="프로젝트", value="kokiriko", inline=True)
        embed.add_field(name="데이터베이스", value=database_name, inline=True)
        embed.add_field(name="추적 멤버", value=f"{len(rows)}명", inline=True)
        embed.add_field(name="7일 이상 미접속", value=f"{sum(r['inactive_seconds'] >= 604800 for r in rows)}명", inline=True)
        embed.add_field(name="경고 보유", value=f"{sum(r['warnings'] > 0 for r in rows)}명", inline=True)
        embed.add_field(name="완료된 세션", value=f"{sessions:,}건", inline=True)
        embed.set_footer(text=f"연결 확인: {now().strftime('%Y-%m-%d %H:%M:%S')} KST")
        return embed

    def member_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = activity_rows(guild)
        embed = discord.Embed(title="👥 전체 멤버 음성 미접속 현황", color=0x3498DB)
        embed.description = "\n".join(
            f"{r['member'].mention} · 미접속 **{duration_text(r['inactive_seconds'])}** · 경고 **{r['warnings']}회**"
            for r in rows[:40]
        ) or "표시할 멤버가 없습니다."
        return embed

    def recent_embed(self, guild: discord.Guild) -> discord.Embed:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from public.discordbot_voice_sessions where guild_id=%s order by id desc limit 20", (guild.id,))
                rows = cur.fetchall()
        embed = discord.Embed(title="🎙️ 최근 음성채널 입퇴장 기록", color=0x57F287)
        embed.description = "\n".join(
            f"<@{r['user_id']}> · **{r['channel_name']}** · {duration_text(r['duration_seconds'])}"
            for r in rows
        ) or "기록된 세션이 없습니다."
        return embed

    def make_excel(self, guild: discord.Guild) -> discord.File:
        book = Workbook()
        sheet = book.active
        sheet.title = "음성 입퇴장 기록"
        sheet.append(["유저 ID","닉네임","채널명","입장","퇴장","사용 시간(분)"])
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute("select * from public.discordbot_voice_sessions where guild_id=%s order by joined_at desc", (guild.id,))
                for row in cur.fetchall():
                    sheet.append([row["user_id"],row["display_name"],row["channel_name"],str(row["joined_at"]),str(row["left_at"]),round(row["duration_seconds"]/60,1)])
        output = io.BytesIO()
        book.save(output)
        output.seek(0)
        return discord.File(output, filename=f"voice_audit_{now().strftime('%Y%m%d_%H%M')}.xlsx")

    @app_commands.command(name="음성관리패널", description="[전용 관리자] 음성 기록 및 DB 연결 상태를 확인합니다.")
    async def panel(self, interaction: discord.Interaction):
        if not authorized(interaction):
            await deny(interaction)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            database_name = await asyncio.to_thread(verify_database)
            embed = await asyncio.to_thread(self.panel_embed, interaction.guild, database_name)
            await interaction.followup.send(embed=embed, view=VoiceAuditView(self), ephemeral=True)
        except Exception as exc:
            await db_error(interaction, exc)

    @app_commands.command(name="음성기록엑셀", description="[전용 관리자] 음성 기록을 Excel로 출력합니다.")
    async def export_excel(self, interaction: discord.Interaction):
        if not authorized(interaction):
            await deny(interaction)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            file = await asyncio.to_thread(self.make_excel, interaction.guild)
            await interaction.followup.send(file=file, ephemeral=True)
        except Exception as exc:
            await db_error(interaction, exc)

    @tasks.loop(hours=1)
    async def warning_loop(self):
        for guild in self.bot.guilds:
            try:
                await asyncio.to_thread(self.check_warnings, guild)
            except Exception:
                pass

    @warning_loop.before_loop
    async def before_warning_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceAuditCog(bot))
