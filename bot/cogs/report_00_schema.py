"""Compatibility migration loaded before the report system cog."""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from bot.cogs import voice_audit

logger = logging.getLogger(__name__)


def migrate_report_config() -> None:
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists public.discordbot_report_config (
                guild_id bigint primary key,
                category_id bigint,
                staff_role_id bigint,
                report_channel_id bigint,
                updated_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            "alter table public.discordbot_report_config add column if not exists category_id bigint"
        )
        cur.execute(
            "alter table public.discordbot_report_config add column if not exists staff_role_id bigint"
        )
        cur.execute(
            "alter table public.discordbot_report_config add column if not exists report_channel_id bigint"
        )
        cur.execute(
            "alter table public.discordbot_report_config alter column category_id drop not null"
        )
        cur.execute(
            "alter table public.discordbot_report_config alter column staff_role_id drop not null"
        )


class ReportSchemaCog(commands.Cog):
    pass


async def setup(bot: commands.Bot) -> None:
    try:
        await asyncio.to_thread(migrate_report_config)
    except Exception:
        logger.exception("신고 설정 테이블 호환성 마이그레이션 실패")
        raise
    await bot.add_cog(ReportSchemaCog())
