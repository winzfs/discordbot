"""생일 등록, 조회, 당일 축하 시스템."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

DATA_FILE = Path("birthday_data.json")
CONFIG_FILE = Path("birthday_config.json")
BIRTHDAYS: dict[str, dict[str, dict]] = {}
CONFIG: dict[str, dict] = {}


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_date(value: str) -> tuple[int, int, int] | None:
    raw = value.replace(".", "").replace("-", "").replace("/", "").strip()
    if len(raw) != 8 or not raw.isdigit():
        return None
    year, month, day = int(raw[:4]), int(raw[4:6]), int(raw[6:])
    try:
        datetime.date(year, month, day)
    except ValueError:
        return None
    return year, month, day


class BirthdayModal(discord.ui.Modal, title="🎂 생일 등록"):
    birthday = discord.ui.TextInput(label="생년월일", placeholder="예: 19990315")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        parsed = parse_date(self.birthday.value)
        if parsed is None:
            await interaction.response.send_message("올바른 생년월일 8자리를 입력하세요.", ephemeral=True)
            return
        year, month, day = parsed
        guild_id = str(interaction.guild_id)
        BIRTHDAYS.setdefault(guild_id, {})[str(interaction.user.id)] = {
            "year": year,
            "month": month,
            "day": day,
            "name": interaction.user.display_name,
        }
        save_json(DATA_FILE, BIRTHDAYS)
        await interaction.response.send_message(
            f"생일을 **{year}년 {month}월 {day}일**로 등록했습니다.", ephemeral=True
        )


class BirthdayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="생일 등록", emoji="🎂", style=discord.ButtonStyle.success, custom_id="birthday:register")
    async def register(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BirthdayModal())

    @discord.ui.button(label="이번 달 생일", emoji="📅", style=discord.ButtonStyle.primary, custom_id="birthday:list")
    async def list_month(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        now = datetime.date.today()
        rows = []
        for user_id, item in BIRTHDAYS.get(str(interaction.guild_id), {}).items():
            if item["month"] == now.month:
                rows.append((item["day"], f"<@{user_id}> — {item['month']}월 {item['day']}일"))
        rows.sort()
        text = "\n".join(row[1] for row in rows) or "이번 달에 등록된 생일이 없습니다."
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="내 생일 삭제", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="birthday:delete")
    async def delete(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        guild_data = BIRTHDAYS.get(str(interaction.guild_id), {})
        guild_data.pop(str(interaction.user.id), None)
        save_json(DATA_FILE, BIRTHDAYS)
        await interaction.response.send_message("등록된 생일을 삭제했습니다.", ephemeral=True)


class BirthdayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global BIRTHDAYS, CONFIG
        BIRTHDAYS = load_json(DATA_FILE)
        CONFIG = load_json(CONFIG_FILE)
        bot.add_view(BirthdayView())
        self.birthday_check.start()

    def cog_unload(self) -> None:
        self.birthday_check.cancel()

    @app_commands.command(name="생일채널설정", description="[관리자] 이 채널을 생일 채널로 설정합니다.")
    @app_commands.default_permissions(administrator=True)
    async def setup_channel(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🎂 생일 등록 및 조회",
            description="아래 버튼으로 생일을 등록하거나 이번 달 생일을 확인하세요.",
            color=0xFF69B4,
        )
        message = await interaction.channel.send(embed=embed, view=BirthdayView())
        CONFIG[str(interaction.guild_id)] = {
            "channel_id": interaction.channel_id,
            "message_id": message.id,
        }
        save_json(CONFIG_FILE, CONFIG)
        await interaction.response.send_message("생일 채널을 설정했습니다.", ephemeral=True)

    @app_commands.command(name="전체생일목록", description="[관리자] 등록된 전체 생일을 조회합니다.")
    @app_commands.default_permissions(administrator=True)
    async def all_birthdays(self, interaction: discord.Interaction) -> None:
        rows = sorted(
            BIRTHDAYS.get(str(interaction.guild_id), {}).items(),
            key=lambda row: (row[1]["month"], row[1]["day"]),
        )
        text = "\n".join(
            f"<@{uid}> — {item['year']}년 {item['month']}월 {item['day']}일" for uid, item in rows
        ) or "등록된 생일이 없습니다."
        await interaction.response.send_message(text[:1900], ephemeral=True)

    @tasks.loop(minutes=30)
    async def birthday_check(self) -> None:
        today = datetime.date.today()
        marker_file = Path(f"birthday_sent_{today.isoformat()}.json")
        sent = set(load_json(marker_file).get("users", []))
        for guild_id, users in BIRTHDAYS.items():
            config = CONFIG.get(guild_id)
            if not config:
                continue
            channel = self.bot.get_channel(config["channel_id"])
            if channel is None:
                continue
            for user_id, item in users.items():
                key = f"{guild_id}:{user_id}"
                if item["month"] == today.month and item["day"] == today.day and key not in sent:
                    await channel.send(f"🎉 <@{user_id}>님, 생일을 진심으로 축하합니다! 🎂")
                    sent.add(key)
        save_json(marker_file, {"users": sorted(sent)})

    @birthday_check.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BirthdayCog(bot))
