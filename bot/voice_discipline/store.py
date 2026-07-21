"""Persistence for voice-warning DM templates and soft-ban audit history."""
from __future__ import annotations

from bot.cogs import voice_audit

MAX_DM_TEMPLATE_LENGTH = 1800
DEFAULT_DM_MESSAGE = (
    "안녕하세요, {member}님.\n\n"
    "{server} 서버의 음성채널 미접속 경고가 {warnings}회 누적되어 "
    "잠시 후 서버에서 퇴장 처리됩니다.\n\n"
    "이번 조치는 영구 차단이 아닌 소프트밴입니다. 밴은 즉시 해제되므로 "
    "새 초대 링크를 통해 다시 참여할 수 있습니다.\n\n"
    "재가입하면 경고는 0회부터 다시 집계됩니다. 서버 활동 규칙을 다시 확인해 주세요."
)


def ensure_schema() -> None:
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists public.discordbot_voice_discipline_config (
                guild_id bigint primary key,
                dm_message text not null,
                updated_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            """
            create table if not exists public.discordbot_voice_softban_history (
                id bigserial primary key,
                guild_id bigint not null,
                user_id bigint not null,
                display_name text not null,
                warning_count integer not null,
                dm_sent boolean not null,
                ban_succeeded boolean not null,
                unban_succeeded boolean not null,
                error_text text,
                processed_at timestamptz not null default now()
            )
            """
        )


def get_dm_message(guild_id: int) -> str:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            "select dm_message from public.discordbot_voice_discipline_config where guild_id=%s",
            (guild_id,),
        )
        row = cur.fetchone()
    return str(row["dm_message"]) if row else DEFAULT_DM_MESSAGE


def set_dm_message(guild_id: int, message: str) -> None:
    message = message.strip()
    if not message:
        raise ValueError("DM 안내문을 비워둘 수 없습니다.")
    if len(message) > MAX_DM_TEMPLATE_LENGTH:
        raise ValueError(f"DM 안내문은 {MAX_DM_TEMPLATE_LENGTH}자 이하여야 합니다.")

    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into public.discordbot_voice_discipline_config(guild_id,dm_message,updated_at)
            values(%s,%s,%s)
            on conflict(guild_id)
            do update set dm_message=excluded.dm_message,updated_at=excluded.updated_at
            """,
            (guild_id, message, voice_audit.now()),
        )


def reset_warning_after_softban(guild_id: int, user_id: int) -> None:
    current = voice_audit.now()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update public.discordbot_member_activity
            set warning_count=0,
                last_warning_at=null,
                last_voice_at=null,
                baseline_at=%s,
                updated_at=%s
            where guild_id=%s and user_id=%s
            """,
            (current, current, guild_id, user_id),
        )


def record_softban_result(
    *,
    guild_id: int,
    user_id: int,
    display_name: str,
    warning_count: int,
    dm_sent: bool,
    ban_succeeded: bool,
    unban_succeeded: bool,
    error_text: str | None,
) -> None:
    ensure_schema()
    with voice_audit.db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into public.discordbot_voice_softban_history
            (guild_id,user_id,display_name,warning_count,dm_sent,ban_succeeded,
             unban_succeeded,error_text,processed_at)
            values(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                guild_id,
                user_id,
                display_name,
                warning_count,
                dm_sent,
                ban_succeeded,
                unban_succeeded,
                error_text,
                voice_audit.now(),
            ),
        )
