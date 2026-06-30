"""음성채널 기록, 7일 미접속 경고, 관리자 전용 패널과 Excel 출력."""
from __future__ import annotations

import datetime as dt
import io
import math
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ADMIN_USER_ID = 324558739921305602
WARNING_DAYS = 7
KST = ZoneInfo("Asia/Seoul")
DB_PATH = Path("voice_audit.db")
MIGRATION_KEY = "baseline_from_feature_start_v2"


def now() -> dt.datetime:
    return dt.datetime.now(KST)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    current = now().isoformat()
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS voice_sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                left_at TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS member_activity(
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                baseline_at TEXT NOT NULL,
                last_voice_at TEXT,
                last_warning_at TEXT,
                warning_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS warning_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                awarded_at TEXT NOT NULL,
                inactivity_days INTEGER NOT NULL,
                reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS voice_audit_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        migrated = conn.execute(
            "SELECT 1 FROM voice_audit_meta WHERE key=?", (MIGRATION_KEY,)
        ).fetchone()
        if not migrated:
            conn.execute(
                """
                UPDATE member_activity
                SET baseline_at=?, last_warning_at=NULL, warning_count=0
                """,
                (current,),
            )
            conn.execute("DELETE FROM warning_history")
            conn.execute(
                "INSERT INTO voice_audit_meta(key,value) VALUES(?,?)",
                (MIGRATION_KEY, current),
            )


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
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


def ensure_member(member: discord.Member) -> None:
    if member.bot:
        return
    with db() as conn:
        conn.execute(
            """
            INSERT INTO member_activity(guild_id,user_id,display_name,baseline_at)
            VALUES(?,?,?,?)
            ON CONFLICT(guild_id,user_id)
            DO UPDATE SET display_name=excluded.display_name
            """,
            (member.guild.id, member.id, member.display_name, now().isoformat()),
        )


def activity_rows(guild: discord.Guild) -> list[dict]:
    current = now()
    for member in guild.members:
        ensure_member(member)
    with db() as conn:
        saved = {
            row["user_id"]: row
            for row in conn.execute("SELECT * FROM member_activity WHERE guild_id=?", (guild.id,))
        }
    rows = []
    for member in guild.members:
        if member.bot:
            continue
        row = saved.get(member.id)
        baseline = parse_time(row["baseline_at"]) if row else current
        last_voice = parse_time(row["last_voice_at"]) if row else None
        reference = last_voice or baseline or current
        rows.append({
            "member": member,
            "last_voice": last_voice,
            "inactive_seconds": max(0, int((current - reference).total_seconds())),
            "warnings": int(row["warning_count"]) if row else 0,
        })
    return sorted(rows, key=lambda item: item["inactive_seconds"], reverse=True)


def authorized(interaction: discord.Interaction) -> bool:
    return interaction.user.id == ADMIN_USER_ID


async def deny(interaction: discord.Interaction) -> None:
    text = "이 기능은 지정된 관리자만 사용할 수 있습니다."
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


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
    async def members(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=self.cog.member_embed(interaction.guild), ephemeral=True)

    @discord.ui.button(label="경고 현황", emoji="⚠️", style=discord.ButtonStyle.danger)
    async def warnings(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=self.cog.warning_embed(interaction.guild), ephemeral=True)

    @discord.ui.button(label="최근 입퇴장", emoji="🎙️", style=discord.ButtonStyle.secondary)
    async def recent(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=self.cog.recent_embed(interaction.guild), ephemeral=True)

    @discord.ui.button(label="즉시 경고 점검", emoji="🔍", style=discord.ButtonStyle.success)
    async def check(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        count = await self.cog.check_warnings(interaction.guild)
        await interaction.followup.send(f"새 경고 **{count}회**를 부여했습니다.", ephemeral=True)

    @discord.ui.button(label="Excel 출력", emoji="📊", style=discord.ButtonStyle.success)
    async def excel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(file=self.cog.make_excel(interaction.guild), ephemeral=True)


class VoiceAuditCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[tuple[int, int], tuple[dt.datetime, int, str]] = {}
        init_db()
        self.warning_loop.start()

    def cog_unload(self) -> None:
        self.warning_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        current = now()
        for guild in self.bot.guilds:
            for member in guild.members:
                ensure_member(member)
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot:
                        self.active[(guild.id, member.id)] = (current, channel.id, channel.name)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        ensure_member(member)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.bot or before.channel == after.channel:
            return
        current = now()
        key = (member.guild.id, member.id)
        ensure_member(member)

        if before.channel is not None:
            session = self.active.pop(key, None)
            if session:
                joined, channel_id, channel_name = session
                seconds = max(0, int((current - joined).total_seconds()))
                with db() as conn:
                    conn.execute(
                        """
                        INSERT INTO voice_sessions(
                            guild_id,user_id,display_name,channel_id,channel_name,joined_at,left_at,duration_seconds
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (member.guild.id, member.id, member.display_name, channel_id, channel_name,
                         joined.isoformat(), current.isoformat(), seconds),
                    )
                    conn.execute(
                        "UPDATE member_activity SET display_name=?,last_voice_at=? WHERE guild_id=? AND user_id=?",
                        (member.display_name, current.isoformat(), member.guild.id, member.id),
                    )

        if after.channel is not None:
            self.active[key] = (current, after.channel.id, after.channel.name)
            with db() as conn:
                conn.execute(
                    "UPDATE member_activity SET display_name=?,last_voice_at=? WHERE guild_id=? AND user_id=?",
                    (member.display_name, current.isoformat(), member.guild.id, member.id),
                )

    async def check_warnings(self, guild: discord.Guild) -> int:
        current = now()
        total = 0
        for member in guild.members:
            if member.bot:
                continue
            ensure_member(member)
            with db() as conn:
                row = conn.execute(
                    "SELECT * FROM member_activity WHERE guild_id=? AND user_id=?",
                    (guild.id, member.id),
                ).fetchone()
                baseline = parse_time(row["baseline_at"]) or current
                last_voice = parse_time(row["last_voice_at"])
                last_warning = parse_time(row["last_warning_at"])
                reference = max(value for value in (baseline, last_voice, last_warning) if value)
                count = math.floor((current - reference).total_seconds() / (WARNING_DAYS * 86400))
                if count <= 0:
                    continue
                warning_time = reference + dt.timedelta(days=WARNING_DAYS * count)
                conn.execute(
                    """
                    UPDATE member_activity
                    SET warning_count=warning_count+?,last_warning_at=?
                    WHERE guild_id=? AND user_id=?
                    """,
                    (count, warning_time.isoformat(), guild.id, member.id),
                )
                for index in range(count):
                    awarded = reference + dt.timedelta(days=WARNING_DAYS * (index + 1))
                    conn.execute(
                        """
                        INSERT INTO warning_history(guild_id,user_id,display_name,awarded_at,inactivity_days,reason)
                        VALUES(?,?,?,?,?,?)
                        """,
                        (guild.id, member.id, member.display_name, awarded.isoformat(), WARNING_DAYS,
                         "음성채널 7일 미접속"),
                    )
                total += count
        return total

    def panel_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = activity_rows(guild)
        with db() as conn:
            sessions = conn.execute("SELECT COUNT(*) FROM voice_sessions WHERE guild_id=?", (guild.id,)).fetchone()[0]
        embed = discord.Embed(title="🎙️ 음성 활동 관리 패널", color=0x5865F2)
        embed.add_field(name="추적 멤버", value=f"{len(rows)}명", inline=True)
        embed.add_field(name="7일 이상 미접속", value=f"{sum(r['inactive_seconds'] >= 604800 for r in rows)}명", inline=True)
        embed.add_field(name="경고 보유", value=f"{sum(r['warnings'] > 0 for r in rows)}명", inline=True)
        embed.add_field(name="완료된 세션", value=f"{sessions:,}건", inline=True)
        embed.set_footer(text="미접속 기간은 기능 도입 시점부터 계산됩니다.")
        return embed

    def member_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = activity_rows(guild)
        embed = discord.Embed(title="👥 전체 멤버 음성 미접속 현황", color=0x3498DB)
        embed.description = "\n".join(
            f"{r['member'].mention} · 미접속 **{duration_text(r['inactive_seconds'])}** · 경고 **{r['warnings']}회**"
            for r in rows[:40]
        ) or "표시할 멤버가 없습니다."
        if len(rows) > 40:
            embed.set_footer(text=f"40명 표시 · 전체 {len(rows)}명은 Excel에서 확인")
        return embed

    def warning_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = [row for row in activity_rows(guild) if row["warnings"] > 0]
        embed = discord.Embed(title="⚠️ 누적 경고 현황", color=0xED4245)
        embed.description = "\n".join(
            f"{r['member'].mention} · 경고 **{r['warnings']}회** · 미접속 {duration_text(r['inactive_seconds'])}"
            for r in rows[:40]
        ) or "경고 보유 멤버가 없습니다."
        return embed

    def recent_embed(self, guild: discord.Guild) -> discord.Embed:
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM voice_sessions WHERE guild_id=? ORDER BY id DESC LIMIT 20", (guild.id,)
            ).fetchall()
        embed = discord.Embed(title="🎙️ 최근 음성채널 입퇴장 기록", color=0x57F287)
        embed.description = "\n".join(
            f"<@{r['user_id']}> · **{r['channel_name']}** · {duration_text(r['duration_seconds'])} · "
            f"{parse_time(r['joined_at']).strftime('%m-%d %H:%M')} → {parse_time(r['left_at']).strftime('%H:%M')}"
            for r in rows
        ) or "기록된 세션이 없습니다."
        return embed

    def make_excel(self, guild: discord.Guild) -> discord.File:
        book = Workbook()
        fill = PatternFill("solid", fgColor="5865F2")
        font = Font(color="FFFFFF", bold=True)

        sessions_sheet = book.active
        sessions_sheet.title = "음성 입퇴장 기록"
        sessions_sheet.append(["유저 ID", "닉네임", "채널 ID", "채널명", "입장", "퇴장", "사용 시간(분)"])
        with db() as conn:
            sessions = conn.execute(
                "SELECT * FROM voice_sessions WHERE guild_id=? ORDER BY joined_at DESC", (guild.id,)
            ).fetchall()
            for row in sessions:
                sessions_sheet.append([
                    row["user_id"], row["display_name"], row["channel_id"], row["channel_name"],
                    row["joined_at"], row["left_at"], round(row["duration_seconds"] / 60, 1),
                ])

        status_sheet = book.create_sheet("멤버 미접속 및 경고")
        status_sheet.append(["유저 ID", "닉네임", "최근 음성 접속", "미접속 시간", "미접속 일수", "누적 경고"])
        for row in activity_rows(guild):
            status_sheet.append([
                row["member"].id, row["member"].display_name,
                row["last_voice"].isoformat() if row["last_voice"] else "기능 도입 후 접속 기록 없음",
                duration_text(row["inactive_seconds"]), round(row["inactive_seconds"] / 86400, 2), row["warnings"],
            ])

        warning_sheet = book.create_sheet("경고 이력")
        warning_sheet.append(["유저 ID", "닉네임", "경고 부여 시각", "기준 일수", "사유"])
        with db() as conn:
            warnings = conn.execute(
                "SELECT * FROM warning_history WHERE guild_id=? ORDER BY awarded_at DESC", (guild.id,)
            ).fetchall()
            for row in warnings:
                warning_sheet.append([
                    row["user_id"], row["display_name"], row["awarded_at"], row["inactivity_days"], row["reason"],
                ])

        for sheet in book.worksheets:
            sheet.freeze_panes = "A2"
            for cell in sheet[1]:
                cell.fill, cell.font = fill, font
            for column in sheet.columns:
                width = min(max(len(str(cell.value or "")) for cell in column) + 2, 45)
                sheet.column_dimensions[column[0].column_letter].width = width

        output = io.BytesIO()
        book.save(output)
        output.seek(0)
        return discord.File(output, filename=f"voice_audit_{guild.id}_{now().strftime('%Y%m%d_%H%M')}.xlsx")

    @app_commands.command(name="음성관리패널", description="[전용 관리자] 음성 기록 및 경고 관리 패널을 엽니다.")
    async def panel(self, interaction: discord.Interaction) -> None:
        if not authorized(interaction):
            await deny(interaction)
            return
        await interaction.response.send_message(
            embed=self.panel_embed(interaction.guild), view=VoiceAuditView(self), ephemeral=True
        )

    @app_commands.command(name="음성기록엑셀", description="[전용 관리자] 음성 기록과 경고 기록을 Excel로 출력합니다.")
    async def export_excel(self, interaction: discord.Interaction) -> None:
        if not authorized(interaction):
            await deny(interaction)
            return
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(file=self.make_excel(interaction.guild), ephemeral=True)

    @tasks.loop(hours=1)
    async def warning_loop(self) -> None:
        for guild in self.bot.guilds:
            await self.check_warnings(guild)

    @warning_loop.before_loop
    async def before_warning_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceAuditCog(bot))
