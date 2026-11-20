import json,random
from pathlib import Path
from server.game.hook_wars import HookWarsMatch
from server.net.protocol import shared_snapshot,snapshot_for

def snap(m,p):return json.loads(snapshot_for(shared_snapshot(m,[],[],False,True),m,p))

def test_hook_levels_increase_range_and_width(data):
 m=HookWarsMatch(data,10,random.Random(1));p=m.add_player("a","A","warden");m.add_player("b","B","warden");m.start();p.level=4;u=m.world.units[p.unit_id];m.command("a",{"t":"cast","slot":"q","x":1500,"y":u.y});hook=m.world.hooks[0];assert hook.max_distance==m.cfg["hook"]["range"]+3*m.cfg["leveling"]["range_per_level"];assert hook.radius==m.cfg["hook"]["radius"]+3*m.cfg["leveling"]["radius_per_level"]

def test_pulled_player_gets_local_enemy_side_vision(data):
 m=HookWarsMatch(data,10,random.Random(1));left=m.add_player("l","L","warden");right=m.add_player("r","R","warden");m.start();lu=m.world.units[left.unit_id];ru=m.world.units[right.unit_id];ru.x=lu.x+120;ru.y=lu.y;seen={u[0] for u in snap(m,right)["u"]};assert lu.id in seen and ru.id in seen

def test_dynamic_vision_assets_exist():
 root=Path(__file__).parents[1];js=(root/"client/game.js").read_text(encoding="utf-8");css=(root/"client/style.css").read_text(encoding="utf-8");assert "HOOK LV" in js and "player-displaced" in js;assert "radial-gradient(circle 330px" in css
