"""파티 모집 설정과 게시물 상태 저장소."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

RecruitState = dict[str, Any]


class RecruitStore:
    """작은 JSON 파일에 모집 패널과 게시물 상태를 보관한다."""

    def __init__(
        self,
        config_file: Path = Path("recruit_config.json"),
        posts_file: Path = Path("recruit_posts.json"),
    ) -> None:
        self.config_file = config_file
        self.posts_file = posts_file
        self.config: dict[str, dict[str, int]] = {}
        self.recruits: dict[str, RecruitState] = {}
        self.load()

    @staticmethod
    def now() -> int:
        return int(time.time())

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)

    def load(self) -> None:
        self.config = self._read(self.config_file)
        self.recruits = self._read(self.posts_file)

        # 구버전 설정 파일을 그대로 사용할 수 있게 키 이름만 이전한다.
        migrated = False
        for config in self.config.values():
            if "message_id" in config and "panel_message_id" not in config:
                config["panel_message_id"] = config.pop("message_id")
                migrated = True
        if migrated:
            self.save_config()

    def save_config(self) -> None:
        self._write(self.config_file, self.config)

    def save_recruits(self) -> None:
        self._write(self.posts_file, self.recruits)

    def set_panel(self, guild_id: int, channel_id: int, message_id: int) -> None:
        self.config[str(guild_id)] = {
            "channel_id": channel_id,
            "panel_message_id": message_id,
        }
        self.save_config()

    def get_panel(self, guild_id: int) -> dict[str, int] | None:
        return self.config.get(str(guild_id))

    def add(self, state: RecruitState) -> None:
        self.recruits[str(state["message_id"])] = state
        self.save_recruits()

    def remove(self, message_id: int) -> RecruitState | None:
        state = self.recruits.pop(str(message_id), None)
        if state is not None:
            self.save_recruits()
        return state

    def save(self) -> None:
        self.save_recruits()

    def is_live(self, state: RecruitState) -> bool:
        """삭제되거나 만료되지 않아 버튼을 계속 사용할 수 있는 게시물인지 확인한다."""
        return int(state.get("expires_at", 0)) > self.now()

    def is_open(self, state: RecruitState) -> bool:
        """현재 새 참가자를 받을 수 있는 게시물인지 확인한다."""
        return self.is_live(state) and not state.get("closed", False)

    def open_for_guild(self, guild_id: int) -> list[RecruitState]:
        states = [
            state
            for state in self.recruits.values()
            if int(state.get("guild_id", 0)) == guild_id and self.is_open(state)
        ]
        return sorted(states, key=lambda item: int(item.get("created_at", 0)), reverse=True)

    def find_user_recruit(self, guild_id: int, user_id: int) -> RecruitState | None:
        """한 사용자가 동시에 여러 모집에 들어가는 것을 막기 위한 조회."""
        for state in self.recruits.values():
            if int(state.get("guild_id", 0)) != guild_id or not self.is_live(state):
                continue
            if user_id in state.get("member_ids", []):
                return state
        return None

    def expired(self) -> list[tuple[int, RecruitState]]:
        expired: list[tuple[int, RecruitState]] = []
        for message_id, state in self.recruits.items():
            if int(state.get("expires_at", 0)) <= self.now():
                expired.append((int(message_id), state))
        return expired
