import random
from pathlib import Path
from server.game.hook_wars import HookWarsMatch

def test_potions_move_and_can_be_hooked(data):
 m=HookWarsMatch(data,10,random.Random(2));a=m.add_player("a","A","warden");m.add_player("b","B","warden");m.start();w=m.world;w.potion_clock=0;m.step(.1);p=next(iter(w.pickups.values()));x,y=p.x,p.y;m.step(.5);assert (p.x,p.y)!=(x,y);u=w.units[a.unit_id];p.x=u.x+160;p.y=u.y;w.cast_hook(u.id,p.x,p.y,m.cfg["hook"]);[m.step(.03) for _ in range(80)];assert p.x < w.mid

def test_polish_assets_present():
 root=Path(__file__).parents[1];js=(root/"client/game.js").read_text(encoding="utf-8");css=(root/"client/style.css").read_text(encoding="utf-8");assert "pudge-hook-trails" in js and "pudge-fog" in js;assert "ENEMY SIDE" in css and "top:18px" in css
