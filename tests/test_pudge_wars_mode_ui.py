from pathlib import Path
from fastapi.testclient import TestClient
from server.main import create_app
from server.store import FileStore

ROOT=Path(__file__).parents[1]

def test_pudge_wars_selector_is_static_and_wired():
    html=(ROOT/"client/index.html").read_text(encoding="utf-8")
    js=(ROOT/"client/game.js").read_text(encoding="utf-8")
    assert 'id="game-mode"' in html
    assert '<option value="hook_wars">Pudge Wars (5v5)</option>' in html
    assert 'id="hook-wars-note"' not in html
    assert 'document.getElementById("game-mode").value' in js
    assert 'initHookWarsModeSelector' not in js

def test_api_really_creates_pudge_wars_room(limits):
    app=create_app(FileStore(None),limits)
    c=TestClient(app)
    r=c.post("/api/rooms?mode=hook_wars")
    assert r.status_code==200
    room=app.state.rooms[r.json()["code"]]
    assert room.mode=="hook_wars"
    assert room.match.mode=="hook_wars"
