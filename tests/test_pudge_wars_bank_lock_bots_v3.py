import random
from fastapi.testclient import TestClient
from server.game.hook_wars import HookWarsMatch,LEFT
from server.main import create_app
from server.store import FileStore

def test_captured_player_is_locked_to_enemy_bank(data):
 m=HookWarsMatch(data,10,random.Random(1));m.add_player("a","A","warden");b=m.add_player("b","B","warden");m.start();u=m.world.units[b.unit_id];u.x=300;m.command("b",{"t":"move","x":1500,"y":u.y});m.step(3);assert u.x<m.world.mid;m.command("b",{"t":"cast","slot":"e","x":1500,"y":u.y});assert u.x<m.world.mid

def test_bots_are_balanced_and_spawn(data):
 m=HookWarsMatch(data,10,random.Random(1));bots=[m.add_bot(LEFT if i%2==0 else "dire") for i in range(4)];assert [p.slot%2 for p in bots]==[0,1,0,1];m.start();assert all(p.unit_id is not None for p in bots)

def test_create_room_with_bots(limits):
 app=create_app(FileStore(None),limits);c=TestClient(app);res=c.post("/api/rooms?mode=hook_wars&bots=3");assert res.status_code==200;room=app.state.rooms[res.json()["code"]];assert len(room.match.bot_pids)==3
