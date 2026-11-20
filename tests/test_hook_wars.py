import random
from server.game.hook_wars import HookWarsMatch, LEFT, RIGHT

def test_hook_wars_teams_river_hook_and_score(data):
    m=HookWarsMatch(data,10,random.Random(1))
    a=m.add_player("a","A","warden");b=m.add_player("b","B","warden")
    m.start(); ua=m.world.units[a.unit_id]; ub=m.world.units[b.unit_id]
    assert ua.team==LEFT and ub.team==RIGHT
    m.command("a",{"t":"move","x":m.world.w,"y":ua.y});m.step(5)
    assert ua.x < m.world.mid
    ua.y=ub.y; ub.x=ua.x+300
    m.command("a",{"t":"cast","slot":"q","x":ub.x,"y":ub.y})
    for _ in range(100):m.step(.05)
    assert ub.x < m.world.mid or not ub.alive

def test_hook_wars_respawn_and_win(data):
    m=HookWarsMatch(data,10,random.Random(1));a=m.add_player("a","A","warden");b=m.add_player("b","B","warden");m.start()
    m.cfg["kills_to_win"]=1
    ua=m.world.units[a.unit_id];ub=m.world.units[b.unit_id]
    m.world.damage(ua,ub,99999);m.step(.01)
    assert m.phase=="over" and m.finished["winner"]=="Radiant"
