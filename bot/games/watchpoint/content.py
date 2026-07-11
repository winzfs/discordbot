from __future__ import annotations

from .models import ChapterDef, EnemyDef, HeroDef, ResearchNode, StageDef, UpgradeDef

GAME_TITLE = "워치포인트 프로토콜"
GAME_VERSION = "2.0.0-stage-growth"

DIFFICULTIES = (
    {"id": 0, "name": "일반", "emoji": "🟢", "hp": 1.0, "atk": 1.0, "reward": 1.0, "rule": "표준 작전"},
    {"id": 1, "name": "악몽", "emoji": "🟣", "hp": 1.42, "atk": 1.28, "reward": 1.45, "rule": "정예 강화·보스 패턴 가속"},
    {"id": 2, "name": "지옥", "emoji": "🔴", "hp": 1.95, "atk": 1.62, "reward": 2.0, "rule": "회복 감소·적 폭주"},
    {"id": 3, "name": "전설", "emoji": "🟡", "hp": 2.65, "atk": 2.05, "reward": 2.75, "rule": "모든 지역 기믹 강화"},
)


def difficulty_def(value: int) -> dict[str, object]:
    return DIFFICULTIES[max(0, min(value, len(DIFFICULTIES) - 1))]


HEROES: dict[str, HeroDef] = {
    "tracer": HeroDef("tracer", "트레이서", "⚡", "공격", "연사·회피·감전 연쇄", 1, 1020, 128, .12, .16, 0, "펄스 폭탄", "burst", 3.4, ("speed", "dodge", "shock", "multi_hit")),
    "reaper": HeroDef("reaper", "리퍼", "💀", "공격", "흡혈·처형·근접 폭발", 1, 1120, 126, .08, .05, .07, "죽음의 꽃", "aoe", 2.7, ("lifesteal", "execute", "berserk", "aoe")),
    "kiriko": HeroDef("kiriko", "키리코", "🦊", "지원", "치명타·정화·회복", 1, 980, 110, .18, .10, .02, "여우길", "tempo", 2.1, ("crit", "heal", "shield", "speed")),
    "reinhardt": HeroDef("reinhardt", "라인하르트", "🛡️", "돌격", "방벽·반격·강타", 1, 1190, 112, .05, .02, 0, "대지분쇄", "control", 2.8, ("shield", "counter", "burn", "control")),
    "genji": HeroDef("genji", "겐지", "🐉", "공격", "반격·연쇄 처형", 8, 930, 128, .15, .17, .02, "용검", "execute", 3.0, ("crit", "dodge", "counter", "execute")),
    "sombra": HeroDef("sombra", "솜브라", "💻", "공격", "해킹·약화·제어", 12, 960, 112, .11, .13, .03, "EMP", "debuff", 2.2, ("hack", "shock", "control", "speed")),
    "ashe": HeroDef("ashe", "애쉬", "🎯", "공격", "정밀 사격·화상", 16, 950, 141, .17, .07, 0, "B.O.B.", "summon", 3.1, ("crit", "burn", "first_hit", "summon")),
    "sigma": HeroDef("sigma", "시그마", "🌌", "돌격", "보호막·중력 제어", 20, 1320, 119, .08, .04, 0, "중력 붕괴", "control", 2.6, ("shield", "control", "aoe", "counter")),
    "moira": HeroDef("moira", "모이라", "🧬", "지원", "흡혈·지속 피해·회복", 24, 1060, 116, .09, .08, .12, "융화", "drain", 2.4, ("lifesteal", "poison", "heal", "beam")),
    "soldier76": HeroDef("soldier76", "솔저: 76", "🔫", "공격", "안정 연사·전술 회복", 28, 1040, 124, .12, .08, .04, "전술 조준경", "tempo", 2.5, ("multi_hit", "crit", "heal", "tracking")),
    "pharah": HeroDef("pharah", "파라", "🚀", "공격", "광역 폭발·공중 우위", 34, 1000, 139, .09, .10, 0, "포화", "aoe", 3.0, ("aoe", "air", "burn", "burst")),
    "ramattra": HeroDef("ramattra", "라마트라", "🟣", "돌격", "형태 전환·후반 폭주", 40, 1500, 120, .06, .02, .04, "절멸", "berserk", 2.7, ("shield", "berserk", "aoe", "survival")),
}

CHAPTER_SPECS = (
    ("널 섹터 공장", "🏭", "증원 드론과 생산 라인을 파괴합니다.", "증원", ("정찰 드론", "수리 드론", "전쟁 로봇", "자폭 옴닉", "중형 타이탄")),
    ("킹스 로우 지하", "🌆", "방벽 부대를 돌파하고 지하 통제실을 확보합니다.", "방벽", ("널 섹터 돌격병", "방벽 드론", "자폭병", "지휘 옴닉", "지하 지휘관")),
    ("아이헨발데 성채", "🏰", "중장갑 방어선을 무너뜨리고 성채를 탈환합니다.", "중장갑", ("성채 수비병", "OR14 중장", "화염 포대", "강화 기사", "성채 파쇄자")),
    ("볼스카야 연구소", "❄️", "빙결 장치와 포탑을 무력화합니다.", "빙결", ("극저온 드론", "자동 포탑", "해킹 기술병", "방어 메카", "거대 방어 메카")),
    ("눔바니 폐허", "🌇", "탈론 기동대를 추격하고 도시 코어를 지킵니다.", "기동", ("탈론 척후병", "점프 제트병", "지원 드론", "돌격 대장", "탈론 사령관")),
    ("남극 기지", "🧊", "저체온 환경에서 실험체를 봉쇄합니다.", "저체온", ("냉각 실험체", "빙결 포탑", "극지 추적자", "실험체 알파", "극저온 거수")),
    ("지브롤터 감시기지", "🛰️", "공중 병력과 건십을 격추합니다.", "공중", ("공중 드론", "미사일 병", "탈론 파일럿", "공습 지휘관", "탈론 건십")),
    ("하나무라 잔해", "⛩️", "암살자와 분신 부대를 추적합니다.", "암살", ("사이버 닌자", "위장 암살자", "분신 드론", "그림자 대장", "용의 그림자")),
    ("네팔 수도원", "🏔️", "상태이상에 저항하는 옴닉 수호자를 상대합니다.", "정화", ("수도원 수호자", "아이리스 수행자", "정화 드론", "수호 승려", "아이리스 파수꾼")),
    ("탈론 궤도기지", "🪐", "모든 전장 기믹을 돌파해 궤도 코어를 파괴합니다.", "복합", ("궤도 돌격병", "중력 포대", "해킹 암살자", "탈론 집행관", "널 섹터 코어")),
)

ENEMIES: dict[str, EnemyDef] = {}
CHAPTER_ENEMY_IDS: dict[int, tuple[str, ...]] = {}
for chapter, (_, _, _, mechanic, names) in enumerate(CHAPTER_SPECS, 1):
    ids: list[str] = []
    for index, name in enumerate(names, 1):
        enemy_id = f"c{chapter}_e{index}"
        boss = index == 5
        elite = index == 4
        hp = int((260 + chapter * 60 + index * 55) * (2.2 if boss else 1.35 if elite else 1.0))
        attack = int((37 + chapter * 7 + index * 4) * (1.35 if boss else 1.15 if elite else 1.0))
        tags = [mechanic, "boss" if boss else "elite" if elite else "normal"]
        if index == 2: tags.append("support")
        if index == 3: tags.append("burst")
        ENEMIES[enemy_id] = EnemyDef(enemy_id, name, "👑" if boss else "⚠️" if elite else "🤖", hp, attack, tuple(tags), f"{name} 전용 패턴")
        ids.append(enemy_id)
    CHAPTER_ENEMY_IDS[chapter] = tuple(ids)

STAGE_NAMES = ("침투", "전초전", "보급선", "위험 구역", "중간 제압", "돌파", "추격", "정예 격돌", "최종 진입", "결전")
OBJECTIVES = ("assault", "assault", "escort", "defense", "elite", "assault", "survival", "elite", "escort", "boss")
OBJECTIVE_LABELS = {"assault": "섬멸", "escort": "호위", "defense": "방어", "survival": "생존", "elite": "정예", "boss": "보스"}


def _build_chapters() -> dict[int, ChapterDef]:
    result: dict[int, ChapterDef] = {}
    for chapter, (name, emoji, summary, mechanic, _) in enumerate(CHAPTER_SPECS, 1):
        stages: list[StageDef] = []
        enemy_ids = CHAPTER_ENEMY_IDS[chapter]
        for stage in range(1, 11):
            objective = OBJECTIVES[stage - 1]
            pool = enemy_ids[:3] if stage <= 4 else enemy_ids[:4]
            if objective == "boss": pool = (enemy_ids[4],)
            elif objective == "elite": pool = (enemy_ids[3], enemy_ids[(stage + chapter) % 3])
            stages.append(StageDef(
                chapter, stage, f"{name} · {STAGE_NAMES[stage - 1]}", objective,
                OBJECTIVE_LABELS[objective], mechanic, f"{mechanic} 작전 규칙",
                tuple(pool), 3 if stage >= 8 else 2, 16 + stage * 2,
                780 + chapter * 130 + stage * 72,
                55 + chapter * 9 + stage * 6,
                120 + chapter * 18 + stage * 10,
                3 + chapter // 2 + (2 if objective in {"elite", "boss"} else 0),
            ))
        result[chapter] = ChapterDef(chapter, name, emoji, summary, mechanic, tuple(stages))
    return result


CHAPTERS = _build_chapters()


def get_stage(chapter: int, stage: int) -> StageDef:
    return CHAPTERS[chapter].stages[stage - 1]


def stage_from_global_id(global_id: int) -> StageDef:
    safe = max(1, min(100, global_id))
    return get_stage((safe - 1) // 10 + 1, (safe - 1) % 10 + 1)


RESEARCH_NODES: dict[str, ResearchNode] = {
    "firepower": ResearchNode("firepower", "화력 교정", "화력", "기본 공격력 증가", 20, 10, 1.35, "attack_pct", .025),
    "critical": ResearchNode("critical", "약점 분석", "화력", "치명타 확률 증가", 15, 12, 1.42, "crit", .006),
    "boss_damage": ResearchNode("boss_damage", "대형 표적 연구", "화력", "보스 피해 증가", 15, 15, 1.44, "boss_damage_pct", .025),
    "status_power": ResearchNode("status_power", "상태 증폭", "화력", "상태 피해 증가", 15, 14, 1.43, "status_damage_pct", .03),
    "vitality": ResearchNode("vitality", "생체 보강", "생존", "최대 체력 증가", 20, 10, 1.35, "max_hp_pct", .025),
    "barrier": ResearchNode("barrier", "초기 방벽", "생존", "시작 보호막 증가", 15, 12, 1.40, "start_shield", 18),
    "recovery": ResearchNode("recovery", "회복 효율", "생존", "회복량 증가", 15, 13, 1.42, "healing_pct", .03),
    "evasion": ResearchNode("evasion", "기동 반응", "생존", "회피율 증가", 12, 16, 1.47, "dodge", .005),
    "ult_charge": ResearchNode("ult_charge", "궁극기 순환", "전술", "궁극기 충전 증가", 15, 14, 1.42, "ult_charge_pct", .03),
    "loot": ResearchNode("loot", "전리품 탐색", "전술", "장비 드롭률 증가", 15, 15, 1.44, "gear_drop_pct", .02),
    "quality": ResearchNode("quality", "정밀 제작", "전술", "고등급 장비 확률 증가", 12, 18, 1.50, "gear_quality", .02),
    "choice": ResearchNode("choice", "전술 시뮬레이션", "전술", "강화 희귀도 증가", 12, 18, 1.50, "upgrade_quality", .02),
}


def _u(uid: str, name: str, desc: str, rarity: str, tags: tuple[str, ...], effects: dict[str, float], max_stack: int = 5, hero: str | None = None, req: tuple[str, ...] = ()) -> UpgradeDef:
    return UpgradeDef(uid, name, desc, rarity, tags, effects, max_stack, hero, req)


UPGRADES: dict[str, UpgradeDef] = {
    u.id: u for u in (
        _u("calibrated_rounds", "교정 탄환", "공격력 +12%", "일반", ("attack",), {"attack_pct": .12}, 8),
        _u("combat_plating", "전투 장갑", "최대 체력 +14%, 즉시 회복", "일반", ("survival",), {"max_hp_pct": .14, "heal_pct": .14}, 6),
        _u("weakpoint_scope", "약점 조준경", "치명타 +7%, 치명 피해 +10%", "일반", ("crit",), {"crit": .07, "crit_damage": .10}, 6),
        _u("phase_step", "위상 스텝", "회피 +6%", "일반", ("dodge",), {"dodge": .06}, 5),
        _u("bio_recycler", "생체 재활용기", "흡혈 +6%", "일반", ("lifesteal",), {"lifesteal": .06}, 6),
        _u("rapid_cycle", "고속 순환", "추가 공격 확률 +15%", "희귀", ("speed", "multi_hit"), {"extra_attack": .15}),
        _u("shock_ammo", "감전 탄환", "공격 시 감전 피해", "희귀", ("shock",), {"shock_damage": .28}),
        _u("chain_reactor", "연쇄 반응로", "감전이 다른 적에게 번짐", "영웅", ("shock", "chain", "aoe"), {"chain_damage": .36}, 4, None, ("shock",)),
        _u("incendiary_mix", "소이 혼합물", "공격 시 화상 부여", "희귀", ("burn",), {"burn_damage": .24}),
        _u("serrated_payload", "절삭 탄두", "공격 시 출혈 부여", "희귀", ("bleed",), {"bleed_damage": .22}),
        _u("execution_protocol", "처형 프로토콜", "저체력 적 피해 +45%", "영웅", ("execute",), {"execute_pct": .45}, 4),
        _u("emergency_barrier", "긴급 방벽", "전투 시작 방벽 +18%", "희귀", ("shield",), {"start_shield_pct": .18}),
        _u("barrier_resonance", "방벽 공명", "방벽 유지 중 피해 +25%", "영웅", ("shield", "attack"), {"shield_damage_pct": .25}, 4, None, ("shield",)),
        _u("ultimate_battery", "궁극기 축전지", "궁극기 충전 +20%", "희귀", ("ultimate",), {"ult_charge_pct": .20}),
        _u("overclocked_ultimate", "궁극기 과충전", "궁극기 위력 +40%", "영웅", ("ultimate", "burst"), {"ultimate_power_pct": .40}, 4, None, ("ultimate",)),
        _u("glass_cannon", "유리 대포", "공격력 +35%, 체력 -12%", "영웅", ("risk", "attack"), {"attack_pct": .35, "max_hp_pct": -.12}, 2),
        _u("boss_breaker", "거대 표적 파쇄", "정예·보스 피해 +28%", "영웅", ("boss",), {"boss_damage_pct": .28}, 4),
        _u("cheat_death", "비상 귀환", "치명 피해 1회 무효화", "전설", ("survival", "legend"), {"cheat_death": 1}, 1),
        _u("recursive_fire", "재귀 사격", "추가 공격 연쇄 가능", "전설", ("multi_hit", "legend"), {"recursive_extra": 1}, 1, None, ("multi_hit",)),
    )
}

HERO_UPGRADE_SPECS = {
    "tracer": (("잔상 반격", {"dodge_counter": .70}, ("dodge", "counter")), ("시간 루프", {"third_hit_extra": 1}, ("speed", "multi_hit"))),
    "reaper": (("피의 광기", {"low_hp_attack_pct": .55}, ("lifesteal", "berserk")), ("영혼 개화", {"kill_heal_pct": .12}, ("execute", "heal"))),
    "kiriko": (("여우 집중", {"crit_heal_pct": .05}, ("crit", "heal")), ("여우길 폭주", {"ult_tempo": .45}, ("ultimate", "speed"))),
    "reinhardt": (("방벽 매트릭스", {"start_shield_pct": .30, "shield_damage_pct": .20}, ("shield",)), ("대지분쇄 연계", {"ult_stun": 1}, ("ultimate", "control"))),
    "genji": (("완전한 튕겨내기", {"dodge": .06, "dodge_counter": .65}, ("dodge", "counter")), ("용신의 흐름", {"extra_attack": .18, "execute_pct": .30}, ("multi_hit", "execute"))),
    "sombra": (("백도어 탄환", {"accuracy": .15, "ult_charge_pct": .18}, ("hack", "tracking")), ("EMP 재귀 루프", {"ultimate_power_pct": .45}, ("hack", "ultimate"))),
    "ashe": (("다이너마이트 탄두", {"burn_damage": .28, "kill_burst": .65}, ("burn", "aoe")), ("B.O.B. 프로토콜", {"ultimate_power_pct": .40, "extra_attack": .12}, ("summon", "ultimate"))),
    "sigma": (("키네틱 방벽", {"start_shield_pct": .25, "shield_damage_pct": .18}, ("shield", "counter")), ("중력 특이점", {"ultimate_power_pct": .55}, ("control", "ultimate"))),
    "moira": (("생체 순환", {"lifesteal": .10, "status_damage_pct": .22}, ("lifesteal", "poison")), ("소멸 수확", {"dodge": .07, "kill_heal_pct": .08}, ("dodge", "heal"))),
    "soldier76": (("나선 로켓 탄두", {"kill_burst": .72, "attack_pct": .15}, ("aoe", "attack")), ("전술 조준 고정", {"crit": .10, "ult_charge_pct": .20}, ("crit", "tracking"))),
    "pharah": (("충격 포화", {"burn_damage": .24, "kill_burst": .85}, ("burn", "aoe")), ("제공권 장악", {"accuracy": .18, "ultimate_power_pct": .50}, ("air", "tracking"))),
    "ramattra": (("네메시스 코어", {"low_hp_attack_pct": .45, "start_shield_pct": .18}, ("berserk", "shield")), ("무한 절멸", {"ultimate_power_pct": .50, "kill_heal_pct": .06}, ("ultimate", "berserk"))),
}
for hero_id, pair in HERO_UPGRADE_SPECS.items():
    for index, (name, effects, tags) in enumerate(pair, 1):
        uid = f"{hero_id}_special_{index}"
        UPGRADES[uid] = _u(uid, name, "영웅 고유 전투 모듈", "전설" if index == 2 else "영웅", tags, effects, 1 if index == 2 else 4, hero_id)

GEAR_SLOTS = (("weapon", "무기", "🔫"), ("helmet", "헬멧", "🪖"), ("armor", "갑옷", "🥋"), ("module", "모듈", "💾"), ("core", "코어", "🔷"))
GRADE_ORDER = ("D", "C", "B", "A", "S", "U")
GRADE_MULTIPLIER = {"D": 1.0, "C": 1.26, "B": 1.62, "A": 2.08, "S": 2.72, "U": 3.55}
GRADE_EMOJI = {"D": "⚪", "C": "🟢", "B": "🔵", "A": "🟣", "S": "🟡", "U": "🔴"}
GEAR_NAMES = {
    "weapon": ("전술 펄스 소총", "테슬라 카빈", "탈론 산탄총", "중력 가속포"),
    "helmet": ("정찰 바이저", "널 섹터 스캐너", "탈론 전술 헬멧", "아이리스 헤드기어"),
    "armor": ("경량 전투복", "강화 장갑", "반응형 방벽복", "블랙워치 플레이트"),
    "module": ("감전 모듈", "정밀 조준 모듈", "생체 회복 모듈", "궁극기 순환 모듈"),
    "core": ("옴닉 에너지 코어", "탈론 암호 코어", "아이리스 파편", "크로노 코어"),
}
DAILY_MISSIONS = (("stage_clear", "스테이지 1회 클리어", 1), ("gear_enhance", "장비 강화 1회", 1), ("research_upgrade", "연구 업그레이드 1회", 1), ("ultimate_use", "궁극기 1회 사용", 1), ("ranking_view", "랭킹 확인 1회", 1))
