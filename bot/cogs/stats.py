"""음성채널 활동 추적과 통계 리포트."""
from __future__ import annotations

import datetime
import io
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

KST = ZoneInfo("Asia/Seoul")
DB_PATH = Path("overwatch_bot.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_logs (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                channel_name TEXT NOT NULL,
                join_time TEXT NOT NULL,
                leave_time TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                date TEXT NOT NULL
            )
            """
        )


def fmt_duration(seconds: int) -> str:
    hours, remainder = divmod(max(seconds, 0), 3600)
    minutes = remainder // 60
    return f"{hours}시간 {minutes}분" if hours else f"{minutes}분"


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: dict[tuple[int, int], tuple[datetime.datetime, str]] = {}
        init_db()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        now = datetime.datetime.now(KST)
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot:
                        self.sessions[(guild.id, member.id)] = (now, channel.name)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        key = (member.guild.id, member.id)
        now = datetime.datetime.now(KST)

        if before.channel is None and after.channel is not None:
            self.sessions[key] = (now, after.channel.name)
            return

        if before.channel is not None and before.channel != after.channel:
            session = self.sessions.pop(key, None)
            if session:
                joined, channel_name = session
                duration = int((now - joined).total_seconds())
                if duration >= 30:
                    with get_conn() as conn:
                        conn.execute(
                            "INSERT INTO voice_logs VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                member.guild.id,
                                member.id,
                                channel_name,
                                joined.isoformat(),
                                now.isoformat(),
                                duration,
                                joined.date().isoformat(),
                            ),
                        )
            if after.channel is not None:
                self.sessions[key] = (now, after.channel.name)

    async def build_ranking(self, guild: discord.Guild, start_date: str, end_date: str) -> discord.Embed:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT user_id, SUM(duration_seconds) AS total, COUNT(*) AS sessions
                FROM voice_logs
                WHERE guild_id = ? AND date BETWEEN ? AND ?
                GROUP BY user_id
                ORDER BY total DESC
                LIMIT 10
                """,
                (guild.id, start_date, end_date),
            ).fetchall()

        embed = discord.Embed(
            title="🎙️ 음성채널 활동 순위",
            description=f"{start_date} ~ {end_date}",
            color=0x5865F2,
        )
        if not rows:
            embed.description += "\n기록된 활동이 없습니다."
            return embed

        lines = []
        for index, row in enumerate(rows, start=1):
            member = guild.get_member(row["user_id"])
            name = member.display_name if member else f"유저 {row['user_id']}"
            lines.append(f"`{index}.` **{name}** — {fmt_duration(row['total'])} ({row['sessions']}회)")
        embed.add_field(name="순위", value="\n".join(lines), inline=False)
        return embed

    @app_commands.command(name="요약", description="[관리자] 특정 날짜의 음성채널 활동을 요약합니다.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(날짜="YYYY-MM-DD, 비우면 오늘")
    async def daily_summary(self, interaction: discord.Interaction, 날짜: str | None = None) -> None:
        target = 날짜 or datetime.datetime.now(KST).date().isoformat()
        try:
            datetime.date.fromisoformat(target)
        except ValueError:
            await interaction.response.send_message("날짜 형식은 YYYY-MM-DD입니다.", ephemeral=True)
            return
        await interaction.response.send_message(embed=await self.build_ranking(interaction.guild, target, target))

    @app_commands.command(name="주간리포트", description="[관리자] 이번 주 음성채널 활동 리포트를 표시합니다.")
    @app_commands.default_permissions(administrator=True)
    async def weekly_report(self, interaction: discord.Interaction) -> None:
        today = datetime.datetime.now(KST).date()
        start = today - datetime.timedelta(days=today.weekday())
        end = start + datetime.timedelta(days=6)
        await interaction.response.send_message(
            embed=await self.build_ranking(interaction.guild, start.isoformat(), end.isoformat())
        )

    @app_commands.command(name="월간리포트", description="[관리자] 이번 달 음성채널 활동 리포트를 표시합니다.")
    @app_commands.default_permissions(administrator=True)
    async def monthly_report(self, interaction: discord.Interaction) -> None:
        today = datetime.datetime.now(KST).date()
        start = today.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - datetime.timedelta(days=1)
        await interaction.response.send_message(
            embed=await self.build_ranking(interaction.guild, start.isoformat(), end.isoformat())
        )

    @app_commands.command(name="현재순위", description="이번 달 음성채널 활동 순위를 표시합니다.")
    async def current_rank(self, interaction: discord.Interaction) -> None:
        today = datetime.datetime.now(KST).date()
        start = today.replace(day=1)
        embed = await self.build_ranking(interaction.guild, start.isoformat(), today.isoformat())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="실시간세션", description="[관리자] 현재 음성채널 접속 현황을 확인합니다.")
    @app_commands.default_permissions(administrator=True)
    async def live_sessions(self, interaction: discord.Interaction) -> None:
        now = datetime.datetime.now(KST)
        lines = []
        for (guild_id, user_id), (joined, channel_name) in self.sessions.items():
            if guild_id != interaction.guild_id:
                continue
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else str(user_id)
            lines.append(f"• **{name}** — {channel_name} · {fmt_duration(int((now - joined).total_seconds()))}")
        await interaction.response.send_message("\n".join(lines) or "현재 접속 중인 유저가 없습니다.", ephemeral=True)

    @app_commands.command(name="유령회원", description="[관리자] 최근 음성채널 활동이 없는 멤버를 찾습니다.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(기간="미접속 기준 일수")
    async def ghost_members(
        self,
        interaction: discord.Interaction,
        기간: app_commands.Range[int, 1, 365] = 30,
    ) -> None:
        cutoff = (datetime.datetime.now(KST).date() - datetime.timedelta(days=기간)).isoformat()
        with get_conn() as conn:
            active = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT user_id FROM voice_logs WHERE guild_id = ? AND date >= ?",
                    (interaction.guild_id, cutoff),
                )
            }
        ghosts = [member for member in interaction.guild.members if not member.bot and member.id not in active]
        text = "\n".join(member.mention for member in ghosts[:50]) or "해당하는 멤버가 없습니다."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="데이터백업", description="[관리자] 음성 활동 데이터를 CSV로 내보냅니다.")
    @app_commands.default_permissions(administrator=True)
    async def export_data(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM voice_logs WHERE guild_id = ? ORDER BY join_time DESC",
                (interaction.guild_id,),
            ).fetchall()
        output = io.StringIO()
        output.write("guild_id,user_id,channel_name,join_time,leave_time,duration_seconds,date\n")
        for row in rows:
            escaped_channel = row["channel_name"].replace('"', '""')
            output.write(
                f"{row['guild_id']},{row['user_id']},\"{escaped_channel}\",{row['join_time']},"
                f"{row['leave_time']},{row['duration_seconds']},{row['date']}\n"
            )
        data = io.BytesIO(output.getvalue().encode("utf-8-sig"))
        await interaction.followup.send(
            file=discord.File(data, filename="voice_stats.csv"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
