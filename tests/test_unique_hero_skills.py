import random

from server.config import load_game_data
from server.game.world import HERO, MINION, World


def world(data, hero="ranger"):
    w = World(1600, 900, 60, random.Random(2))
    hdata = data.heroes[hero]
    h = w.spawn(HERO, "p", 300, 450, owner="p", radius=hdata["radius"], max_hp=hdata["hp"], dmg=hdata["dmg"], armor=hdata["armor"], atk_range=hdata["range"], atk_cd=hdata["atk_cd"], speed=hdata["speed"])
    foes=[w.spawn(MINION,"creep",500+i*70,450,variant="goblin",radius=14,max_hp=1000,dmg=0,armor=0,atk_range=0,atk_cd=99,speed=0) for i in range(4)]
    return w,h,foes


def run(w, seconds):
    for _ in range(int(seconds/0.05)): w.step(0.05)


def test_ranger_pierces_three_and_volley_fires_five(data):
    w,h,foes=world(data,"ranger")
    assert w.cast(h.id,"q",data.heroes["ranger"]["skills"]["q"],1000,450)
    run(w,0.55)
    assert sum(f.hp<1000 for f in foes)==3
    h.cds["w"]=0; assert w.cast(h.id,"w",data.heroes["ranger"]["skills"]["w"],1000,450)
    assert len(w.projectiles)==5


def test_ranger_tumble_grants_temporary_haste_and_execute_doubles(data):
    w,h,foes=world(data,"ranger"); base=h.atk_cd
    assert w.cast(h.id,"e",data.heroes["ranger"]["skills"]["e"],500,450); assert h.atk_cd<base
    run(w,4); assert abs(h.atk_cd-base)<1e-6
    target=foes[0]; target.x,target.y,target.hp=570,450,300; target.max_hp=1000; target.target_id=None; target.move_to=None
    h.cds["r"]=0; assert w.cast(h.id,"r",data.heroes["ranger"]["skills"]["r"],900,450); run(w,.5)
    assert target.hp <= 0


def test_reaper_shadowstep_drain_phase_and_pulses(data):
    w,h,foes=world(data,"reaper"); t=foes[0]; h.hp=200
    assert w.cast(h.id,"q",data.heroes["reaper"]["skills"]["q"],t.x,t.y); assert t.hp<1000 and abs(h.x-t.x)<100
    h.cds["w"]=0; before=h.hp; assert w.cast(h.id,"w",data.heroes["reaper"]["skills"]["w"],h.x,h.y); assert h.hp>before
    h.cds["e"]=0; assert w.cast(h.id,"e",data.heroes["reaper"]["skills"]["e"],h.x,h.y); assert h.phased>0
    assert w._nearest_hostile(foes[1],9999) is not h
    h.cds["r"]=0; hp=t.hp; assert w.cast(h.id,"r",data.heroes["reaper"]["skills"]["r"],h.x,h.y); run(w,2); assert t.hp<hp


def test_druid_root_zone_hot_and_bear_form(data):
    w,h,foes=world(data,"druid"); t=foes[0]
    assert w.cast(h.id,"q",data.heroes["druid"]["skills"]["q"],t.x,t.y); run(w,.35); assert t.stunned>1
    h.cds["w"]=0; assert w.cast(h.id,"w",data.heroes["druid"]["skills"]["w"],t.x,t.y); hp=t.hp; run(w,1); assert t.hp<hp and t.speed==0
    h.hp=100; h.cds["e"]=0; assert w.cast(h.id,"e",data.heroes["druid"]["skills"]["e"],h.x,h.y); run(w,1); assert h.hp>100
    base=(h.max_hp,h.dmg,h.armor); h.cds["r"]=0; assert w.cast(h.id,"r",data.heroes["druid"]["skills"]["r"],h.x,h.y); assert h.max_hp>base[0] and h.dmg>base[1] and h.armor>base[2]
    run(w,9); assert round(h.max_hp)==base[0] and round(h.dmg)==base[1] and round(h.armor)==base[2]


def test_artificer_chain_mine_drone_and_beam(data):
    w,h,foes=world(data,"artificer")
    assert w.cast(h.id,"q",data.heroes["artificer"]["skills"]["q"],foes[0].x,foes[0].y); assert sum(f.hp<1000 for f in foes)==4
    h.cds["w"]=0; assert w.cast(h.id,"w",data.heroes["artificer"]["skills"]["w"],foes[0].x,foes[0].y); hp=foes[0].hp; run(w,.8); assert foes[0].hp<hp and foes[0].stunned>0
    h.cds["e"]=0; hp=[f.hp for f in foes]; assert w.cast(h.id,"e",data.heroes["artificer"]["skills"]["e"],h.x,h.y); run(w,1); assert any(f.hp<b for f,b in zip(foes,hp))
    h.cds["r"]=0; hp=[f.hp for f in foes]; assert w.cast(h.id,"r",data.heroes["artificer"]["skills"]["r"],1000,450); assert sum(f.hp<b for f,b in zip(foes,hp))>=2


def test_effect_events_match_skill_families(data):
    expected={"ranger":"wind","reaper":"shadow","druid":"nature","artificer":"arc"}
    for hero,color in expected.items():
        w,h,foes=world(data,hero)
        for slot in "qwer":
            w.cast(h.id,slot,data.heroes[hero]["skills"][slot],foes[0].x,foes[0].y)
        assert any(len(f)>1 and f[1]==color for f in w.fx)


def test_projectile_wire_data_names_the_actual_visual(data):
    from server.game.match import Match
    from server.net import protocol
    m = Match(data, 6, random.Random(9)); p = m.add_player("p", "P", "ranger"); m.start(); m.step(m.timer + .01)
    h = m.world.units[p.unit_id]
    m.world.cast(h.id, "q", data.heroes["ranger"]["skills"]["q"], h.x + 500, h.y)
    row = protocol.shared_snapshot(m, [], [], False)
    assert '"wind","arrow",0' in row
    m.world.projectiles.clear(); h.cds["r"] = 0
    m.world.cast(h.id, "r", data.heroes["ranger"]["skills"]["r"], h.x + 500, h.y)
    assert '"great_arrow"' in protocol.shared_snapshot(m, [], [], False)
