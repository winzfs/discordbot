"""오버워치 오늘의 운세."""
from __future__ import annotations

import datetime
import hashlib
import random

import discord
from discord import app_commands
from discord.ext import commands

HEROES = [
    "디바", "라인하르트", "윈스턴", "자리야", "라마트라", "정커퀸",
    "캐서디", "솜브라", "벤처", "트레이서", "겐지", "애쉬",
    "아나", "키리코", "루시우", "메르시", "주노", "젠야타",
]
GOOD = [
    "오늘은 팀원과 호흡이 이상할 정도로 잘 맞습니다.",
    "궁극기 타이밍이 기가 막히게 들어맞는 날입니다.",
    "첫 판부터 손이 풀립니다. 자신 있게 시작하세요.",
    "위기 상황에서 한 번쯤 기적 같은 역전이 나옵니다.",
]
BAD = [
    "무리한 진입은 오늘 유독 비싸게 돌아옵니다.",
    "두 판 연속 지면 잠깐 쉬는 편이 좋습니다.",
    "채팅보다 핑과 음성 소통이 멘탈을 지켜줍니다.",
    "익숙하지 않은 영웅은 오늘만큼은 연습방에 두세요.",
]
ADVICE = [
    "첫 교전에서 너무 많은 스킬을 쓰지 마세요.",
    "고지대를 먼저 잡으면 운이 따라옵니다.",
    "물 한 잔 마시고 손목을 풀고 시작하세요.",
    "팀원 한 명을 칭찬하면 분위기가 달라집니다.",
]


def daily_rng(user_id: int) -> random.Random:
    today = datetime.date.today().isoformat()
    seed = hashlib.sha256(f"{today}:{user_id}".encode()).digest()
    return random.Random(seed)


class FortuneCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="운세", description="오늘의 오버워치 운세를 확인합니다.")
    async def fortune(self, interaction: discord.Interaction) -> None:
        rng = daily_rng(interaction.user.id)
        score = rng.randint(1, 5)
        good = score >= 3
        hero = rng.choice(HEROES)
        message = rng.choice(GOOD if good else BAD)
        embed = discord.Embed(
            title="🔮 오늘의 오버워치 운세",
            description=message,
            color=0x57F287 if good else 0xED4245,
        )
        embed.add_field(name="행운 지수", value="★" * score + "☆" * (5 - score), inline=False)
        embed.add_field(name="행운의 영웅", value=hero, inline=True)
        embed.add_field(name="행운의 숫자", value=str(rng.randint(1, 99)), inline=True)
        embed.add_field(name="오늘의 조언", value=rng.choice(ADVICE), inline=False)
        embed.set_footer(text="운세는 매일 자정에 바뀝니다.")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FortuneCog(bot))
