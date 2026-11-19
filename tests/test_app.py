import dataclasses

from fastapi.testclient import TestClient

from server.main import create_app
from server.store import FileStore


class ExplodingStore(FileStore):
    """Proves HTTP endpoints never touch the database."""
    calls = 0

    async def begin_match(self, month):
        ExplodingStore.calls += 1
        return await super().begin_match(month)


def test_http_routes_never_touch_db(limits):
    app = create_app(ExplodingStore(None), limits)
    c = TestClient(app)
    for path in ("/", "/health", "/api/status", "/api/leaderboard", "/static/game.js"):
        assert c.get(path).status_code == 200
    assert ExplodingStore.calls == 0


def test_room_cap(limits):
    lim = dataclasses.replace(limits, max_rooms=1)
    c = TestClient(create_app(FileStore(None), lim))
    assert c.post("/api/rooms").status_code == 200
    assert c.post("/api/rooms").status_code == 503


def test_join_start_and_snapshot_is_small(limits):
    lim = dataclasses.replace(limits, sim_hz=20, net_hz=10)
    store = FileStore(None)
    app = create_app(store, lim)
    c = TestClient(app)
    code = c.post("/api/rooms").json()["code"]
    with c.websocket_connect(f"/ws/{code}?name=Anton&hero=pyro") as ws:
        hello = ws.receive_json()
        assert hello["t"] == "hello" and hello["code"] == code
        assert ws.receive_json()["t"] == "lobby"
        ws.send_json({"t": "start"})
        snap = None
        for _ in range(50):
            raw = ws.receive_text()
            if raw.startswith('{"t":"s"'):
                snap = raw
                if '"ph":"shop"' in raw:
                    break
        assert snap is not None
        assert len(snap) < 2000
    # Everyone left -> match ended -> metered bytes were flushed to the store.
    month = next(iter(store.data["usage"]))
    assert store.data["usage"][month]["egress_bytes"] > 0
    assert store.data["usage"][month]["db_sessions"] == 2


def test_unknown_room(limits):
    c = TestClient(create_app(FileStore(None), limits))
    with c.websocket_connect("/ws/ZZZZZ") as ws:
        assert ws.receive_json()["t"] == "err"
