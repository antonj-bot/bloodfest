-- Optional: the server creates these automatically on first match.
create table if not exists usage_month (
    month         text primary key,
    egress_bytes  bigint  not null default 0,
    db_sessions   integer not null default 0,
    match_seconds bigint  not null default 0,
    matches       integer not null default 0
);
create table if not exists matches (
    id       bigserial primary key,
    ended_at timestamptz not null default now(),
    rounds   integer not null,
    winner   text
);
create table if not exists player_stats (
    name       text primary key,
    matches    integer not null default 0,
    wins       integer not null default 0,
    kills      integer not null default 0,
    boss_kills integer not null default 0,
    points     bigint  not null default 0
);
