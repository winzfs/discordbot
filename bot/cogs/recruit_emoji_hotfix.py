"""파티 모집 앱의 잘못된 버튼 이모지를 교정한다.

Discord 버튼의 ``emoji`` 필드는 일반 텍스트 화살표(←)를 허용하지 않는다.
기존 화면 구조는 유지하면서 해당 뒤로가기 버튼들만 표준 이모지(⬅️)로
교체한다. 원본 클래스의 callback은 그대로 사용한다.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bot.recruiting import builder, manage

logger = logging.getLogger(__name__)
BACK_EMOJI = "⬅️"


def _builder_cancel_init(self: discord.ui.Button) -> None:
    discord.ui.Button.__init__(
        self,
        label="취소",
        emoji=BACK_EMOJI,
        style=discord.ButtonStyle.secondary,
        custom_id="recruit:builder:cancel",
    )


def _manage_back_init(self: discord.ui.Button) -> None:
    discord.ui.Button.__init__(
        self,
        label="내 파티로",
        emoji=BACK_EMOJI,
        style=discord.ButtonStyle.secondary,
    )


def _edit_back_init(self: discord.ui.Button) -> None:
    discord.ui.Button.__init__(
        self,
        label="취소",
        emoji=BACK_EMOJI,
        style=discord.ButtonStyle.secondary,
    )


def _cancel_delete_init(self: discord.ui.Button) -> None:
    discord.ui.Button.__init__(
        self,
        label="돌아가기",
        emoji=BACK_EMOJI,
        style=discord.ButtonStyle.secondary,
    )


def _cancel_leave_init(self: discord.ui.Button) -> None:
    discord.ui.Button.__init__(
        self,
        label="계속 참가",
        emoji=BACK_EMOJI,
        style=discord.ButtonStyle.secondary,
    )


def install_patch() -> None:
    """현재 앱 화면에서 사용되는 모든 일반 화살표 버튼을 교체한다."""
    builder._BuilderCancelButton.__init__ = _builder_cancel_init
    manage._ManageBackButton.__init__ = _manage_back_init
    manage._EditBackButton.__init__ = _edit_back_init
    manage._CancelDeleteButton.__init__ = _cancel_delete_init
    manage._CancelLeaveButton.__init__ = _cancel_leave_init


class RecruitEmojiHotfixCog(commands.Cog):
    """확장 모듈 수명 주기를 위한 빈 Cog."""


async def setup(bot: commands.Bot) -> None:
    install_patch()

    # 배포 시점에 패치 누락을 즉시 발견하도록 버튼 직렬화 전 상태를 검사한다.
    checks = (
        builder._BuilderCancelButton(),
        manage._ManageBackButton(),
        manage._EditBackButton(),
        manage._CancelDeleteButton(),
        manage._CancelLeaveButton(),
    )
    if any(str(button.emoji) != BACK_EMOJI for button in checks):
        raise RuntimeError("파티 모집 뒤로가기 버튼 이모지 패치 검증 실패")

    await bot.add_cog(RecruitEmojiHotfixCog())
    logger.info("파티 모집 버튼 이모지 핫픽스 적용 완료: %s", BACK_EMOJI)
