import discord
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="핑")
    async def ping(self, ctx: commands.Context) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"퐁! `{latency_ms}ms`")

    @commands.command(name="도움말")
    async def help_command(self, ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="봇 도움말",
            description="현재 사용할 수 있는 기본 명령어입니다.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="!핑", value="봇 응답 속도를 확인합니다.", inline=False)
        embed.add_field(name="!도움말", value="이 도움말을 표시합니다.", inline=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
