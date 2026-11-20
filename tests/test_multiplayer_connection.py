from fastapi.testclient import TestClient
from server.main import create_app
from server.store import FileStore
from starlette.websockets import WebSocketDisconnect


def test_two_players_can_join_same_lobby(limits):
    app = create_app(FileStore(None), limits)
    c = TestClient(app)
    code = c.post("/api/rooms").json()["code"]
    with c.websocket_connect(f"/ws/{code}?name=Host&hero=ronin") as host:
        assert host.receive_json()["t"] == "hello"
        first = host.receive_json()
        assert first["t"] == "lobby" and len(first["players"]) == 1
        with c.websocket_connect(f"/ws/{code}?name=Friend&hero=pyro") as friend:
            assert friend.receive_json()["t"] == "hello"
            # Joining broadcasts the same two-player lobby to both sockets.
            friend_lobby = friend.receive_json()
            host_lobby = host.receive_json()
            assert friend_lobby["t"] == host_lobby["t"] == "lobby"
            assert {p[1] for p in friend_lobby["players"]} == {"Host", "Friend"}
            assert len(app.state.rooms[code].clients) == 2


def test_unknown_room_uses_explicit_close_code(limits):
    c = TestClient(create_app(FileStore(None), limits))
    with c.websocket_connect("/ws/ZZZZZ?name=X&hero=ronin") as ws:
        assert ws.receive_json()["msg"].startswith("Room not found")
        
        try:
            ws.receive_text()
        except WebSocketDisconnect as exc:
            assert exc.code == 4001
            assert exc.reason == "room not found"
