"""Persistence. Talks to Neon at most TWICE per match (start + end) and never otherwise.

Why so stingy: Neon Free scales compute to zero after 5 minutes idle, and the
free plan gives 100 CU-hours/month. Every connection wakes the compute, so we
open a connection, do one short transaction, and close it immediately.
No connection pool, no health checks against the DB, no background polling.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class Usage:
    egress_bytes: int = 0
    db_sessions: int = 0
    match_seconds: int = 0
    matches: int = 0


class Store(Protocol):
    async def begin_match(self, month: str) -> tuple[Usage, list[dict]]: ...
    async def end_match(self, month: str, egress: int, seconds: int, result: dict | None) -> tuple[Usage, list[dict]]: ...


SCHEMA = """
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
"""

_BUMP_SQL = """
insert into usage_month (month, egress_bytes, db_sessions, match_seconds, matches)
values (%s, %s, 1, %s, %s)
on conflict (month) do update set
    egress_bytes  = usage_month.egress_bytes  + excluded.egress_bytes,
    db_sessions   = usage_month.db_sessions   + 1,
    match_seconds = usage_month.match_seconds + excluded.match_seconds,
    matches       = usage_month.matches       + excluded.matches
returning egress_bytes, db_sessions, match_seconds, matches
"""

_TOP_SQL = "select name, wins, kills, boss_kills, points from player_stats order by wins desc, points desc limit 10"

_PLAYER_SQL = """
insert into player_stats (name, matches, wins, kills, boss_kills, points)
values (%s, 1, %s, %s, %s, %s)
on conflict (name) do update set
    matches    = player_stats.matches    + 1,
    wins       = player_stats.wins       + excluded.wins,
    kills      = player_stats.kills      + excluded.kills,
    boss_kills = player_stats.boss_kills + excluded.boss_kills,
    points     = player_stats.points     + excluded.points
"""

# Keeps storage tiny (Neon Free = 1 GB). Only the newest 500 match rows survive.
_PRUNE_SQL = "delete from matches where id <= (select max(id) - 500 from matches)"


def _top_rows(rows) -> list[dict]:
    return [{"name": r[0], "wins": r[1], "kills": r[2], "boss_kills": r[3], "points": r[4]} for r in rows]


class NeonStore:
    def __init__(self, url: str, timeout_s: int = 10) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self._schema_ready = False

    async def _connect(self):
        import psycopg  # imported lazily so tests/dev don't need it

        return await psycopg.AsyncConnection.connect(self.url, connect_timeout=self.timeout_s)

    async def begin_match(self, month: str) -> tuple[Usage, list[dict]]:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                if not self._schema_ready:
                    await cur.execute(SCHEMA)
                    self._schema_ready = True
                await cur.execute(_BUMP_SQL, (month, 0, 0, 0))
                usage = Usage(*await cur.fetchone())
                await cur.execute(_TOP_SQL)
                top = _top_rows(await cur.fetchall())
            await conn.commit()
            return usage, top
        finally:
            await conn.close()

    async def end_match(self, month: str, egress: int, seconds: int, result: dict | None) -> tuple[Usage, list[dict]]:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                if not self._schema_ready:
                    await cur.execute(SCHEMA)
                    self._schema_ready = True
                await cur.execute(_BUMP_SQL, (month, egress, seconds, 1 if result else 0))
                usage = Usage(*await cur.fetchone())
                if result:
                    await cur.execute("insert into matches (rounds, winner) values (%s, %s)",
                                      (result["rounds"], result["winner"]))
                    for p in result["players"]:
                        await cur.execute(_PLAYER_SQL, (p["name"], 1 if p["name"] == result["winner"] else 0,
                                                        p["kills"], p["boss_kills"], p["points"]))
                    await cur.execute(_PRUNE_SQL)
                await cur.execute(_TOP_SQL)
                top = _top_rows(await cur.fetchall())
            await conn.commit()
            return usage, top
        finally:
            await conn.close()


class FileStore:
    """Local-dev / test store. Same behaviour as NeonStore, backed by a JSON file (or memory)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self.data = {"usage": {}, "players": {}}
        if path and path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def _bump(self, month: str, egress: int, seconds: int, matches: int) -> Usage:
        u = Usage(**self.data["usage"].get(month, {}))
        u.egress_bytes += egress
        u.db_sessions += 1
        u.match_seconds += seconds
        u.matches += matches
        self.data["usage"][month] = asdict(u)
        return u

    def _top(self) -> list[dict]:
        rows = sorted(self.data["players"].items(), key=lambda kv: (-kv[1]["wins"], -kv[1]["points"]))[:10]
        return [{"name": n, **{k: s[k] for k in ("wins", "kills", "boss_kills", "points")}} for n, s in rows]

    async def begin_match(self, month: str) -> tuple[Usage, list[dict]]:
        async with self._lock:
            u = self._bump(month, 0, 0, 0)
            self._save()
            return u, self._top()

    async def end_match(self, month: str, egress: int, seconds: int, result: dict | None) -> tuple[Usage, list[dict]]:
        async with self._lock:
            u = self._bump(month, egress, seconds, 1 if result else 0)
            if result:
                for p in result["players"]:
                    s = self.data["players"].setdefault(
                        p["name"], {"matches": 0, "wins": 0, "kills": 0, "boss_kills": 0, "points": 0})
                    s["matches"] += 1
                    s["wins"] += 1 if p["name"] == result["winner"] else 0
                    for k in ("kills", "boss_kills", "points"):
                        s[k] += p[k]
            self._save()
            return u, self._top()
