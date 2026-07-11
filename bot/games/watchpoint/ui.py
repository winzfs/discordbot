from __future__ import annotations

import asyncio
import math
from typing import Any

import discord

from .content import (
    CHAPTERS, DAILY_MISSIONS, GEAR_SLOTS, GRADE_EMOJI, HEROES, RESEARCH_NODES,
    UPGRADES, difficulty_def, get_stage,
)
from .models import BattleFrame, BattleResult, GearItem, RunState
from .repository import account_xp_required, mastery_xp_required
from .service import GameRuleError, WatchpointService

DIVIDER = "━━━━━━━━━━━━━━━━"


def bar(current: int, maximum: int, filled: str = "🟩", empty: str = "⬛", width: int = 10) -> str:
    if maximum <= 0:
        return empty * width
    count = max(0, min(width, round(width * current / maximum)))
    return filled * count + empty * (width - count)


def stage_label(global_id: int) -> str:
    if global_id <= 0:
        return "미진행"
    return f"{(global_id - 1) // 10 + 1}-{(global_id - 1) % 10 + 1}"


def slot_label(slot: str) -> str:
    for key, name, emoji in GEAR_SLOTS:
        if key == slot:
            return f"{emoji} {name}"
    return slot


def gear_stats(item: GearItem) -> str:
    names = {
        "attack_pct": "공격력", "max_hp_pct": "최대 체력", "crit": "치명타",
        "dodge": "회피", "lifesteal": "흡혈", "ult_charge_pct": "궁 충전",
        "status_damage_pct": "상태 피해", "start_shield_pct": "시작 방벽",
    }
    lines = []
    grade_scale = {"D": 1.0, "C": 1.26, "B": 1.62, "A": 2.08, "S": 2.72, "U": 3.55}.get(item.grade, 1.0)
    enhance = 1 + item.level * .075
    for key, value in item.stats.items():
        final = float(value) * grade_scale * enhance
        lines.append(f"{names.get(key, key)} +{final * 100:.1f}%")
    return "\n".join(lines) or "옵션 없음"


def headquarters_embed(user: discord.abc.User, snapshot: dict[str, Any]) -> discord.Embed:
    account = snapshot["account"]
    progress = snapshot["progress"]
    run = snapshot["run"]
    equipped = [item for item in snapshot["gear"] if item.equipped]
    embed = discord.Embed(title="🛰️ 워치포인트 프로토콜", color=0x38BDF8)
    embed.description = (
        f"{user.mention} 요원의 작전본부\n{DIVIDER}\n"
        "100개 스테이지를 돌파하고 영웅·장비·연구를 성장시키세요."
    )
    embed.add_field(
        name=f"계정 Lv.{account.level}",
        value=f"XP {bar(account.xp, snapshot['xp_required'], '🟦')}  {account.xp:,}/{snapshot['xp_required']:,}\n전투력 **{snapshot['power']:,}**",
        inline=False,
    )
    embed.add_field(name="자원", value=f"💳 {account.credits:,} 크레딧\n🧪 {account.research_points:,} 연구 데이터", inline=True)
    embed.add_field(name="진행", value=f"최고 **{stage_label(account.best_stage_id)}**\n보스 **{account.total_boss_clears}회**", inline=True)
    embed.add_field(name="장비", value=f"장착 {len(equipped)}/5\n보유 {len(snapshot['gear'])}/50", inline=True)
    diff_lines = []
    for difficulty in range(4):
        info = difficulty_def(difficulty)
        diff_lines.append(f"{info['emoji']} {info['name']}: {stage_label(progress.get(difficulty, 0))}")
    embed.add_field(name="난이도 진행", value="\n".join(diff_lines), inline=False)
    if run:
        stage = get_stage(run.chapter, run.stage)
        embed.add_field(name="진행 중 작전", value=f"{HEROES[run.hero_id].emoji} {HEROES[run.hero_id].name} · {stage.name}\nHP {run.hp:,}/{run.max_hp:,}", inline=False)
    embed.set_footer(text="명령어는 /로그라이크 하나 · 이후 진행은 버튼으로 조작")
    return embed


def setup_embed(view: "MissionSetupView") -> discord.Embed:
    hero = HEROES[view.hero_id]
    chapter = CHAPTERS[view.chapter]
    difficulty = difficulty_def(view.difficulty)
    progress = view.service.repository.get_hero_progress(view.owner_id, hero.id)
    embed = discord.Embed(title="🎯 작전 편성", color=0x5865F2)
    embed.description = f"영웅, 난이도, 투입 지역을 선택하세요.\n{DIVIDER}"
    embed.add_field(name="영웅", value=f"{hero.emoji} **{hero.name}** · {hero.role}\n{hero.description}\n숙련도 Lv.{progress.mastery_level}", inline=False)
    embed.add_field(name="난이도", value=f"{difficulty['emoji']} **{difficulty['name']}**\n{difficulty['rule']}", inline=True)
    embed.add_field(name="챕터", value=f"{chapter.emoji} **{chapter.number}. {chapter.name}**\n기믹: {chapter.mechanic}", inline=True)
    embed.add_field(name="예상 전투력", value=f"**{view.service.combat_power(view.owner_id, hero.id):,}**", inline=False)
    embed.set_footer(text="각 챕터는 10개 스테이지 · 5/8 정예 · 10 보스")
    return embed


def briefing_embed(state: RunState, service: WatchpointService) -> discord.Embed:
    info = service.stage_briefing(state)
    stage, chapter, difficulty = info["stage"], info["chapter"], info["difficulty"]
    hero = HEROES[state.hero_id]
    embed = discord.Embed(title=f"{chapter.emoji} {stage.name}", color=0xF59E0B if stage.objective == "boss" else 0x38BDF8)
    embed.description = f"{difficulty['emoji']} {difficulty['name']} · {stage.objective_label} 작전\n{DIVIDER}\n{chapter.summary}"
    embed.add_field(name="작전 목표", value=f"**{stage.objective_label}** · {stage.waves} 웨이브\n권장 제한 {stage.target_turns}턴", inline=True)
    embed.add_field(name="전장 기믹", value=f"**{stage.modifier_label}**\n{chapter.mechanic}", inline=True)
    embed.add_field(name=f"{hero.emoji} {hero.name}", value=f"HP {bar(state.hp, state.max_hp)} {state.hp:,}/{state.max_hp:,}\n공격 {state.attack:,} · 치명 {state.crit * 100:.0f}% · 회피 {state.dodge * 100:.0f}%", inline=False)
    if state.run_upgrades:
        names = [f"{UPGRADES[key].name} ×{count}" for key, count in state.run_upgrades.items() if key in UPGRADES]
        embed.add_field(name="현재 빌드", value=" · ".join(names[:8]), inline=False)
    embed.set_footer(text="전투는 자동 진행되며 궁극기는 100%에 자동 발동")
    return embed


def battle_frame_embed(state: RunState, frame: BattleFrame) -> discord.Embed:
    hero = HEROES[state.hero_id]
    embed = discord.Embed(title=f"⚔️ 전투 진행 · TURN {frame.turn}", color=0xEF4444)
    enemy_lines = []
    for enemy in frame.enemies:
        hp = int(enemy["hp"])
        maximum = int(enemy["max_hp"])
        phase = f" · P{enemy['phase']}" if int(enemy.get("phase", 1)) > 1 else ""
        enemy_lines.append(f"{enemy['emoji']} **{enemy['name']}**{phase}\n{bar(hp, maximum, '🟥')} {hp:,}/{maximum:,}")
    embed.description = "\n\n".join(enemy_lines) or "적 전멸"
    embed.add_field(name="전술 상황", value=f"**{frame.headline}**\n{frame.objective_progress}", inline=False)
    embed.add_field(name=f"{hero.emoji} {hero.name}", value=f"{bar(frame.player_hp, frame.player_max_hp)} {frame.player_hp:,}/{frame.player_max_hp:,}\n🛡️ {frame.player_shield:,} · 🌟 {bar(frame.ultimate, 100, '🟨')} {frame.ultimate}%", inline=False)
    return embed


def result_embed(previous: RunState, result: BattleResult) -> discord.Embed:
    color = 0x57F287 if result.won else 0x7F1D1D
    title = "✅ 작전 성공" if result.won else "☠️ 작전 실패"
    embed = discord.Embed(title=title, description=result.summary, color=color)
    if result.won:
        embed.add_field(name="작전 보상", value=f"⭐ XP {result.xp:,}\n💳 크레딧 {result.credits:,}\n🧪 연구 {result.research}", inline=True)
        embed.add_field(name="영웅 숙련", value=f"+{result.mastery_xp} XP\n궁극기 {result.ultimate_uses}회", inline=True)
        if result.gear:
            item = result.gear
            embed.add_field(name="장비 획득", value=f"{GRADE_EMOJI.get(item.grade, '')} **[{item.grade}] {item.name}**\n{slot_label(item.slot)}\n{gear_stats(item)}", inline=False)
        if result.chapter_clear:
            embed.add_field(name="챕터 완료", value="다음 챕터가 해금되었습니다. 작전본부에서 새 작전을 편성하세요.", inline=False)
    else:
        embed.add_field(name="정비 지침", value="장비 강화와 연구를 진행하거나 다른 빌드를 선택해 재도전하세요.", inline=False)
    return embed


def gear_embed(user: discord.abc.User, service: WatchpointService, selected: GearItem | None = None) -> discord.Embed:
    account = service.repository.get_account(user.id)
    gear = service.list_gear(user.id)
    equipped = [item for item in gear if item.equipped]
    embed = discord.Embed(title="🔧 장비 격납고", color=0xF59E0B)
    embed.description = f"💳 {account.credits:,} 크레딧 · 보유 {len(gear)}/50\n{DIVIDER}"
    if equipped:
        embed.add_field(name="장착 장비", value="\n".join(f"{slot_label(item.slot)} · {GRADE_EMOJI.get(item.grade, '')} [{item.grade}] {item.name} +{item.level}" for item in equipped), inline=False)
    if selected:
        cost = service.gear_enhance_cost(selected)
        embed.add_field(name="선택 장비", value=f"{GRADE_EMOJI.get(selected.grade, '')} **[{selected.grade}] {selected.name} +{selected.level}**\n{slot_label(selected.slot)}\n{gear_stats(selected)}\n강화 비용: {cost:,} 크레딧", inline=False)
    else:
        embed.add_field(name="안내", value="아래 목록에서 장비를 선택하세요. 같은 부위는 하나만 장착됩니다.", inline=False)
    embed.set_footer(text="등급 D → C → B → A → S → U · 강화 최대 +30")
    return embed


def research_embed(user: discord.abc.User, service: WatchpointService, selected_id: str | None = None) -> discord.Embed:
    account = service.repository.get_account(user.id)
    levels = service.repository.research_levels(user.id)
    embed = discord.Embed(title="🧪 워치포인트 연구소", color=0xA855F7)
    embed.description = f"보유 연구 데이터 **{account.research_points:,}**\n{DIVIDER}"
    branch_lines: dict[str, list[str]] = {"화력": [], "생존": [], "전술": []}
    for node_id, node in RESEARCH_NODES.items():
        level = levels.get(node_id, 0)
        branch_lines[node.branch].append(f"{node.name} Lv.{level}/{node.max_level}")
    for branch, lines in branch_lines.items():
        embed.add_field(name=branch, value="\n".join(lines), inline=True)
    if selected_id and selected_id in RESEARCH_NODES:
        node = RESEARCH_NODES[selected_id]
        level = levels.get(selected_id, 0)
        cost = service.research_cost(selected_id, level) if level < node.max_level else 0
        embed.add_field(name="선택 연구", value=f"**{node.name}** Lv.{level}/{node.max_level}\n{node.description}\n다음 비용: {cost if cost else 'MAX'}", inline=False)
    return embed


def daily_embed(user: discord.abc.User, service: WatchpointService) -> discord.Embed:
    progress, claimed = service.daily_status(user.id)
    lines = []
    complete = True
    for key, label, target in DAILY_MISSIONS:
        current = min(target, int(progress.get(key, 0)))
        done = current >= target
        complete = complete and done
        lines.append(f"{'✅' if done else '⬜'} {label} · {current}/{target}")
    embed = discord.Embed(title="📋 일일 작전 지시", color=0x57F287 if complete else 0x5865F2)
    embed.description = "\n".join(lines)
    embed.add_field(name="전체 완료 보상", value="💳 1,000 크레딧 · 🧪 연구 데이터 10", inline=False)
    embed.set_footer(text="수령 완료" if claimed else "매일 00:00 KST 초기화")
    return embed


def ranking_embed(rows: list[dict[str, int]]) -> discord.Embed:
    embed = discord.Embed(title="🏆 워치포인트 작전 랭킹", color=0xFACC15)
    medals = ("🥇", "🥈", "🥉")
    lines = []
    for index, row in enumerate(rows, 1):
        prefix = medals[index - 1] if index <= 3 else f"`{index:02d}`"
        lines.append(f"{prefix} <@{row['user_id']}> · 전설도 {row['highest_difficulty']} · 최고 {stage_label(row['best_stage_id'])} · Lv.{row['level']} · 보스 {row['total_boss_clears']}")
    embed.description = "\n".join(lines) or "아직 기록이 없습니다."
    return embed


async def safe_error(interaction: discord.Interaction, error: Exception) -> None:
    message = str(error) if isinstance(error, GameRuleError) else f"작업 실패: {type(error).__name__}"
    if interaction.response.is_done():
        await interaction.followup.send(f"❌ {message}", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {message}", ephemeral=True)


async def show_headquarters(interaction: discord.Interaction, service: WatchpointService, owner_id: int) -> None:
    snapshot = await asyncio.to_thread(service.headquarters, owner_id)
    embed = headquarters_embed(interaction.user, snapshot)
    view = HeadquartersView(service, owner_id, bool(snapshot["run"]))
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)


class OwnedView(discord.ui.View):
    def __init__(self, service: WatchpointService, owner_id: int, *, timeout: float = 900) -> None:
        super().__init__(timeout=timeout)
        self.service = service
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("이 작전 패널은 다른 요원이 조작할 수 없습니다.", ephemeral=True)
        return False


class HeadquartersView(OwnedView):
    def __init__(self, service: WatchpointService, owner_id: int, has_run: bool) -> None:
        super().__init__(service, owner_id)
        self.new_run.disabled = has_run
        self.continue_run.disabled = not has_run

    @discord.ui.button(label="새 작전", emoji="🎯", style=discord.ButtonStyle.primary, row=0)
    async def new_run(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        view = MissionSetupView(self.service, self.owner_id)
        await interaction.response.edit_message(embed=setup_embed(view), view=view)

    @discord.ui.button(label="작전 계속", emoji="⚔️", style=discord.ButtonStyle.success, row=0)
    async def continue_run(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = await asyncio.to_thread(self.service.repository.get_run, self.owner_id)
        if not state:
            await safe_error(interaction, GameRuleError("진행 중인 작전이 없습니다"))
            return
        await interaction.response.edit_message(embed=briefing_embed(state, self.service), view=RunView(self.service, self.owner_id))

    @discord.ui.button(label="장비", emoji="🔧", style=discord.ButtonStyle.secondary, row=1)
    async def gear(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        view = GearView(self.service, self.owner_id)
        await interaction.response.edit_message(embed=gear_embed(interaction.user, self.service), view=view)

    @discord.ui.button(label="연구소", emoji="🧪", style=discord.ButtonStyle.secondary, row=1)
    async def research(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        view = ResearchView(self.service, self.owner_id)
        await interaction.response.edit_message(embed=research_embed(interaction.user, self.service), view=view)

    @discord.ui.button(label="일일 미션", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def daily(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=daily_embed(interaction.user, self.service), view=DailyView(self.service, self.owner_id))

    @discord.ui.button(label="랭킹", emoji="🏆", style=discord.ButtonStyle.secondary, row=2)
    async def ranking(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        rows = await asyncio.to_thread(self.service.ranking, self.owner_id)
        await interaction.followup.send(embed=ranking_embed(rows), ephemeral=False)


class HeroSelect(discord.ui.Select):
    def __init__(self, parent: "MissionSetupView") -> None:
        self.parent_view = parent
        options = [discord.SelectOption(label=hero.name, value=hero_id, emoji=hero.emoji, description=f"{hero.role} · {hero.description}"[:100]) for hero_id, hero in HEROES.items() if hero_id in parent.service.available_heroes(parent.owner_id)]
        super().__init__(placeholder="영웅 선택", options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.hero_id = self.values[0]
        await interaction.response.edit_message(embed=setup_embed(self.parent_view), view=self.parent_view)


class DifficultySelect(discord.ui.Select):
    def __init__(self, parent: "MissionSetupView") -> None:
        self.parent_view = parent
        options = []
        for value in parent.service.available_difficulties(parent.owner_id):
            info = difficulty_def(value)
            options.append(discord.SelectOption(label=str(info["name"]), value=str(value), emoji=str(info["emoji"]), description=str(info["rule"])[:100]))
        super().__init__(placeholder="난이도 선택", options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.difficulty = int(self.values[0])
        chapters = self.parent_view.service.available_chapters(self.parent_view.owner_id, self.parent_view.difficulty)
        if self.parent_view.chapter not in chapters:
            self.parent_view.chapter = chapters[-1]
        self.parent_view.rebuild()
        await interaction.response.edit_message(embed=setup_embed(self.parent_view), view=self.parent_view)


class ChapterSelect(discord.ui.Select):
    def __init__(self, parent: "MissionSetupView") -> None:
        self.parent_view = parent
        options = [discord.SelectOption(label=f"{chapter}. {CHAPTERS[chapter].name}", value=str(chapter), emoji=CHAPTERS[chapter].emoji, description=CHAPTERS[chapter].mechanic) for chapter in parent.service.available_chapters(parent.owner_id, parent.difficulty)]
        super().__init__(placeholder="챕터 선택", options=options, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.chapter = int(self.values[0])
        await interaction.response.edit_message(embed=setup_embed(self.parent_view), view=self.parent_view)


class MissionSetupView(OwnedView):
    def __init__(self, service: WatchpointService, owner_id: int) -> None:
        super().__init__(service, owner_id)
        self.hero_id = service.available_heroes(owner_id)[0]
        self.difficulty = service.available_difficulties(owner_id)[-1]
        self.chapter = service.available_chapters(owner_id, self.difficulty)[-1]
        self.rebuild()

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(HeroSelect(self))
        self.add_item(DifficultySelect(self))
        self.add_item(ChapterSelect(self))
        start = discord.ui.Button(label="작전 시작", emoji="🚀", style=discord.ButtonStyle.success, row=3)
        start.callback = self.start
        self.add_item(start)
        back = discord.ui.Button(label="작전본부", emoji="🏠", style=discord.ButtonStyle.secondary, row=3)
        back.callback = self.back
        self.add_item(back)

    async def start(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            state = await asyncio.to_thread(self.service.start_run, self.owner_id, self.hero_id, self.chapter, self.difficulty)
        except Exception as exc:
            await safe_error(interaction, exc)
            return
        await interaction.edit_original_response(embed=briefing_embed(state, self.service), view=RunView(self.service, self.owner_id))

    async def back(self, interaction: discord.Interaction) -> None:
        await show_headquarters(interaction, self.service, self.owner_id)


class RunView(OwnedView):
    @discord.ui.button(label="전투 시작", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def battle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        async with self.service.lock_for(self.owner_id):
            state = await asyncio.to_thread(self.service.repository.get_run, self.owner_id)
            if not state:
                await safe_error(interaction, GameRuleError("진행 중인 작전이 없습니다"))
                return
            previous = RunState.from_json(state.to_json())
            try:
                result = await asyncio.to_thread(self.service.simulate_stage, self.owner_id)
            except Exception as exc:
                await safe_error(interaction, exc)
                return
            for index in sample_indexes(len(result.frames), 9):
                await interaction.edit_original_response(embed=battle_frame_embed(previous, result.frames[index]), view=None)
                await asyncio.sleep(.42)
            if result.won and result.next_choices:
                view: discord.ui.View = UpgradeChoiceView(self.service, self.owner_id, result.next_choices)
            else:
                view = PostBattleView(self.service, self.owner_id)
            await interaction.edit_original_response(embed=result_embed(previous, result), view=view)

    @discord.ui.button(label="작전 포기", emoji="🏳️", style=discord.ButtonStyle.secondary)
    async def abandon(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await asyncio.to_thread(self.service.abandon_run, self.owner_id)
        await show_headquarters(interaction, self.service, self.owner_id)

    @discord.ui.button(label="작전본부", emoji="🏠", style=discord.ButtonStyle.secondary)
    async def headquarters(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await show_headquarters(interaction, self.service, self.owner_id)


class UpgradeChoiceView(OwnedView):
    def __init__(self, service: WatchpointService, owner_id: int, choices: list[str]) -> None:
        super().__init__(service, owner_id)
        for index, upgrade_id in enumerate(choices):
            upgrade = UPGRADES[upgrade_id]
            button = discord.ui.Button(label=f"{upgrade.name} · {upgrade.rarity}", style=discord.ButtonStyle.primary, row=index)
            button.callback = self.make_callback(upgrade_id)
            self.add_item(button)
        info = discord.ui.Button(label="선택지 상세 보기", emoji="ℹ️", style=discord.ButtonStyle.secondary, row=3)
        info.callback = self.show_details
        self.add_item(info)
        self.choices = choices

    def make_callback(self, upgrade_id: str):
        async def callback(interaction: discord.Interaction) -> None:
            try:
                state = await asyncio.to_thread(self.service.choose_upgrade, self.owner_id, upgrade_id)
            except Exception as exc:
                await safe_error(interaction, exc)
                return
            await interaction.response.edit_message(embed=briefing_embed(state, self.service), view=RunView(self.service, self.owner_id))
        return callback

    async def show_details(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="🔷 강화 선택지", color=0x8B5CF6)
        for upgrade_id in self.choices:
            upgrade = UPGRADES[upgrade_id]
            embed.add_field(name=f"{upgrade.name} · {upgrade.rarity}", value=upgrade.description, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PostBattleView(OwnedView):
    @discord.ui.button(label="작전본부", emoji="🏠", style=discord.ButtonStyle.primary)
    async def headquarters(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await show_headquarters(interaction, self.service, self.owner_id)

    @discord.ui.button(label="장비 확인", emoji="🔧", style=discord.ButtonStyle.secondary)
    async def gear(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=gear_embed(interaction.user, self.service), view=GearView(self.service, self.owner_id))


class GearSelect(discord.ui.Select):
    def __init__(self, parent: "GearView") -> None:
        self.parent_view = parent
        gear = parent.service.list_gear(parent.owner_id)[:25]
        options = [discord.SelectOption(label=f"[{item.grade}] {item.name} +{item.level}"[:100], value=item.item_id, emoji=GRADE_EMOJI.get(item.grade), description=f"{slot_label(item.slot)}{' · 장착 중' if item.equipped else ''}"[:100]) for item in gear]
        super().__init__(placeholder="장비 선택", options=options or [discord.SelectOption(label="장비 없음", value="none")], disabled=not gear)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_id = self.values[0]
        item = self.parent_view.service.repository.get_gear(self.parent_view.owner_id, self.values[0])
        await interaction.response.edit_message(embed=gear_embed(interaction.user, self.parent_view.service, item), view=self.parent_view)


class GearView(OwnedView):
    def __init__(self, service: WatchpointService, owner_id: int) -> None:
        super().__init__(service, owner_id)
        self.selected_id: str | None = None
        self.add_item(GearSelect(self))

    @discord.ui.button(label="장착", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def equip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.selected_id:
            await safe_error(interaction, GameRuleError("장비를 먼저 선택하세요"))
            return
        try:
            item = await asyncio.to_thread(self.service.equip_gear, self.owner_id, self.selected_id)
        except Exception as exc:
            await safe_error(interaction, exc)
            return
        await interaction.response.edit_message(embed=gear_embed(interaction.user, self.service, item), view=GearView(self.service, self.owner_id))

    @discord.ui.button(label="강화", emoji="⬆️", style=discord.ButtonStyle.primary, row=1)
    async def enhance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.selected_id:
            await safe_error(interaction, GameRuleError("장비를 먼저 선택하세요"))
            return
        try:
            item = await asyncio.to_thread(self.service.enhance_gear, self.owner_id, self.selected_id)
        except Exception as exc:
            await safe_error(interaction, exc)
            return
        view = GearView(self.service, self.owner_id)
        view.selected_id = item.item_id
        await interaction.response.edit_message(embed=gear_embed(interaction.user, self.service, item), view=view)

    @discord.ui.button(label="작전본부", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def headquarters(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await show_headquarters(interaction, self.service, self.owner_id)


class ResearchSelect(discord.ui.Select):
    def __init__(self, parent: "ResearchView") -> None:
        self.parent_view = parent
        options = [discord.SelectOption(label=node.name, value=node_id, description=f"{node.branch} · {node.description}"[:100]) for node_id, node in RESEARCH_NODES.items()]
        super().__init__(placeholder="연구 항목 선택", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_id = self.values[0]
        await interaction.response.edit_message(embed=research_embed(interaction.user, self.parent_view.service, self.values[0]), view=self.parent_view)


class ResearchView(OwnedView):
    def __init__(self, service: WatchpointService, owner_id: int) -> None:
        super().__init__(service, owner_id)
        self.selected_id: str | None = None
        self.add_item(ResearchSelect(self))

    @discord.ui.button(label="연구 업그레이드", emoji="🧪", style=discord.ButtonStyle.success, row=1)
    async def upgrade(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.selected_id:
            await safe_error(interaction, GameRuleError("연구 항목을 먼저 선택하세요"))
            return
        try:
            await asyncio.to_thread(self.service.upgrade_research, self.owner_id, self.selected_id)
        except Exception as exc:
            await safe_error(interaction, exc)
            return
        await interaction.response.edit_message(embed=research_embed(interaction.user, self.service, self.selected_id), view=self)

    @discord.ui.button(label="작전본부", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def headquarters(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await show_headquarters(interaction, self.service, self.owner_id)


class DailyView(OwnedView):
    @discord.ui.button(label="전체 보상 수령", emoji="🎁", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        claimed = await asyncio.to_thread(self.service.claim_daily, self.owner_id)
        if not claimed:
            await interaction.response.send_message("아직 모든 미션을 완료하지 않았거나 이미 수령했습니다.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=daily_embed(interaction.user, self.service), view=self)

    @discord.ui.button(label="작전본부", emoji="🏠", style=discord.ButtonStyle.secondary)
    async def headquarters(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await show_headquarters(interaction, self.service, self.owner_id)


def sample_indexes(total: int, maximum: int) -> list[int]:
    if total <= maximum:
        return list(range(total))
    indexes = {0, total - 1}
    for index in range(1, maximum - 1):
        indexes.add(round(index * (total - 1) / (maximum - 1)))
    return sorted(indexes)
