from server.game.world import BOSS, BOSS_TEAM, CREEP_TEAM, HERO, MINION, World

STATS = dict(radius=15, max_hp=100, dmg=10, armor=0, atk_range=40, atk_cd=1, speed=100)


def make(round_s=150):
    return World(1600, 900, round_s)


def test_minions_do_not_fight_each_other_but_attack_boss():
    w = make()
    a = w.spawn(MINION, CREEP_TEAM, 100, 100, aggro=300, **STATS)
    w.spawn(MINION, CREEP_TEAM, 120, 100, aggro=300, **STATS)
    boss = w.spawn(BOSS, BOSS_TEAM, 160, 100, **{**STATS, "max_hp": 10_000})
    for _ in range(40):
        w.step(0.05)
    assert a.target_id == boss.id
    assert boss.hp < 10_000
    assert all(u.target_id in (None, boss.id) for u in w.units.values() if u.kind == MINION)


def test_heroes_are_all_enemies():
    w = make()
    h1 = w.spawn(HERO, "p0", 100, 100, owner="a", **STATS)
    h2 = w.spawn(HERO, "p1", 130, 100, owner="b", **STATS)
    w.command_attack(h1.id, h2.id)
    w.step(0.05)
    assert h2.hp < h2.max_hp


def test_projectile_hits_first_hostile_and_not_owner():
    w = make()
    h = w.spawn(HERO, "p0", 100, 450, owner="a", **STATS)
    m = w.spawn(MINION, CREEP_TEAM, 300, 450, aggro=0, **STATS)
    skill = {"type": "projectile", "cd": 4, "dmg": 50, "speed": 1000, "range": 800, "r": 10}
    assert w.cast(h.id, "q", skill, 800, 450)
    assert not w.cast(h.id, "q", skill, 800, 450)      # on cooldown
    for _ in range(10):
        w.step(0.05)
    assert h.hp == h.max_hp
    assert m.hp < m.max_hp


def test_time_limit_ends_the_round_and_nothing_bleeds_before_it():
    w = make(round_s=5)
    h = w.spawn(HERO, "p0", 100, 100, owner="a", **{**STATS, "max_hp": 5000})
    for _ in range(98):                       # 4.9 s: still inside the time limit
        w.step(0.05)
    assert h.alive and h.hp == h.max_hp and not w.time_up
    for _ in range(10):
        w.step(0.05)
    assert not h.alive and w.time_up
    assert ("timeup",) in w.events
    assert sum(1 for e in w.events if e == ("timeup",)) == 1     # announced once, not every tick


def test_suicide_has_no_killer():
    w = make()
    h = w.spawn(HERO, "p0", 100, 100, owner="a", **STATS)
    w.kill(h.id)
    assert not h.alive
    assert w.events == [("death", h.id, None)]
