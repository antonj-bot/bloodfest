from fastapi.testclient import TestClient
from server.main import create_app
from server.store import FileStore


def _until_snapshot(ws, limit=80):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("t") == "s":
            return msg
    raise AssertionError("no snapshot")


def test_player_can_join_after_match_started(limits):
    c = TestClient(create_app(FileStore(None), limits))
    code = c.post("/api/rooms").json()["code"]
    with c.websocket_connect(f"/ws/{code}?name=Host&hero=ronin") as host:
        assert host.receive_json()["t"] == "hello"
        assert host.receive_json()["t"] == "lobby"
        host.send_json({"t":"start"})
        _until_snapshot(host)
        with c.websocket_connect(f"/ws/{code}?name=Late&hero=ranger") as late:
            assert late.receive_json()["t"] == "hello"
            snap = _until_snapshot(late)
            assert snap["ph"] in {"shop", "fight", "round_end", "over"}
            room = c.app.state.rooms[code]
            p = next(p for p in room.match.players.values() if p.name == "Late")
            assert p.connected
            if room.match.phase == "fight":
                assert p.unit_id is not None
                assert room.match.world.units[p.unit_id].alive


def test_late_join_still_respects_room_capacity(limits):
    import dataclasses
    lim = dataclasses.replace(limits, max_players_per_room=1)
    c = TestClient(create_app(FileStore(None), lim))
    code = c.post("/api/rooms").json()["code"]
    with c.websocket_connect(f"/ws/{code}?name=Host&hero=ronin") as host:
        host.receive_json(); host.receive_json(); host.send_json({"t":"start"})
        with c.websocket_connect(f"/ws/{code}?name=Extra&hero=pyro") as extra:
            assert extra.receive_json()["t"] == "err"
