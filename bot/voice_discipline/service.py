"""Three-warning candidate selection and safe soft-ban execution."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import discord

from bot.cogs import voice_audit
from bot.voice_discipline import store

logger = logging.getLogger(__name__)
WARNING_THRESHOLD = 3


@dataclass(slots=True)
class SoftbanTarget:
    member: discord.Member
    warnings: int


def get_softban_targets(guild: discord.Guild, members: list[discord.Member]) -> list[SoftbanTarget]:
    voice_audit.upsert_members(guild.id, members)
    saved = voice_audit.load_activity(guild.id)
    targets = []
    for member in members:
        row = saved.get(member.id)
        warnings = int(row["warning_count"] or 0) if row else 0
        if warnings >= WARNING_THRESHOLD:
            targets.append(SoftbanTarget(member=member, warnings=warnings))
    return sorted(targets, key=lambda item: (-item.warnings, item.member.id))


def render_dm_message(template: str, guild: discord.Guild, target: SoftbanTarget) -> str:
    rendered = (
        template.replace("{member}", target.member.display_name)
        .replace("{server}", guild.name)
        .replace("{warnings}", str(target.warnings))
    )
    return rendered[:2000]


def softban_block_reason(guild: discord.Guild, member: discord.Member) -> str | None:
    if member.id == guild.owner_id:
        return "서버 소유자"
    if member.id == voice_audit.ADMIN_USER_ID:
        return "지정 관리자"

    me = guild.me
    if me is None:
        return "봇 멤버 정보를 확인할 수 없음"
    if not me.guild_permissions.ban_members:
        return "봇에 멤버 차단 권한이 없음"
    if member.top_role >= me.top_role:
        return "봇 역할보다 같거나 높은 역할"
    return None


async def _record_safely(
    guild_id: int,
    target: SoftbanTarget,
    *,
    dm_sent: bool,
    ban_succeeded: bool,
    unban_succeeded: bool,
    error_text: str | None,
) -> None:
    try:
        await asyncio.to_thread(
            store.record_softban_result,
            guild_id=guild_id,
            user_id=target.member.id,
            display_name=target.member.display_name,
            warning_count=target.warnings,
            dm_sent=dm_sent,
            ban_succeeded=ban_succeeded,
            unban_succeeded=unban_succeeded,
            error_text=error_text,
        )
    except Exception:
        logger.exception(
            "소프트밴 처리 이력 저장 실패: guild=%s user=%s",
            guild_id,
            target.member.id,
        )


async def _reset_warning_with_retry(guild_id: int, user_id: int) -> str | None:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            await asyncio.to_thread(store.reset_warning_after_softban, guild_id, user_id)
            return None
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(attempt + 1)
    return f"{type(last_error).__name__}: {last_error}" if last_error else "알 수 없는 경고 초기화 오류"


async def _unban_with_retry(guild: discord.Guild, user_id: int) -> str | None:
    last_error: Exception | None = None
    user = discord.Object(id=user_id)
    for attempt in range(3):
        try:
            await guild.unban(user, reason="3회 경고 소프트밴 즉시 해제 · 재가입 허용")
            return None
        except discord.NotFound:
            return None
        except (discord.Forbidden, discord.HTTPException) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(attempt + 1)
    return f"{type(last_error).__name__}: {last_error}" if last_error else "알 수 없는 밴 해제 오류"


async def execute_softbans(
    guild: discord.Guild,
    targets: list[SoftbanTarget],
    template: str,
) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {
        "success": [],
        "dm_failed": [],
        "skipped": [],
        "ban_failed": [],
        "unban_failed": [],
        "reset_failed": [],
    }

    for target in targets:
        member = target.member
        blocked = softban_block_reason(guild, member)
        if blocked:
            result["skipped"].append({"target": target, "error": blocked})
            await _record_safely(
                guild.id,
                target,
                dm_sent=False,
                ban_succeeded=False,
                unban_succeeded=False,
                error_text=f"처리 제외: {blocked}",
            )
            continue

        dm_sent = False
        dm_error: str | None = None
        try:
            await member.send(render_dm_message(template, guild, target))
            dm_sent = True
        except (discord.Forbidden, discord.HTTPException) as exc:
            dm_error = f"{type(exc).__name__}: {exc}"
            result["dm_failed"].append({"target": target, "error": dm_error})

        try:
            await guild.ban(
                member,
                reason=f"음성채널 미접속 경고 {target.warnings}회 누적 소프트밴",
                delete_message_seconds=0,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            ban_error = f"{type(exc).__name__}: {exc}"
            result["ban_failed"].append({"target": target, "error": ban_error})
            await _record_safely(
                guild.id,
                target,
                dm_sent=dm_sent,
                ban_succeeded=False,
                unban_succeeded=False,
                error_text=" / ".join(filter(None, (dm_error, f"밴 실패: {ban_error}"))),
            )
            continue

        unban_error = await _unban_with_retry(guild, member.id)
        if unban_error:
            result["unban_failed"].append({"target": target, "error": unban_error})
            await _record_safely(
                guild.id,
                target,
                dm_sent=dm_sent,
                ban_succeeded=True,
                unban_succeeded=False,
                error_text=" / ".join(filter(None, (dm_error, f"밴 해제 실패: {unban_error}"))),
            )
            continue

        reset_error = await _reset_warning_with_retry(guild.id, member.id)
        if reset_error:
            result["reset_failed"].append({"target": target, "error": reset_error})
        await _record_safely(
            guild.id,
            target,
            dm_sent=dm_sent,
            ban_succeeded=True,
            unban_succeeded=True,
            error_text=" / ".join(
                filter(
                    None,
                    (
                        dm_error,
                        f"경고 초기화 실패: {reset_error}" if reset_error else None,
                    ),
                )
            ),
        )
        result["success"].append({"target": target, "dm_sent": dm_sent})

    return result
