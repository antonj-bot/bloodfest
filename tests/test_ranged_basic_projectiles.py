import random
from server.game.match import Match
from server.game.world import MINION
from server.net import protocol


def fight(data, hero):
    m=Match(data,6,random.Random(4));p=m.add_player("p","P",hero);m.start();m.step(m.timer+.01)
    u=m.world.units[p.unit_id];target=next(x for x in m.world.units.values() if x.kind==MINION)
    distance = 20 if data.heroes[hero]["range"] < 120 else 150
    target.x,target.y=u.x+distance,u.y;u.target_id=target.id;u.move_to=None;u.atk_timer=0
    return m,u,target


def test_each_ranged_hero_basic_attack_launches_theme_projectile(data):
    expected={"pyro":"fire_bolt","ranger":"arrow","druid":"thorn","artificer":"arc_bolt"}
    for hero,visual in expected.items():
        m,u,t=fight(data,hero);hp=t.hp;m.world.step(.01)
        assert t.hp==hp and len(m.world.projectiles)==1
        p=m.world.projectiles[0];assert p.visual==visual and p.dmg==u.dmg
        for _ in range(30):m.world.step(.02)
        assert t.hp<hp


def test_melee_heroes_still_hit_instantly(data):
    for hero in ("ronin","warden","reaper"):
        m,u,t=fight(data,hero);hp=t.hp;m.world.step(.01)
        assert t.hp<hp and not m.world.projectiles


def test_random_ranged_enemies_launch_matching_basics(data):
    m,u,_=fight(data,"ronin")
    for variant,visual in (("archer","bone_arrow"),("wisp","arc_bolt")):
        enemy=next(x for x in m.world.units.values() if x.kind==MINION and x.variant==variant)
        for other in m.world.units.values():
            if other.kind == MINION: other.target_id = None; other.atk_timer = 99
        enemy.x,enemy.y=u.x+100,u.y;enemy.home=(enemy.x,enemy.y);enemy.target_id=u.id;enemy.atk_timer=0
        m.world.step(.01);assert any(p.owner_uid==enemy.id and p.visual==visual for p in m.world.projectiles)
        m.world.projectiles.clear()


def test_wire_snapshot_names_basic_projectile_visual(data):
    m,u,t=fight(data,"ranger");m.world.step(.01)
    assert '"arrow"' in protocol.shared_snapshot(m,[],[],False)
