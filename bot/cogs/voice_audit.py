"""음성채널 입퇴장 기록, 미접속 경고, 임베드 관리 패널, Excel 내보내기."""
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

KST = ZoneInfo("Asia/Seoul")
DB_PATH = Path("voice_audit.db")
WARNING_DAYS = 7


def now() -> dt.datetime:
    return dt.datetime.now(KST)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS voice_sessions (
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
            CREATE INDEX IF NOT EXISTS idx_voice_sessions_guild_user
            ON voice_sessions(guild_id, user_id, joined_at);

            CREATE TABLE IF NOT EXISTS member_activity (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                baseline_at TEXT NOT NULL,
                last_voice_at TEXT,
                last_warning_at TEXT,
                warning_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS warning_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                awarded_at TEXT NOT NULL,
                inactivity_days INTEGER NOT NULL,
                reason TEXT NOT NULL
            );
            """
        )


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def format_duration(seconds: int) -> str:
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


def format_inactive(last: dt.datetime, current: dt.datetime | None = None) -> str:
    current = current or now()
    seconds = max(0, int((current - last).total_seconds()))
    return format_duration(seconds)


def ensure_member(member: discord.Member) -> None:
    if member.bot:
        return
    baseline = member.joined_at.astimezone(KST) if member.joined_at else now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO member_activity(guild_id, user_id, display_name, baseline_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET display_name=excluded.display_name
            """,
            (member.guild.id, member.id, member.display_name, baseline.isoformat()),
        )


def member_rows(guild: discord.Guild) -> list[dict]:
    current = now()
    rows: list[dict] = []
    with connect() as conn:
        stored = {
            row["user_id"]: row
            for row in conn.execute(
                "SELECT * FROM member_activity WHERE guild_id=?",
                (guild.id,),
            )
        }
    for member in guild.members:
        if member.bot:
            continue
        ensure_member(member)
        row = stored.get(member.id)
        if row is None:
            baseline = member.joined_at.astimezone(KST) if member.joined_at else current
            last_voice = None
            warnings = 0
        else:
            baseline = parse_time(row["baseline_at"]) or current
            last_voice = parse_time(row["last_voice_at"])
            warnings = row["warning_count"]
        reference = last_voice or baseline
        rows.append({
            "member": member,
            "last_voice": last_voice,
            "reference": reference,
            "inactive_seconds": max(0, int((current - reference).total_seconds())),
            "warnings": warnings,
        })
    rows.sort(key=lambda item: item["inactive_seconds"], reverse=True)
    return rows


class VoiceAuditView(discord.ui.View):
    def __init__(self, cog: "VoiceAuditCog"):
        super().__init__(timeout=600)
        self.cog = cog

    async def guard(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("서버 관리 권한이 필요합니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="전체 멤버 현황", emoji="👥", style=discord.ButtonStyle.primary)
    async def members(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if await self.guard(interaction):
            await interaction.response.send_message(embed=self.cog.member_status_embed(interaction.guild), ephemeral=True)

    @discord.ui.button(label="경고 현황", emoji="⚠️", style=discord.ButtonStyle.danger)
    async def warnings(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if await self.guard(interaction):
            await interaction.response.send_message(embed=self.cog.warning_embed(interaction.guild), ephemeral=True)

    @discord.ui.button(label="최근 입퇴장", emoji="🎙️", style=discord.ButtonStyle.secondary)
    async def recent(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if await self.guard(interaction):
            await interaction.response.send_message(embed=self.cog.recent_embed(interaction.guild), ephemeral=True)

    @discord.ui.button(label="즉시 경고 점검", emoji="🔍", style=discord.ButtonStyle.success)
    async def check(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        awarded = await self.cog.check_guild_warnings(interaction.guild)
        await interaction.followup.send(f"점검 완료: 새 경고 **{awarded}회** 부여", ephemeral=True)

    @discord.ui.button(label="Excel 출력", emoji="📊", style=discord.ButtonStyle.success)
    async def excel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        file = self.cog.build_excel(interaction.guild)
        await interaction.followup.send(file=file, ephemeral=True)


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
                joined_at, channel_id, channel_name = session
                duration = max(0, int((current - joined_at).total_seconds()))
                with connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO voice_sessions(
                            guild_id,user_id,display_name,channel_id,channel_name,joined_at,left_at,duration_seconds
                        ) VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            member.guild.id, member.id, member.display_name, channel_id, channel_name,
                            joined_at.isoformat(), current.isoformat(), duration,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE member_activity
                        SET display_name=?, last_voice_at=?
                        WHERE guild_id=? AND user_id=?
                        """,
                        (member.display_name, current.isoformat(), member.guild.id, member.id),
                    )

        if after.channel is not None:
            self.active[key] = (current, after.channel.id, after.channel.name)
            with connect() as conn:
                conn.execute(
                    "UPDATE member_activity SET display_name=?, last_voice_at=? WHERE guild_id=? AND user_id=?",
                    (member.display_name, current.isoformat(), member.guild.id, member.id),
                )

    async def check_guild_warnings(self, guild: discord.Guild) -> int:
        current = now()
        awarded_total = 0
        for member in guild.members:
            if member.bot:
                continue
            ensure_member(member)
            with connect() as conn:
                row = conn.execute(
                    "SELECT * FROM member_activity WHERE guild_id=? AND user_id=?",
                    (guild.id, member.id),
                ).fetchone()
                baseline = parse_time(row["baseline_at"]) or current
                last_voice = parse_time(row["last_voice_at"])
                last_warning = parse_time(row["last_warning_at"])
                reference = max(value for value in (baseline, last_voice, last_warning) if value is not None)
                elapsed_days = (current - reference).total_seconds() / 86400
                new_warnings = math.floor(elapsed_days / WARNING_DAYS)
                if new_warnings <= 0:
                    continue
                warning_time = reference + dt.timedelta(days=WARNING_DAYS * new_warnings)
                conn.execute(
                    """
                    UPDATE member_activity
                    SET display_name=?, warning_count=warning_count+?, last_warning_at=?
                    WHERE guild_id=? AND user_id=?
                    """,
                    (member.display_name, new_warnings, warning_time.isoformat(), guild.id, member.id),
                )
                for number in range(new_warnings):
                    conn.execute(
                        """
                        INSERT INTO warning_history(guild_id,user_id,display_name,awarded_at,inactivity_days,reason)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (
                            guild.id, member.id, member.display_name,
                            (reference + dt.timedelta(days=WARNING_DAYS * (number + 1))).isoformat(),
                            WARNING_DAYS,
                            "음성채널 7일 미접속",
                        ),
                    )
                awarded_total += new_warnings
        return awarded_total

    def panel_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = member_rows(guild)
        warned = sum(1 for row in rows if row["warnings"] > 0)
        inactive_week = sum(1 for row in rows if row["inactive_seconds"] >= WARNING_DAYS * 86400)
        with connect() as conn:
            sessions = conn.execute("SELECT COUNT(*) FROM voice_sessions WHERE guild_id=?", (guild.id,)).fetchone()[0]
        embed = discord.Embed(title="🎙️ 음성 활동 관리 패널", color=0x5865F2)
        embed.description = "입퇴장 기록, 미접속 기간, 누적 경고, Excel 출력을 관리합니다."
        embed.add_field(name="추적 멤버", value=f"{len(rows)}명", inline=True)
        embed.add_field(name="7일 이상 미접속", value=f"{inactive_week}명", inline=True)
        embed.add_field(name="경고 보유", value=f"{warned}명", inline=True)
        embed.add_field(name="완료된 음성 세션", value=f"{sessions:,}건", inline=True)
        embed.set_footer(text="경고는 7일 미접속마다 1회씩 자동 누적됩니다.")
        return embed

    def member_status_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = member_rows(guild)
        embed = discord.Embed(title="👥 전체 멤버 음성 미접속 현황", color=0x3498DB)
        lines = []
        for row in rows[:40]:
            last = row["last_voice"].strftime("%Y-%m-%d %H:%M") if row["last_voice"] else "접속 기록 없음"
            lines.append(
                f"{row['member'].mention} · 미접속 **{format_duration(row['inactive_seconds'])}** · "
                f"경고 **{row['warnings']}회** · 최근 {last}"
            )
        embed.description = "\n".join(lines) or "표시할 멤버가 없습니다."
        if len(rows) > 40:
            embed.set_footer(text=f"상위 40명 표시 · 전체 {len(rows)}명은 Excel에서 확인")
        return embed

    def warning_embed(self, guild: discord.Guild) -> discord.Embed:
        rows = [row for row in member_rows(guild) if row["warnings"] > 0]
        embed = discord.Embed(title="⚠️ 누적 경고 현황", color=0xED4245)
        embed.description = "\n".join(
            f"{row['member'].mention} · 경고 **{row['warnings']}회** · 미접속 {format_duration(row['inactive_seconds'])}"
            for row in rows[:40]
        ) or "경고를 보유한 멤버가 없습니다."
        return embed

    def recent_embed(self, guild: discord.Guild) -> discord.Embed:
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM voice_sessions WHERE guild_id=? ORDER BY id DESC LIMIT 20",
                (guild.id,),
            ).fetchall()
        embed = discord.Embed(title="🎙️ 최근 음성채널 입퇴장 기록", color=0x57F287)
        embed.description = "\n".join(
            f"<@{row['user_id']}> · **{row['channel_name']}** · {format_duration(row['duration_seconds'])} · "
            f"{parse_time(row['joined_at']).strftime('%m-%d %H:%M')} → {parse_time(row['left_at']).strftime('%H:%M')}"
            for row in rows
        ) or "기록된 세션이 없습니다."
        return embed

    def build_excel(self, guild: discord.Guild) -> discord.File:
        workbook = Workbook()
        header_fill = PatternFill("solid", fgColor="5865F2")
        header_font = Font(color="FFFFFF", bold=True)

        sessions_sheet = workbook.active
        sessions_sheet.title = "음성 입퇴장 기록"
        session_headers = ["유저 ID", "닉네임", "채널 ID", "채널명", "입장 시각", "퇴장 시각", "사용 시간(분)"]
        sessions_sheet.append(session_headers)
        with connect() as conn:
            sessions = conn.execute(
                "SELECT * FROM voice_sessions WHERE guild_id=? ORDER BY joined_at DESC",
                (guild.id,),
            ).fetchall()
            for row in sessions:
                sessions_sheet.append([
                    row["user_id"], row["display_name"], row["channel_id"], row["channel_name"],
                    row["joined_at"], row["left_at"], round(row["duration_seconds"] / 60, 1),
                ])

        status_sheet = workbook.create_sheet("멤버 미접속 및 경고")
        status_headers = ["유저 ID", "닉네임", "최근 음성 접속", "미접속 시간", "미접속 일수", "누적 경고"]
        status_sheet.append(status_headers)
        for row in member_rows(guild):
            status_sheet.append([
                row["member"].id,
                row["member"].display_name,
                row["last_voice"].isoformat() if row["last_voice"] else "접속 기록 없음",
                format_duration(row["inactive_seconds"]),
                round(row["inactive_seconds"] / 86400, 2),
                row["warnings"],
            ])

        warning_sheet = workbook.create_sheet("경고 이력")
        warning_headers = ["유저 ID", "닉네임", "경고 부여 시각", "기준 미접속 일수", "사유"]
        warning_sheet.append(warning_headers)
        with connect() as conn:
            warnings = conn.execute(
                "SELECT * FROM warning_history WHERE guild_id=? ORDER BY awarded_at DESC",
                (guild.id,),
            ).fetchall()
            for row in warnings:
                warning_sheet.append([
                    row["user_id"], row["display_name"], row["awarded_at"], row["inactivity_days"], row["reason"],
                ])

        for sheet in workbook.worksheets:
            sheet.freeze_panes = "A2"
            for cell in sheet[1]:
                cell.fill = header_fill
                cell.font = header_font
            for column in sheet.columns:
                width = min(max(len(str(cell.value or "")) for cell in column) + 2, 45)
                sheet.column_dimensions[column[0].column_letter].width = width

        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        filename = f"voice_audit_{guild.id}_{now().strftime('%Y%m%d_%H%M')}.xlsx"
        return discord.File(buffer, filename=filename)

    @app_commands.command(name="음성관리패널", description="[관리자] 음성 기록·미접속 경고 관리 패널을 엽니다.")
    @app_commands.default_permissions(manage_guild=True)
    async def panel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=self.panel_embed(interaction.guild),
            view=VoiceAuditView(self),
            ephemeral=True,
        )

    @app_commands.command(name="음성기록엑셀", description="[관리자] 음성 입퇴장·미접속·경고 기록을 Excel로 출력합니다.")
    @app_commands.default_permissions(manage_guild=True)
    async def export_excel(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(file=self.build_excel(interaction.guild), ephemeral=True)

    @tasks.loop(hours=1)
    async def warning_loop(self) -> None:
        for guild in self.bot.guilds:
            await self.check_guild_warnings(guild)

    @warning_loop.before_loop
    async def before_warning_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceAuditCog(bot))
