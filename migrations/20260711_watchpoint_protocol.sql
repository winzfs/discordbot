create table if not exists public.discordbot_wp_accounts (
    user_id bigint primary key,
    level integer not null default 1,
    xp integer not null default 0,
    credits integer not null default 0,
    research_points integer not null default 0,
    best_stage_id integer not null default 0,
    highest_difficulty integer not null default 0,
    total_stage_clears integer not null default 0,
    total_boss_clears integer not null default 0,
    created_at bigint not null,
    updated_at bigint not null
);

create table if not exists public.discordbot_wp_difficulty_progress (
    user_id bigint not null,
    difficulty integer not null,
    best_stage_id integer not null default 0,
    updated_at bigint not null,
    primary key (user_id, difficulty)
);

create table if not exists public.discordbot_wp_hero_progress (
    user_id bigint not null,
    hero_id text not null,
    mastery_level integer not null default 1,
    mastery_xp integer not null default 0,
    total_wins integer not null default 0,
    updated_at bigint not null,
    primary key (user_id, hero_id)
);

create table if not exists public.discordbot_wp_runs (
    user_id bigint primary key,
    state jsonb not null,
    updated_at bigint not null
);

create table if not exists public.discordbot_wp_gear (
    item_id text primary key,
    user_id bigint not null,
    slot text not null,
    grade text not null,
    level integer not null default 0,
    name text not null,
    stats jsonb not null,
    equipped boolean not null default false,
    locked boolean not null default false,
    created_at bigint not null
);

create index if not exists discordbot_wp_gear_user_idx
    on public.discordbot_wp_gear(user_id, equipped desc, created_at desc);

create table if not exists public.discordbot_wp_research (
    user_id bigint not null,
    node_id text not null,
    level integer not null default 0,
    updated_at bigint not null,
    primary key (user_id, node_id)
);

create table if not exists public.discordbot_wp_daily (
    user_id bigint not null,
    day date not null,
    progress jsonb not null default '{}'::jsonb,
    claimed boolean not null default false,
    updated_at bigint not null,
    primary key (user_id, day)
);

alter table public.discordbot_wp_accounts enable row level security;
alter table public.discordbot_wp_difficulty_progress enable row level security;
alter table public.discordbot_wp_hero_progress enable row level security;
alter table public.discordbot_wp_runs enable row level security;
alter table public.discordbot_wp_gear enable row level security;
alter table public.discordbot_wp_research enable row level security;
alter table public.discordbot_wp_daily enable row level security;

revoke all on table public.discordbot_wp_accounts from anon, authenticated;
revoke all on table public.discordbot_wp_difficulty_progress from anon, authenticated;
revoke all on table public.discordbot_wp_hero_progress from anon, authenticated;
revoke all on table public.discordbot_wp_runs from anon, authenticated;
revoke all on table public.discordbot_wp_gear from anon, authenticated;
revoke all on table public.discordbot_wp_research from anon, authenticated;
revoke all on table public.discordbot_wp_daily from anon, authenticated;
