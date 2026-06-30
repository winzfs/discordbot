import asyncio
import logging

from bot.app import DiscordBot
from bot.config import Settings
from bot.logging_config import configure_logging


async def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    bot = DiscordBot(settings)

    try:
        await bot.start(settings.discord_token)
    except KeyboardInterrupt:
        logger.info("종료 요청을 받았습니다.")
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
