"""오버워치 Reddit 인기글 자동 게시."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

CONFIG_FILE = Path("reddit_config.json")
SUBREDDITS = ("Overwatch", "CompetitiveOverwatch", "OverwatchUniversity", "Overwatch_Memes")
HEADERS = {"User-Agent": "OverwatchDiscordBot/3.0"}
CONFIG: dict[str, dict] = {}


def load_config() -> None:
    global CONFIG
    try:
        CONFIG = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        CONFIG = {}


def save_config() -> None:
    CONFIG_FILE.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")


async def fetch_posts(subreddit: str, limit: int = 5) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit + 5}"
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return []
                payload = await response.json()
    except (aiohttp.ClientError, TimeoutError):
        return []

    posts = []
    for child in payload.get("data", {}).get("children", []):
        item = child.get("data", {})
        if item.get("stickied") or item.get("over_18"):
            continue
        posts.append({
            "id": item.get("id", ""),
            "title": item.get("title", "제목 없음"),
            "author": item.get("author", "unknown"),
            "score": item.get("score", 0),
            "comments": item.get("num_comments", 0),
            "url": f"https://reddit.com{item.get('permalink', '')}",
            "image": item.get("url") if item.get("post_hint") == "image" else None,
        })
        if len(posts) >= limit:
            break
    return posts


def post_embed(subreddit: str, post: dict) -> discord.Embed:
    embed = discord.Embed(
        title=post["title"][:256],
        url=post["url"],
        description=f"👍 {post['score']:,} · 💬 {post['comments']:,} · u/{post['author']}",
        color=0xFF4500,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if post.get("image"):
        embed.set_image(url=post["image"])
    embed.set_footer(text=f"r/{subreddit}")
    return embed


async def publish(bot: commands.Bot, guild_id: str) -> int:
    cfg = CONFIG.get(guild_id, {})
    channel = bot.get_channel(cfg.get("channel_id", 0))
    if channel is None:
        return 0

    posted = set(cfg.get("posted_ids", []))
    count = 0
    for subreddit in cfg.get("subreddits", ["Overwatch"]):
        for post in await fetch_posts(subreddit, cfg.get("count", 3)):
            if post["id"] in posted:
                continue
            await channel.send(embed=post_embed(subreddit, post))
            posted.add(post["id"])
            count += 1
    cfg["posted_ids"] = list(posted)[-200:]
    save_config()
    return count


class RedditCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        load_config()
        self.auto_post.start()

    def cog_unload(self) -> None:
        self.auto_post.cancel()

    @app_commands.command(name="레딧채널설정", description="[관리자] 이 채널을 Reddit 자동 게시 채널로 설정합니다.")
    @app_commands.default_permissions(administrator=True)
    async def setup_channel(self, interaction: discord.Interaction) -> None:
        CONFIG[str(interaction.guild_id)] = {
            "channel_id": interaction.channel_id,
            "enabled": True,
            "subreddits": ["Overwatch", "CompetitiveOverwatch"],
            "count": 3,
            "posted_ids": [],
        }
        save_config()
        await interaction.response.send_message("Reddit 자동 게시 채널을 설정했습니다.", ephemeral=True)

    @app_commands.command(name="레딧", description="Reddit 오버워치 인기글을 즉시 가져옵니다.")
    @app_commands.describe(서브레딧="가져올 서브레딧", 개수="게시물 개수")
    @app_commands.choices(서브레딧=[app_commands.Choice(name=name, value=name) for name in SUBREDDITS])
    async def reddit(
        self,
        interaction: discord.Interaction,
        서브레딧: app_commands.Choice[str] = None,
        개수: app_commands.Range[int, 1, 10] = 5,
    ) -> None:
        await interaction.response.defer()
        name = 서브레딧.value if 서브레딧 else "Overwatch"
        posts = await fetch_posts(name, 개수)
        if not posts:
            await interaction.followup.send("게시물을 가져오지 못했습니다.", ephemeral=True)
            return
        for post in posts:
            await interaction.followup.send(embed=post_embed(name, post))

    @app_commands.command(name="레딧즉시게시", description="[관리자] 설정된 Reddit 글을 즉시 게시합니다.")
    @app_commands.default_permissions(administrator=True)
    async def post_now(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        count = await publish(self.bot, str(interaction.guild_id))
        await interaction.followup.send(f"새 게시물 {count}개를 게시했습니다.", ephemeral=True)

    @tasks.loop(hours=1)
    async def auto_post(self) -> None:
        for guild_id, cfg in list(CONFIG.items()):
            if cfg.get("enabled"):
                await publish(self.bot, guild_id)

    @auto_post.before_loop
    async def before_auto_post(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RedditCog(bot))
