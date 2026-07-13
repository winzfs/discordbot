"""Components V2 파티 모집 화면에 사용하는 표시 도우미."""
from __future__ import annotations

from .store import RecruitState

ACCENT_COLOR = 0xF06414
CLOSED_COLOR = 0x747F8D
SUCCESS_COLOR = 0x57F287

MODE_EMOJIS = {
    "경쟁전": "🏆",
    "빠른 대전": "⚡",
    "스타디움": "🏟️",
    "아케이드": "🕹️",
    "내전 / 사용자 지정": "🎯",
}

ROLE_EMOJIS = {
    "돌격": "🛡️",
    "공격": "⚔️",
    "지원": "➕",
    "자유 역할": "🎲",
    "무관": "🔄",
}


def party_link(state: RecruitState) -> str:
    return (
        f"https://discord.com/channels/{state['guild_id']}/"
        f"{state['channel_id']}/{state['message_id']}"
    )


def mode_emoji(mode: str) -> str:
    return MODE_EMOJIS.get(mode, "🎮")


def role_emoji(role: str) -> str:
    return ROLE_EMOJIS.get(role, "🎯")


def member_count(state: RecruitState) -> tuple[int, int]:
    return len(state.get("member_ids", [])), int(state.get("max_members", 5))


def progress_bar(current: int, maximum: int) -> str:
    maximum = max(1, maximum)
    current = min(max(0, current), maximum)
    return "▰" * current + "▱" * (maximum - current)


def member_mentions(state: RecruitState) -> str:
    members = state.get("member_ids", [])
    if not members:
        return "아직 참가자가 없습니다."
    return "\n".join(
        f"`{index + 1:02}`  <@{member_id}>"
        for index, member_id in enumerate(members)
    )


def status_info(state: RecruitState) -> tuple[str, str, int]:
    count, maximum = member_count(state)
    if state.get("closed", False):
        reason = state.get("closed_reason") or "모집 마감"
        return "🔒", reason, CLOSED_COLOR
    if count >= maximum:
        return "✅", "정원 마감", CLOSED_COLOR
    return "🟢", "모집 중", ACCENT_COLOR


def compact_party_text(state: RecruitState) -> str:
    count, maximum = member_count(state)
    return (
        f"**{mode_emoji(str(state['mode']))} {state['mode']}**  ·  `{count}/{maximum}명`\n"
        f"<@{state['host_id']}>  ·  {state['tier']}  ·  "
        f"{role_emoji(str(state['role']))} {state['role']}\n"
        f"-# <t:{state['expires_at']}:R> 자동 만료"
    )
