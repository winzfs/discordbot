from __future__ import annotations

import datetime as dt
import os
import time
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import Account, GearItem, HeroProgress, RunState

DATABASE_URL = os.getenv("SUPABASE_DB_URL", "").strip()
KST = ZoneInfo("Asia/Seoul")
MAX_GEAR = 50

SCHEMA_SQL = """
create table if not exists public.discordbot_wp_accounts(
 user_id bigint primary key, level int not null default 1, xp int not null default 0,
 credits int not null default 0, research_points int not null default 0,
 best_stage_id int not null default 0, highest_difficulty int not null default 0,
 total_stage_clears int not null default 0, total_boss_clears int not null default 0,
 created_at bigint not null, updated_at bigint not null);
create table if not exists public.discordbot_wp_difficulty_progress(
 user_id bigint not null, difficulty int not null, best_stage_id int not null default 0,
 updated_at bigint not null, primary key(user_id,difficulty));
create table if not exists public.discordbot_wp_hero_progress(
 user_id bigint not null, hero_id text not null, mastery_level int not null default 1,
 mastery_xp int not null default 0, total_wins int not null default 0,
 updated_at bigint not null, primary key(user_id,hero_id));
create table if not exists public.discordbot_wp_runs(
 user_id bigint primary key, state jsonb not null, updated_at bigint not null);
create table if not exists public.discordbot_wp_gear(
 item_id text primary key, user_id bigint not null, slot text not null, grade text not null,
 level int not null default 0, name text not null, stats jsonb not null,
 equipped boolean not null default false, locked boolean not null default false,
 created_at bigint not null);
create index if not exists discordbot_wp_gear_user_idx on public.discordbot_wp_gear(user_id,equipped desc,created_at desc);
create table if not exists public.discordbot_wp_research(
 user_id bigint not null, node_id text not null, level int not null default 0,
 updated_at bigint not null, primary key(user_id,node_id));
create table if not exists public.discordbot_wp_daily(
 user_id bigint not null, day date not null, progress jsonb not null default '{}'::jsonb,
 claimed boolean not null default false, updated_at bigint not null,
 primary key(user_id,day));
"""


def now_ts() -> int:
    return int(time.time())


def account_xp_required(level: int) -> int:
    return 180 + max(0, level - 1) * 55


def mastery_xp_required(level: int) -> int:
    return 120 + max(0, level - 1) * 45


class WatchpointRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = (database_url or DATABASE_URL).strip()
        if not self.database_url:
            raise RuntimeError("SUPABASE_DB_URL 환경변수가 없습니다")

    @contextmanager
    def connection(self):
        with psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            connect_timeout=10,
            prepare_threshold=None,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("set local statement_timeout='15s'")
            yield conn

    def ensure_schema(self) -> None:
        with self.connection() as conn, conn.cursor() as cur:
            for statement in SCHEMA_SQL.split(";"):
                sql = statement.strip()
                if sql:
                    cur.execute(sql)

    def get_account(self, user_id: int) -> Account:
        current = now_ts()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into public.discordbot_wp_accounts(user_id,created_at,updated_at)
                values(%s,%s,%s) on conflict(user_id) do nothing""",
                (user_id, current, current),
            )
            cur.execute("select * from public.discordbot_wp_accounts where user_id=%s", (user_id,))
            row = cur.fetchone()
        return Account(**dict(row))

    def save_account(self, account: Account) -> None:
        account.updated_at = now_ts()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """update public.discordbot_wp_accounts set level=%s,xp=%s,credits=%s,
                research_points=%s,best_stage_id=%s,highest_difficulty=%s,
                total_stage_clears=%s,total_boss_clears=%s,updated_at=%s where user_id=%s""",
                (account.level, account.xp, account.credits, account.research_points,
                 account.best_stage_id, account.highest_difficulty, account.total_stage_clears,
                 account.total_boss_clears, account.updated_at, account.user_id),
            )

    def grant_rewards(self, user_id: int, xp: int, credits: int, research: int) -> Account:
        with self.connection() as conn, conn.cursor() as cur:
            current = now_ts()
            cur.execute(
                """insert into public.discordbot_wp_accounts(user_id,created_at,updated_at)
                values(%s,%s,%s) on conflict(user_id) do nothing""",
                (user_id, current, current),
            )
            cur.execute("select * from public.discordbot_wp_accounts where user_id=%s for update", (user_id,))
            row = dict(cur.fetchone())
            row["xp"] += max(0, xp)
            row["credits"] += max(0, credits)
            row["research_points"] += max(0, research)
            while row["level"] < 100 and row["xp"] >= account_xp_required(row["level"]):
                row["xp"] -= account_xp_required(row["level"])
                row["level"] += 1
                row["credits"] += 250 + row["level"] * 20
                row["research_points"] += 3
            cur.execute(
                """update public.discordbot_wp_accounts set level=%s,xp=%s,credits=%s,
                research_points=%s,updated_at=%s where user_id=%s returning *""",
                (row["level"], row["xp"], row["credits"], row["research_points"], current, user_id),
            )
            saved = dict(cur.fetchone())
        return Account(**saved)

    def record_clear(self, user_id: int, difficulty: int, stage_id: int, boss: bool) -> None:
        current = now_ts()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into public.discordbot_wp_difficulty_progress(user_id,difficulty,best_stage_id,updated_at)
                values(%s,%s,%s,%s) on conflict(user_id,difficulty) do update set
                best_stage_id=greatest(discordbot_wp_difficulty_progress.best_stage_id,excluded.best_stage_id),
                updated_at=excluded.updated_at""",
                (user_id, difficulty, stage_id, current),
            )
            cur.execute(
                """update public.discordbot_wp_accounts set
                best_stage_id=greatest(best_stage_id,%s),highest_difficulty=greatest(highest_difficulty,%s),
                total_stage_clears=total_stage_clears+1,total_boss_clears=total_boss_clears+%s,
                updated_at=%s where user_id=%s""",
                (stage_id, difficulty, 1 if boss else 0, current, user_id),
            )

    def difficulty_progress(self, user_id: int) -> dict[int, int]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select difficulty,best_stage_id from public.discordbot_wp_difficulty_progress where user_id=%s", (user_id,))
            return {int(row["difficulty"]): int(row["best_stage_id"]) for row in cur.fetchall()}

    def get_hero_progress(self, user_id: int, hero_id: str) -> HeroProgress:
        current = now_ts()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into public.discordbot_wp_hero_progress(user_id,hero_id,updated_at)
                values(%s,%s,%s) on conflict(user_id,hero_id) do nothing""",
                (user_id, hero_id, current),
            )
            cur.execute("select * from public.discordbot_wp_hero_progress where user_id=%s and hero_id=%s", (user_id, hero_id))
            row = dict(cur.fetchone())
        row.pop("updated_at", None)
        return HeroProgress(**row)

    def grant_mastery(self, user_id: int, hero_id: str, xp: int, won: bool) -> HeroProgress:
        self.get_hero_progress(user_id, hero_id)
        current = now_ts()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "select * from public.discordbot_wp_hero_progress where user_id=%s and hero_id=%s for update",
                (user_id, hero_id),
            )
            row = dict(cur.fetchone())
            row["mastery_xp"] += max(0, xp)
            if won:
                row["total_wins"] += 1
            while row["mastery_level"] < 50 and row["mastery_xp"] >= mastery_xp_required(row["mastery_level"]):
                row["mastery_xp"] -= mastery_xp_required(row["mastery_level"])
                row["mastery_level"] += 1
            cur.execute(
                """update public.discordbot_wp_hero_progress set mastery_level=%s,mastery_xp=%s,
                total_wins=%s,updated_at=%s where user_id=%s and hero_id=%s""",
                (row["mastery_level"], row["mastery_xp"], row["total_wins"], current, user_id, hero_id),
            )
        return HeroProgress(user_id, hero_id, row["mastery_level"], row["mastery_xp"], row["total_wins"])

    def get_run(self, user_id: int) -> RunState | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select state from public.discordbot_wp_runs where user_id=%s", (user_id,))
            row = cur.fetchone()
        return RunState.from_json(dict(row["state"])) if row else None

    def save_run(self, state: RunState) -> None:
        state.updated_at = now_ts()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into public.discordbot_wp_runs(user_id,state,updated_at) values(%s,%s,%s)
                on conflict(user_id) do update set state=excluded.state,updated_at=excluded.updated_at""",
                (state.user_id, Jsonb(state.to_json()), state.updated_at),
            )

    def delete_run(self, user_id: int) -> None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("delete from public.discordbot_wp_runs where user_id=%s", (user_id,))

    def research_levels(self, user_id: int) -> dict[str, int]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select node_id,level from public.discordbot_wp_research where user_id=%s", (user_id,))
            return {str(row["node_id"]): int(row["level"]) for row in cur.fetchall()}

    def buy_research(self, user_id: int, node_id: str, cost: int, max_level: int) -> int:
        current = now_ts()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select research_points from public.discordbot_wp_accounts where user_id=%s for update", (user_id,))
            row = cur.fetchone()
            if not row or int(row["research_points"]) < cost:
                raise ValueError("연구 데이터가 부족합니다")
            cur.execute("select level from public.discordbot_wp_research where user_id=%s and node_id=%s for update", (user_id, node_id))
            saved = cur.fetchone()
            level = int(saved["level"]) if saved else 0
            if level >= max_level:
                raise ValueError("이미 최대 레벨입니다")
            new_level = level + 1
            cur.execute("update public.discordbot_wp_accounts set research_points=research_points-%s,updated_at=%s where user_id=%s", (cost, current, user_id))
            cur.execute(
                """insert into public.discordbot_wp_research(user_id,node_id,level,updated_at) values(%s,%s,%s,%s)
                on conflict(user_id,node_id) do update set level=excluded.level,updated_at=excluded.updated_at""",
                (user_id, node_id, new_level, current),
            )
        return new_level

    def list_gear(self, user_id: int) -> list[GearItem]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select * from public.discordbot_wp_gear where user_id=%s order by equipped desc,created_at desc", (user_id,))
            return [GearItem.from_row(dict(row)) for row in cur.fetchall()]

    def get_gear(self, user_id: int, item_id: str) -> GearItem | None:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select * from public.discordbot_wp_gear where user_id=%s and item_id=%s", (user_id, item_id))
            row = cur.fetchone()
        return GearItem.from_row(dict(row)) if row else None

    def add_gear(self, item: GearItem) -> bool:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select count(*) as count from public.discordbot_wp_gear where user_id=%s", (item.user_id,))
            if int(cur.fetchone()["count"]) >= MAX_GEAR:
                cur.execute(
                    """delete from public.discordbot_wp_gear where item_id=(select item_id from
                    public.discordbot_wp_gear where user_id=%s and not equipped and not locked
                    order by created_at asc limit 1)""",
                    (item.user_id,),
                )
                if cur.rowcount == 0:
                    return False
            cur.execute(
                """insert into public.discordbot_wp_gear(item_id,user_id,slot,grade,level,name,stats,equipped,locked,created_at)
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(item_id) do nothing""",
                (item.item_id, item.user_id, item.slot, item.grade, item.level, item.name,
                 Jsonb(item.stats), item.equipped, item.locked, item.created_at),
            )
            return cur.rowcount == 1

    def equip_gear(self, user_id: int, item_id: str) -> GearItem:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select * from public.discordbot_wp_gear where user_id=%s and item_id=%s for update", (user_id, item_id))
            row = cur.fetchone()
            if not row:
                raise ValueError("장비를 찾을 수 없습니다")
            cur.execute("update public.discordbot_wp_gear set equipped=false where user_id=%s and slot=%s", (user_id, row["slot"]))
            cur.execute("update public.discordbot_wp_gear set equipped=true where item_id=%s", (item_id,))
        return self.get_gear(user_id, item_id)  # type: ignore[return-value]

    def enhance_gear(self, user_id: int, item_id: str, cost: int) -> GearItem:
        current = now_ts()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select credits from public.discordbot_wp_accounts where user_id=%s for update", (user_id,))
            wallet = cur.fetchone()
            cur.execute("select level from public.discordbot_wp_gear where user_id=%s and item_id=%s for update", (user_id, item_id))
            item = cur.fetchone()
            if not item:
                raise ValueError("장비를 찾을 수 없습니다")
            if int(item["level"]) >= 30:
                raise ValueError("이미 최대 강화입니다")
            if not wallet or int(wallet["credits"]) < cost:
                raise ValueError("크레딧이 부족합니다")
            cur.execute("update public.discordbot_wp_accounts set credits=credits-%s,updated_at=%s where user_id=%s", (cost, current, user_id))
            cur.execute("update public.discordbot_wp_gear set level=level+1 where item_id=%s", (item_id,))
        return self.get_gear(user_id, item_id)  # type: ignore[return-value]

    def daily_status(self, user_id: int) -> tuple[dict[str, int], bool]:
        today = dt.datetime.now(KST).date()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select progress,claimed from public.discordbot_wp_daily where user_id=%s and day=%s", (user_id, today))
            row = cur.fetchone()
        return (dict(row["progress"]), bool(row["claimed"])) if row else ({}, False)

    def add_daily(self, user_id: int, key: str, amount: int = 1) -> None:
        today = dt.datetime.now(KST).date()
        progress, claimed = self.daily_status(user_id)
        progress[key] = int(progress.get(key, 0)) + amount
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into public.discordbot_wp_daily(user_id,day,progress,claimed,updated_at) values(%s,%s,%s,%s,%s)
                on conflict(user_id,day) do update set progress=excluded.progress,updated_at=excluded.updated_at""",
                (user_id, today, Jsonb(progress), claimed, now_ts()),
            )

    def claim_daily(self, user_id: int, required: tuple[tuple[str, str, int], ...]) -> bool:
        today = dt.datetime.now(KST).date()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("select progress,claimed from public.discordbot_wp_daily where user_id=%s and day=%s for update", (user_id, today))
            row = cur.fetchone()
            progress = dict(row["progress"]) if row else {}
            if row and row["claimed"]:
                return False
            if any(int(progress.get(key, 0)) < need for key, _, need in required):
                return False
            cur.execute(
                """insert into public.discordbot_wp_daily(user_id,day,progress,claimed,updated_at) values(%s,%s,%s,true,%s)
                on conflict(user_id,day) do update set claimed=true,updated_at=excluded.updated_at""",
                (user_id, today, Jsonb(progress), now_ts()),
            )
            cur.execute("update public.discordbot_wp_accounts set credits=credits+1000,research_points=research_points+10,updated_at=%s where user_id=%s", (now_ts(), user_id))
            return True

    def ranking(self, limit: int = 10) -> list[dict[str, int]]:
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """select user_id,level,best_stage_id,highest_difficulty,total_boss_clears
                from public.discordbot_wp_accounts order by highest_difficulty desc,best_stage_id desc,
                level desc,total_boss_clears desc limit %s""",
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]
