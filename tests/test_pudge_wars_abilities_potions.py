import random
from server.game.hook_wars import HookWarsMatch

def make(data):
 m=HookWarsMatch(data,10,random.Random(1));a=m.add_player("a","A","warden");b=m.add_player("b","B","warden");m.start();return m,a,b

def test_blink_stays_on_bank_and_cools_down(data):
 m,a,_=make(data);u=m.world.units[a.unit_id];old=u.x;m.command("a",{"t":"cast","slot":"e","x":1500,"y":u.y});assert u.x>old and u.x<m.world.mid;assert u.cds["e"]>0

def test_random_potions_spawn_and_apply(data):
 m,a,_=make(data);m.world.potion_clock=0;m.step(.1);assert m.world.pickups
 p=next(iter(m.world.pickups.values()));u=m.world.units[a.unit_id];p.x,p.y=u.x,u.y;u.hp=100;m.step(.1);assert not m.world.pickups and (u.hp>100 or u.shield>0 or u.cds.get("e",0)==0)

def test_pudge_client_hud_exists():
 from pathlib import Path
 root=Path(__file__).parents[1];js=(root/"client/game.js").read_text(encoding="utf-8");css=(root/"client/style.css").read_text(encoding="utf-8");assert "MEAT HOOK" in js and "BLINK" in js and "Random potions" in js;assert "#pudge-skill-hud" in css
