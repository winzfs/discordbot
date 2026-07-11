from __future__ import annotations

import asyncio
import math
import random
import uuid
from collections import defaultdict
from typing import Any

from .content import (
    CHAPTERS, DAILY_MISSIONS, ENEMIES, GEAR_NAMES, GEAR_SLOTS, GRADE_MULTIPLIER,
    GRADE_ORDER, HEROES, RESEARCH_NODES, UPGRADES, difficulty_def, get_stage,
)
from .models import BattleEnemy, BattleFrame, BattleResult, GearItem, RunState, now_ts
from .repository import WatchpointRepository, account_xp_required, mastery_xp_required


class GameRuleError(RuntimeError):
    pass


class WatchpointService:
    def __init__(self, repository: WatchpointRepository) -> None:
        self.repository = repository
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock_for(self, user_id: int) -> asyncio.Lock:
        return self._locks[user_id]

    def ensure_starter_gear(self, user_id: int) -> None:
        self.repository.get_account(user_id)
        if self.repository.list_gear(user_id):
            return
        starters = (
            GearItem(f"starter-{user_id}-weapon", user_id, "weapon", "D", 0, "신병용 펄스 소총", {"attack_pct": .10}, True),
            GearItem(f"starter-{user_id}-armor", user_id, "armor", "D", 0, "신병용 전투복", {"max_hp_pct": .12}, True),
        )
        for item in starters:
            self.repository.add_gear(item)

    def headquarters(self, user_id: int) -> dict[str, Any]:
        self.ensure_starter_gear(user_id)
        account = self.repository.get_account(user_id)
        progress = self.repository.difficulty_progress(user_id)
        run = self.repository.get_run(user_id)
        gear = self.repository.list_gear(user_id)
        research = self.repository.research_levels(user_id)
        return {
            "account": account,
            "progress": progress,
            "run": run,
            "gear": gear,
            "research": research,
            "power": self.combat_power(user_id),
            "xp_required": account_xp_required(account.level),
        }

    def available_heroes(self, user_id: int) -> list[str]:
        level = self.repository.get_account(user_id).level
        return [hero_id for hero_id, hero in HEROES.items() if level >= hero.unlock_level]

    def available_difficulties(self, user_id: int) -> list[int]:
        progress = self.repository.difficulty_progress(user_id)
        result = [0]
        for difficulty in range(1, 4):
            if progress.get(difficulty - 1, 0) >= 100:
                result.append(difficulty)
        return result

    def available_chapters(self, user_id: int, difficulty: int) -> list[int]:
        progress = self.repository.difficulty_progress(user_id).get(difficulty, 0)
        maximum = min(10, max(1, progress // 10 + 1))
        return list(range(1, maximum + 1))

    def research_effects(self, user_id: int) -> dict[str, float]:
        levels = self.repository.research_levels(user_id)
        effects: dict[str, float] = defaultdict(float)
        for node_id, level in levels.items():
            node = RESEARCH_NODES.get(node_id)
            if node:
                effects[node.effect_key] += node.effect_per_level * level
        return dict(effects)

    def equipped_stats(self, user_id: int) -> dict[str, float]:
        result: dict[str, float] = defaultdict(float)
        for item in self.repository.list_gear(user_id):
            if not item.equipped:
                continue
            grade = GRADE_MULTIPLIER.get(item.grade, 1.0)
            enhance = 1 + item.level * .075
            for key, value in item.stats.items():
                result[key] += float(value) * grade * enhance
        return dict(result)

    def combat_power(self, user_id: int, hero_id: str = "tracer") -> int:
        hero = HEROES.get(hero_id, HEROES["tracer"])
        mastery = self.repository.get_hero_progress(user_id, hero.id)
        research = self.research_effects(user_id)
        gear = self.equipped_stats(user_id)
        attack = hero.attack * (1 + mastery.mastery_level * .012 + research.get("attack_pct", 0) + gear.get("attack_pct", 0))
        hp = hero.max_hp * (1 + mastery.mastery_level * .010 + research.get("max_hp_pct", 0) + gear.get("max_hp_pct", 0))
        utility = 1 + hero.crit * 1.5 + hero.dodge + hero.lifesteal + gear.get("crit", 0)
        return int(attack * 8.5 + hp * .55 * utility)

    def start_run(self, user_id: int, hero_id: str, chapter: int, difficulty: int) -> RunState:
        self.ensure_starter_gear(user_id)
        active = self.repository.get_run(user_id)
        if active and active.status not in {"dead", "complete"}:
            raise GameRuleError("진행 중인 작전이 있습니다")
        if hero_id not in self.available_heroes(user_id):
            raise GameRuleError("아직 해금되지 않은 영웅입니다")
        if difficulty not in self.available_difficulties(user_id):
            raise GameRuleError("이 난이도는 이전 난이도 100스테이지 클리어 후 열립니다")
        if chapter not in self.available_chapters(user_id, difficulty):
            raise GameRuleError("아직 해금되지 않은 챕터입니다")

        hero = HEROES[hero_id]
        account = self.repository.get_account(user_id)
        mastery = self.repository.get_hero_progress(user_id, hero_id)
        research = self.research_effects(user_id)
        gear = self.equipped_stats(user_id)
        progress = self.repository.difficulty_progress(user_id).get(difficulty, 0)
        cleared_in_chapter = max(0, min(10, progress - (chapter - 1) * 10))
        stage = min(10, cleared_in_chapter + 1) if cleared_in_chapter else 1
        hp_scale = 1 + mastery.mastery_level * .010 + research.get("max_hp_pct", 0) + gear.get("max_hp_pct", 0)
        atk_scale = 1 + mastery.mastery_level * .012 + research.get("attack_pct", 0) + gear.get("attack_pct", 0)
        max_hp = max(100, int(hero.max_hp * hp_scale))
        state = RunState(
            user_id=user_id, hero_id=hero_id, chapter=chapter, stage=stage, difficulty=difficulty,
            hp=max_hp, max_hp=max_hp, attack=max(1, int(hero.attack * atk_scale)),
            crit=min(.75, hero.crit + research.get("crit", 0) + gear.get("crit", 0)),
            crit_damage=1.75 + gear.get("crit_damage", 0),
            dodge=min(.60, hero.dodge + research.get("dodge", 0) + gear.get("dodge", 0)),
            lifesteal=min(.65, hero.lifesteal + gear.get("lifesteal", 0)),
            shield=int(research.get("start_shield", 0) + max_hp * gear.get("start_shield_pct", 0)),
            build_tags=list(hero.tags), status="briefing",
        )
        state.last_summary = f"Lv.{account.level} {hero.name} 작전 준비 완료"
        self.repository.save_run(state)
        return state

    def abandon_run(self, user_id: int) -> None:
        self.repository.delete_run(user_id)

    def stage_briefing(self, state: RunState) -> dict[str, Any]:
        stage = get_stage(state.chapter, state.stage)
        return {"stage": stage, "chapter": CHAPTERS[state.chapter], "difficulty": difficulty_def(state.difficulty)}

    def aggregate_upgrade_effects(self, state: RunState) -> dict[str, float]:
        result: dict[str, float] = defaultdict(float)
        for upgrade_id, count in state.run_upgrades.items():
            upgrade = UPGRADES.get(upgrade_id)
            if not upgrade:
                continue
            for key, value in upgrade.effects.items():
                if key in {"cheat_death", "recursive_extra", "third_hit_extra", "ult_stun"}:
                    result[key] = max(result[key], value)
                else:
                    result[key] += value * count
        return dict(result)

    def choose_upgrade(self, user_id: int, upgrade_id: str) -> RunState:
        state = self.repository.get_run(user_id)
        if not state or state.status != "upgrade":
            raise GameRuleError("선택할 강화가 없습니다")
        if upgrade_id not in state.pending_choices:
            raise GameRuleError("현재 선택지에 없는 강화입니다")
        upgrade = UPGRADES[upgrade_id]
        current = int(state.run_upgrades.get(upgrade_id, 0))
        if current >= upgrade.max_stack:
            raise GameRuleError("이미 최대 중첩입니다")
        old_hp_ratio = state.hp / max(1, state.max_hp)
        state.run_upgrades[upgrade_id] = current + 1
        for tag in upgrade.tags:
            if tag not in state.build_tags:
                state.build_tags.append(tag)
        effects = upgrade.effects
        if effects.get("attack_pct"):
            state.attack = max(1, int(state.attack * (1 + effects["attack_pct"])))
        if effects.get("max_hp_pct"):
            state.max_hp = max(100, int(state.max_hp * (1 + effects["max_hp_pct"])))
            state.hp = max(1, min(state.max_hp, int(state.max_hp * old_hp_ratio)))
        if effects.get("heal_pct"):
            state.hp = min(state.max_hp, state.hp + int(state.max_hp * effects["heal_pct"]))
        state.crit = min(.80, state.crit + effects.get("crit", 0))
        state.crit_damage += effects.get("crit_damage", 0)
        state.dodge = min(.65, max(0, state.dodge + effects.get("dodge", 0)))
        state.lifesteal = min(.70, max(0, state.lifesteal + effects.get("lifesteal", 0)))
        state.pending_choices = []
        state.status = "briefing"
        state.last_summary = f"{upgrade.name} 획득 · 다음 스테이지 준비"
        self.repository.save_run(state)
        return state

    def simulate_stage(self, user_id: int) -> BattleResult:
        state = self.repository.get_run(user_id)
        if not state or state.status != "briefing":
            raise GameRuleError("진행할 수 있는 작전이 없습니다")
        stage = get_stage(state.chapter, state.stage)
        chapter = CHAPTERS[state.chapter]
        difficulty = difficulty_def(state.difficulty)
        hero = HEROES[state.hero_id]
        research = self.research_effects(user_id)
        effects = self.aggregate_upgrade_effects(state)
        effects["boss_damage_pct"] = effects.get("boss_damage_pct", 0) + research.get("boss_damage_pct", 0)
        effects["status_damage_pct"] = effects.get("status_damage_pct", 0) + research.get("status_damage_pct", 0)
        effects["ult_charge_pct"] = effects.get("ult_charge_pct", 0) + research.get("ult_charge_pct", 0)
        healing_bonus = 1 + research.get("healing_pct", 0)
        if state.difficulty >= 2:
            healing_bonus *= .72

        state.status = "running"
        starting_hp = state.hp
        frames: list[BattleFrame] = []
        logs: list[str] = [f"{chapter.emoji} {stage.name} 작전 개시"]
        total_turn = 0
        attack_count = 0
        ult_uses = 0
        cheat_death = effects.get("cheat_death", 0) > 0
        stun_next = False
        won = True

        for wave in range(1, stage.waves + 1):
            enemies = self._spawn_wave(stage, state.difficulty, wave)
            logs.append(f"WAVE {wave}/{stage.waves} · 적 {len(enemies)}기 탐지")
            while any(enemy.hp > 0 for enemy in enemies):
                total_turn += 1
                if total_turn > stage.target_turns + stage.waves * 8:
                    won = False
                    logs.append("제한 시간 초과 · 작전 실패")
                    break
                target = next(enemy for enemy in enemies if enemy.hp > 0)
                attack_count += 1
                multiplier = 1 + effects.get("attack_pct", 0)
                if state.hp <= state.max_hp * .40:
                    multiplier += effects.get("low_hp_attack_pct", 0)
                if state.shield > 0:
                    multiplier += effects.get("shield_damage_pct", 0)
                if "boss" in target.tags or "elite" in target.tags:
                    multiplier += effects.get("boss_damage_pct", 0)
                damage = max(1, int(state.attack * multiplier * random.uniform(.90, 1.10)))
                critical = random.random() < state.crit
                if critical:
                    damage = int(damage * state.crit_damage)
                if target.hp <= target.max_hp * .25:
                    damage = int(damage * (1 + effects.get("execute_pct", 0)))
                    if hero.id in {"reaper", "genji"}:
                        damage = int(damage * 1.18)
                dealt = self._damage_enemy(target, damage)
                logs.append(f"{'💥 ' if critical else ''}{hero.name} → {target.name} {dealt:,} 피해")
                if critical and hero.id == "kiriko":
                    state.hp = min(state.max_hp, state.hp + int(state.max_hp * .035 * healing_bonus))
                heal = int(dealt * state.lifesteal * healing_bonus)
                if hero.id == "moira":
                    heal += int(dealt * .035 * healing_bonus)
                state.hp = min(state.max_hp, state.hp + heal)

                status_multiplier = 1 + effects.get("status_damage_pct", 0)
                for key, icon in (("shock_damage", "⚡"), ("burn_damage", "🔥"), ("bleed_damage", "🩸")):
                    if effects.get(key):
                        dot = max(1, int(state.attack * effects[key] * status_multiplier))
                        self._damage_enemy(target, dot)
                        logs.append(f"{icon} {target.name} 추가 피해 {dot:,}")
                if hero.id == "ashe" and attack_count == 1:
                    self._damage_enemy(target, int(state.attack * .45))
                extra_chance = effects.get("extra_attack", 0)
                if hero.id in {"tracer", "soldier76"}:
                    extra_chance += .13
                if random.random() < min(.70, extra_chance):
                    extra = int(state.attack * .72)
                    self._damage_enemy(target, extra)
                    logs.append(f"🔁 추가 사격 {extra:,}")
                if effects.get("third_hit_extra") and attack_count % 3 == 0:
                    self._damage_enemy(target, int(state.attack * .85))
                    logs.append("⏱️ 세 번째 공격 연계")

                charge = int((18 + (8 if critical else 0)) * (1 + effects.get("ult_charge_pct", 0)))
                state.ultimate = min(100, state.ultimate + charge)
                if state.ultimate >= 100 and any(enemy.hp > 0 for enemy in enemies):
                    ult_uses += 1
                    state.ultimate = 0
                    stun_next = self._use_ultimate(state, hero, enemies, effects, logs)

                alive_before = sum(enemy.hp > 0 for enemy in enemies)
                if target.hp <= 0:
                    logs.append(f"☠️ {target.name} 제거")
                    kill_heal = effects.get("kill_heal_pct", 0)
                    if hero.id == "reaper": kill_heal += .04
                    state.hp = min(state.max_hp, state.hp + int(state.max_hp * kill_heal * healing_bonus))
                    burst = effects.get("kill_burst", 0)
                    if burst:
                        for other in enemies:
                            if other.hp > 0:
                                self._damage_enemy(other, int(state.attack * burst))

                if any(enemy.hp > 0 for enemy in enemies):
                    if stun_next:
                        logs.append("🌀 적 공격 패턴 봉쇄")
                        stun_next = False
                    else:
                        state.hp, state.shield = self._enemy_phase(state, enemies, difficulty, effects, logs)
                if state.hp <= 0:
                    if cheat_death:
                        cheat_death = False
                        state.hp = max(1, int(state.max_hp * .30))
                        logs.append("🪽 비상 귀환 프로토콜 발동")
                    else:
                        won = False
                        logs.append("작전 요원 전투불능")
                        break

                frames.append(self._frame(total_turn, logs[-1], state, enemies, stage, wave))
                logs = logs[-8:]
            if not won:
                break
            if wave < stage.waves:
                recovery = int(state.max_hp * (.08 + (.04 if state.stage in {5, 8} else 0)) * healing_bonus)
                state.hp = min(state.max_hp, state.hp + recovery)
                state.shield += int(state.max_hp * .04)
                logs.append(f"🧰 웨이브 정비 · 체력 {recovery:,} 회복")

        if not frames:
            frames.append(self._frame(total_turn, logs[-1], state, [], stage, stage.waves))
        if not won:
            mastery = max(15, stage.mastery_xp // 3)
            self.repository.grant_mastery(user_id, hero.id, mastery, False)
            self.repository.delete_run(user_id)
            return BattleResult(False, frames, f"{stage.name} 실패 · 최고 체력 손실 {starting_hp - max(0, state.hp):,}", mastery_xp=mastery, ultimate_uses=ult_uses)

        reward_scale = float(difficulty["reward"])
        xp = int(stage.xp_reward * reward_scale)
        credits = int(stage.credit_reward * reward_scale)
        research_reward = int(stage.research_reward * reward_scale)
        mastery_xp = 40 + stage.stage * 4 + stage.chapter * 3
        boss = stage.objective == "boss"
        self.repository.grant_rewards(user_id, xp, credits, research_reward)
        self.repository.grant_mastery(user_id, hero.id, mastery_xp, True)
        self.repository.record_clear(user_id, state.difficulty, stage.global_id, boss)
        self.repository.add_daily(user_id, "stage_clear", 1)
        if ult_uses:
            self.repository.add_daily(user_id, "ultimate_use", ult_uses)

        gear = self._roll_gear(state, research, guaranteed=boss)
        if gear:
            self.repository.add_gear(gear)

        chapter_clear = state.stage >= 10
        choices: list[str] = []
        if chapter_clear:
            self.repository.delete_run(user_id)
            state.status = "complete"
        else:
            state.stage += 1
            state.hp = min(state.max_hp, state.hp + int(state.max_hp * (.45 if boss else .24)))
            state.shield = 0
            choices = self._roll_upgrade_choices(state, research)
            state.pending_choices = choices
            state.status = "upgrade"
            state.last_summary = f"{stage.name} 클리어 · 강화 선택 대기"
            self.repository.save_run(state)
        summary = f"{stage.name} 클리어 · XP {xp:,} · 크레딧 {credits:,} · 연구 {research_reward}"
        return BattleResult(True, frames, summary, xp, credits, research_reward, mastery_xp, gear, boss, chapter_clear, ult_uses, choices)

    def _spawn_wave(self, stage: Any, difficulty: int, wave: int) -> list[BattleEnemy]:
        diff = difficulty_def(difficulty)
        count = 1 if stage.objective == "boss" else 2 if wave < stage.waves else min(3, len(stage.enemy_ids))
        selected = list(stage.enemy_ids)
        random.shuffle(selected)
        enemies: list[BattleEnemy] = []
        stage_scale = 1 + (stage.stage - 1) * .045
        for enemy_id in selected[:count]:
            definition = ENEMIES[enemy_id]
            hp = int(definition.max_hp * float(diff["hp"]) * stage_scale * (.74 if stage.objective != "boss" else .82))
            attack = int(definition.attack * float(diff["atk"]) * stage_scale * (.58 if stage.objective != "boss" else .64))
            enemies.append(BattleEnemy(definition.id, definition.name, definition.emoji, hp, hp, attack, list(definition.tags), definition.skill_name))
        return enemies

    @staticmethod
    def _damage_enemy(enemy: BattleEnemy, damage: int) -> int:
        actual = max(0, min(enemy.hp, int(damage)))
        enemy.hp -= actual
        return actual

    def _use_ultimate(self, state: RunState, hero: Any, enemies: list[BattleEnemy], effects: dict[str, float], logs: list[str]) -> bool:
        power = hero.ultimate_power * (1 + effects.get("ultimate_power_pct", 0))
        alive = [enemy for enemy in enemies if enemy.hp > 0]
        logs.append(f"🌟 {hero.ultimate_name} 발동!")
        if hero.ultimate_kind in {"aoe", "control", "debuff", "drain", "summon", "berserk"}:
            for enemy in alive:
                self._damage_enemy(enemy, int(state.attack * power))
        else:
            target = alive[0]
            self._damage_enemy(target, int(state.attack * power))
        if hero.ultimate_kind in {"tempo", "drain"}:
            state.hp = min(state.max_hp, state.hp + int(state.max_hp * .12))
        if hero.id == "reinhardt" or effects.get("ult_stun"):
            return True
        return False

    def _enemy_phase(self, state: RunState, enemies: list[BattleEnemy], difficulty: dict[str, object], effects: dict[str, float], logs: list[str]) -> tuple[int, int]:
        hp, shield = state.hp, state.shield
        for enemy in enemies:
            if enemy.hp <= 0:
                continue
            if "boss" in enemy.tags:
                ratio = enemy.hp / max(1, enemy.max_hp)
                phase = 3 if ratio <= .33 else 2 if ratio <= .66 else 1
                if phase > enemy.phase:
                    enemy.phase = phase
                    enemy.attack = int(enemy.attack * 1.18)
                    logs.append(f"🚨 {enemy.name} 페이즈 {phase} 돌입")
            if "support" in enemy.tags and random.random() < .30:
                target = max(enemies, key=lambda item: item.max_hp - item.hp)
                heal = int(target.max_hp * .08)
                target.hp = min(target.max_hp, target.hp + heal)
                logs.append(f"🧰 {enemy.name} 수리 {heal:,}")
                continue
            accuracy = .90 + (.04 if "tracking" in enemy.tags else 0) - effects.get("accuracy", 0) * .20
            if random.random() > accuracy or random.random() < state.dodge:
                logs.append(f"🌀 {enemy.name} 공격 회피")
                counter = effects.get("dodge_counter", 0)
                if counter:
                    self._damage_enemy(enemy, int(state.attack * counter))
                continue
            damage = int(enemy.attack * random.uniform(.90, 1.10))
            if "burst" in enemy.tags and random.random() < .25:
                damage = int(damage * 1.55)
                logs.append(f"💢 {enemy.skill_name}")
            absorbed = min(shield, damage)
            shield -= absorbed
            hp -= damage - absorbed
            logs.append(f"🔻 {enemy.name} → {damage:,} 피해")
            if hp <= 0:
                break
        return hp, shield

    @staticmethod
    def _objective_progress(stage: Any, wave: int, turn: int) -> str:
        if stage.objective == "escort":
            return f"호위 {min(100, int((wave - 1 + .5) / stage.waves * 100))}%"
        if stage.objective == "defense":
            return f"방어 유지 {max(0, stage.target_turns - turn)}턴"
        if stage.objective == "survival":
            return f"생존 {turn}/{stage.target_turns}턴"
        return f"웨이브 {wave}/{stage.waves}"

    def _frame(self, turn: int, headline: str, state: RunState, enemies: list[BattleEnemy], stage: Any, wave: int) -> BattleFrame:
        return BattleFrame(
            turn, headline, max(0, state.hp), state.max_hp, max(0, state.shield), state.ultimate,
            [{"name": e.name, "emoji": e.emoji, "hp": max(0, e.hp), "max_hp": e.max_hp, "phase": e.phase} for e in enemies],
            [], self._objective_progress(stage, wave, turn),
        )

    def _roll_upgrade_choices(self, state: RunState, research: dict[str, float]) -> list[str]:
        available = []
        for upgrade in UPGRADES.values():
            if upgrade.hero_id and upgrade.hero_id != state.hero_id:
                continue
            if state.run_upgrades.get(upgrade.id, 0) >= upgrade.max_stack:
                continue
            if upgrade.requires_any and not any(tag in state.build_tags for tag in upgrade.requires_any):
                continue
            available.append(upgrade)
        quality = research.get("upgrade_quality", 0)
        weights = {"일반": 1.0 - min(.45, quality), "희귀": .58 + quality, "영웅": .25 + quality * .8, "전설": .055 + quality * .35}
        selected: list[str] = []
        while available and len(selected) < 3:
            pick = random.choices(available, weights=[weights.get(item.rarity, .2) for item in available], k=1)[0]
            selected.append(pick.id)
            available.remove(pick)
        return selected

    def _roll_gear(self, state: RunState, research: dict[str, float], guaranteed: bool = False) -> GearItem | None:
        chance = .34 + research.get("gear_drop_pct", 0)
        if not guaranteed and random.random() > chance:
            return None
        quality = research.get("gear_quality", 0) + state.difficulty * .08 + state.chapter * .012
        weights = [42, 30, 17, 8, 2.5, .5]
        for index in range(len(weights)):
            weights[index] *= max(.15, 1 + quality * (index - 1.4))
        grade = random.choices(GRADE_ORDER, weights=weights, k=1)[0]
        slot = random.choice([entry[0] for entry in GEAR_SLOTS])
        name = random.choice(GEAR_NAMES[slot])
        base = .045 + GRADE_ORDER.index(grade) * .018 + state.chapter * .002
        stat_by_slot = {
            "weapon": {"attack_pct": base}, "helmet": {"crit": base * .48, "dodge": base * .22},
            "armor": {"max_hp_pct": base * 1.3}, "module": {"ult_charge_pct": base, "status_damage_pct": base * .7},
            "core": {"attack_pct": base * .55, "max_hp_pct": base * .55},
        }
        return GearItem(uuid.uuid4().hex, state.user_id, slot, grade, 0, name, stat_by_slot[slot], False, False, now_ts())

    def list_gear(self, user_id: int) -> list[GearItem]:
        self.ensure_starter_gear(user_id)
        return self.repository.list_gear(user_id)

    @staticmethod
    def gear_enhance_cost(item: GearItem) -> int:
        return int((120 + item.level * 65) * GRADE_MULTIPLIER.get(item.grade, 1.0))

    def equip_gear(self, user_id: int, item_id: str) -> GearItem:
        return self.repository.equip_gear(user_id, item_id)

    def enhance_gear(self, user_id: int, item_id: str) -> GearItem:
        item = self.repository.get_gear(user_id, item_id)
        if not item:
            raise GameRuleError("장비를 찾을 수 없습니다")
        try:
            saved = self.repository.enhance_gear(user_id, item_id, self.gear_enhance_cost(item))
        except ValueError as exc:
            raise GameRuleError(str(exc)) from exc
        self.repository.add_daily(user_id, "gear_enhance", 1)
        return saved

    @staticmethod
    def research_cost(node_id: str, level: int) -> int:
        node = RESEARCH_NODES[node_id]
        return max(1, int(node.base_cost * (node.cost_growth ** level)))

    def upgrade_research(self, user_id: int, node_id: str) -> tuple[int, int]:
        node = RESEARCH_NODES.get(node_id)
        if not node:
            raise GameRuleError("연구 항목을 찾을 수 없습니다")
        level = self.repository.research_levels(user_id).get(node_id, 0)
        cost = self.research_cost(node_id, level)
        try:
            new_level = self.repository.buy_research(user_id, node_id, cost, node.max_level)
        except ValueError as exc:
            raise GameRuleError(str(exc)) from exc
        self.repository.add_daily(user_id, "research_upgrade", 1)
        return new_level, cost

    def daily_status(self, user_id: int) -> tuple[dict[str, int], bool]:
        return self.repository.daily_status(user_id)

    def claim_daily(self, user_id: int) -> bool:
        return self.repository.claim_daily(user_id, DAILY_MISSIONS)

    def ranking(self, user_id: int) -> list[dict[str, int]]:
        self.repository.add_daily(user_id, "ranking_view", 1)
        return self.repository.ranking(10)
