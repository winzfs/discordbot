"""파티 모집 임베드 렌더링."""
from __future__ import annotations

import discord

from .store import RecruitState, RecruitStore

EMBED_COLOR = 0xF06414


def party_link(state: RecruitState) -> str:
    return (
        f"https://discord.com/channels/{state['guild_id']}/"
        f"{state['channel_id']}/{state['message_id']}"
    )


def _member_mentions(state: RecruitState) -> str:
    members = state.get("member_ids", [])
    if not members:
        return "아직 참가자가 없습니다."
    return "\n".join(f"`{index + 1}.` <@{member_id}>" for index, member_id in enumerate(members))


def recruit_embed(state: RecruitState) -> discord.Embed:
    count = len(state.get("member_ids", []))
    maximum = int(state["max_members"])
    closed = state.get("closed", False)

    if closed:
        status = state.get("closed_reason") or "모집 마감"
        title = f"🔒 {state['mode']} 파티 · {status}"
        color = 0x747F8D
    else:
        status = "모집 중"
        title = f"🎮 {state['mode']} 파티 모집"
        color = EMBED_COLOR

    embed = discord.Embed(
        title=title,
        description=state.get("note") or "아래 버튼을 눌러 파티에 참가하세요.",
        color=color,
    )
    embed.add_field(name="파티장", value=f"<@{state['host_id']}>", inline=True)
    embed.add_field(name="인원", value=f"**{count}/{maximum}명**", inline=True)
    embed.add_field(name="상태", value=status, inline=True)
    embed.add_field(name="티어", value=state["tier"], inline=True)
    embed.add_field(name="필요 역할", value=state["role"], inline=True)

    voice_channel_id = state.get("voice_channel_id")
    embed.add_field(
        name="음성 채널",
        value=f"<#{voice_channel_id}>" if voice_channel_id else "파티장에게 확인",
        inline=True,
    )
    embed.add_field(name="참가자", value=_member_mentions(state), inline=False)
    embed.add_field(name="자동 만료", value=f"<t:{state['expires_at']}:R>", inline=True)
    embed.add_field(name="생성 시각", value=f"<t:{state['created_at']}:t>", inline=True)
    embed.set_footer(text="참가가 확정된 경우에만 버튼을 눌러 주세요.")
    return embed


def panel_embed(store: RecruitStore, guild_id: int) -> discord.Embed:
    active = store.open_for_guild(guild_id)
    embed = discord.Embed(
        title="🎮 오버워치 파티 모집",
        description=(
            "버튼을 눌러 조건을 선택하면 모집 글이 바로 생성됩니다.\n"
            "모집 글은 **90분 후 자동 만료**됩니다."
        ),
        color=EMBED_COLOR,
    )

    if active:
        lines = [
            f"• [{state['mode']} · {len(state['member_ids'])}/{state['max_members']}명]"
            f"({party_link(state)}) — <@{state['host_id']}> · {state['role']}"
            for state in active[:8]
        ]
        embed.add_field(name=f"현재 모집 중 · {len(active)}건", value="\n".join(lines), inline=False)
        if len(active) > 8:
            embed.add_field(name="더 보기", value=f"외 {len(active) - 8}건", inline=False)
    else:
        embed.add_field(
            name="현재 모집 중인 파티가 없습니다",
            value="아래 **파티 모집하기** 버튼으로 첫 파티를 열어보세요.",
            inline=False,
        )

    embed.add_field(
        name="이용 방법",
        value="① 조건 선택 → ② 모집 글 생성 → ③ 참가 버튼 → ④ 파티장이 마감",
        inline=False,
    )
    embed.set_footer(text="잠수 모집을 줄이기 위해 오래된 글은 자동 정리됩니다.")
    return embed
