from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


def now_ts() -> int:
    return int(time.time())


@dataclass(frozen=True, slots=True)
class HeroDef:
    id: str
    name: str
    emoji: str
    role: str
    description: str
    unlock_level: int
    max_hp: int
    attack: int
    crit: float
    dodge: float
    lifesteal: float
    ultimate_name: str
    ultimate_kind: str
    ultimate_power: float
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnemyDef:
    id: str
    name: str
    emoji: str
    max_hp: int
    attack: int
    tags: tuple[str, ...]
    skill_name: str


@dataclass(frozen=True, slots=True)
class StageDef:
    chapter: int
    stage: int
    name: str
    objective: str
    objective_label: str
    modifier: str
    modifier_label: str
    enemy_ids: tuple[str, ...]
    waves: int
    target_turns: int
    base_power: int
    xp_reward: int
    credit_reward: int
    research_reward: int

    @property
    def global_id(self) -> int:
        return (self.chapter - 1) * 10 + self.stage

    @property
    def mastery_xp(self) -> int:
        return 40 + self.stage * 4 + self.chapter * 3


@dataclass(frozen=True, slots=True)
class ChapterDef:
    number: int
    name: str
    emoji: str
    summary: str
    mechanic: str
    stages: tuple[StageDef, ...]


@dataclass(frozen=True, slots=True)
class UpgradeDef:
    id: str
    name: str
    description: str
    rarity: str
    tags: tuple[str, ...]
    effects: dict[str, float]
    max_stack: int = 5
    hero_id: str | None = None
    requires_any: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchNode:
    id: str
    name: str
    branch: str
    description: str
    max_level: int
    base_cost: int
    cost_growth: float
    effect_key: str
    effect_per_level: float


@dataclass(slots=True)
class Account:
    user_id: int
    level: int = 1
    xp: int = 0
    credits: int = 0
    research_points: int = 0
    best_stage_id: int = 0
    highest_difficulty: int = 0
    total_stage_clears: int = 0
    total_boss_clears: int = 0
    created_at: int = field(default_factory=now_ts)
    updated_at: int = field(default_factory=now_ts)


@dataclass(slots=True)
class HeroProgress:
    user_id: int
    hero_id: str
    mastery_level: int = 1
    mastery_xp: int = 0
    total_wins: int = 0


@dataclass(slots=True)
class GearItem:
    item_id: str
    user_id: int
    slot: str
    grade: str
    level: int
    name: str
    stats: dict[str, float]
    equipped: bool = False
    locked: bool = False
    created_at: int = field(default_factory=now_ts)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "GearItem":
        return cls(
            item_id=str(row["item_id"]),
            user_id=int(row["user_id"]),
            slot=str(row["slot"]),
            grade=str(row["grade"]),
            level=int(row["level"]),
            name=str(row["name"]),
            stats=dict(row.get("stats") or {}),
            equipped=bool(row.get("equipped")),
            locked=bool(row.get("locked")),
            created_at=int(row.get("created_at") or now_ts()),
        )


@dataclass(slots=True)
class RunState:
    user_id: int
    hero_id: str
    chapter: int
    stage: int
    difficulty: int
    hp: int
    max_hp: int
    attack: int
    crit: float
    crit_damage: float
    dodge: float
    lifesteal: float
    shield: int = 0
    ultimate: int = 0
    status: str = "briefing"
    run_upgrades: dict[str, int] = field(default_factory=dict)
    build_tags: list[str] = field(default_factory=list)
    pending_choices: list[str] = field(default_factory=list)
    last_summary: str = ""
    created_at: int = field(default_factory=now_ts)
    updated_at: int = field(default_factory=now_ts)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "RunState":
        allowed = cls.__dataclass_fields__.keys()
        cleaned = {key: value for key, value in payload.items() if key in allowed}
        return cls(**cleaned)


@dataclass(slots=True)
class BattleEnemy:
    id: str
    name: str
    emoji: str
    max_hp: int
    hp: int
    attack: int
    tags: list[str]
    skill_name: str
    phase: int = 1
    shield: int = 0
    burn: int = 0
    bleed: int = 0
    shock: int = 0


@dataclass(slots=True)
class BattleFrame:
    turn: int
    headline: str
    player_hp: int
    player_max_hp: int
    player_shield: int
    ultimate: int
    enemies: list[dict[str, Any]]
    log_lines: list[str]
    objective_progress: str


@dataclass(slots=True)
class BattleResult:
    won: bool
    frames: list[BattleFrame]
    summary: str
    xp: int = 0
    credits: int = 0
    research: int = 0
    mastery_xp: int = 0
    gear: GearItem | None = None
    boss_clear: bool = False
    chapter_clear: bool = False
    ultimate_uses: int = 0
    next_choices: list[str] = field(default_factory=list)
