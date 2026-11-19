import asyncio
import dataclasses

from server.budget import Budget
from server.store import FileStore


class BrokenStore:
    async def begin_match(self, month):
        raise ConnectionError("neon down")

    async def end_match(self, *a):
        raise ConnectionError("neon down")


def run(coro):
    return asyncio.run(coro)


def test_two_db_sessions_per_match(limits):
    store = FileStore(None)
    b = Budget(store, limits, month_fn=lambda: "2026-11")
    assert run(b.begin_match()).ok
    run(b.end_match(60, {"rounds": 1, "winner": "A", "players": [
        {"name": "A", "hero": "ronin", "points": 3, "kills": 1, "boss_kills": 0, "level": 2}]}))
    assert store.data["usage"]["2026-11"]["db_sessions"] == 2
    assert b.leaderboard[0]["name"] == "A"


def test_warm_server_uses_one_db_session_per_match(limits):
    store = FileStore(None)
    b = Budget(store, limits, month_fn=lambda: "2026-11")
    result = {"rounds": 1, "winner": "A", "players": [
        {"name": "A", "hero": "ronin", "points": 1, "kills": 0, "boss_kills": 0, "level": 1}]}
    for _ in range(3):
        assert run(b.begin_match()).ok
        run(b.end_match(10, result))
    # 1 cold-start read + 3 end-of-match writes
    assert store.data["usage"]["2026-11"]["db_sessions"] == 4


def test_refuses_when_bandwidth_spent(limits):
    lim = dataclasses.replace(limits, monthly_egress_cap_bytes=1000)
    b = Budget(FileStore(None), lim, month_fn=lambda: "2026-11")
    b.meter(5000)
    v = run(b.begin_match())
    assert not v.ok and "bandwidth" in v.reason


def test_bandwidth_persists_across_restart(limits):
    store = FileStore(None)
    lim = dataclasses.replace(limits, monthly_egress_cap_bytes=10_000)
    b1 = Budget(store, lim, month_fn=lambda: "2026-11")
    run(b1.begin_match())
    b1.meter(20_000)
    run(b1.end_match(1, None))
    b2 = Budget(store, lim, month_fn=lambda: "2026-11")   # "restarted" server
    assert not run(b2.begin_match()).ok


def test_refuses_when_db_sessions_spent(limits):
    lim = dataclasses.replace(limits, monthly_db_sessions_cap=2)
    b = Budget(FileStore(None), lim, month_fn=lambda: "2026-11")
    assert run(b.begin_match()).ok          # session 1 (+1 reserved for end)
    run(b.end_match(1, None))               # session 2
    assert not run(b.begin_match()).ok


def test_fail_closed_when_db_unreachable(limits):
    b = Budget(BrokenStore(), limits)
    assert not run(b.begin_match()).ok


def test_new_month_resets(limits):
    store = FileStore(None)
    lim = dataclasses.replace(limits, monthly_egress_cap_bytes=10_000)
    month = ["2026-11"]
    b = Budget(store, lim, month_fn=lambda: month[0])
    run(b.begin_match())
    b.meter(20_000)
    run(b.end_match(1, None))
    month[0] = "2026-12"
    assert run(b.begin_match()).ok
