import random

from server.game.match import FIGHT, Match
from server.game.world import BOSS, BOSS_TEAM, CREEP_TEAM, HERO, MINION, World
from server.net import protocol

HERO_STATS = dict(radius=18, max_hp=1000, dmg=10, armor=0, atk_range=40, atk_cd=1, speed=100)
BOSS_STATS = dict(radius=46, max_hp=50_000, dmg=60, armor=0, atk_range=90, atk_cd=1.4, speed=0, aggro=600)
POTIONS = {"spawn_min_s": 5, "spawn_max_s": 5, "max_on_ground": 3, "lifetime_s": 20,
           "heal_pct": 0.3, "minion_drop_chance": 1.0, "pickup_pad": 18}


def arena(data, n, heroes=1, potions=None, seed=1):
    w = World(1600, 900, 999, random.Random(seed), potion_cfg=potions)
    hs = [w.spawn(HERO, f"p{i}", 300 + 400 * i, 450, owner=f"o{i}", **HERO_STATS) for i in range(heroes)]
    boss = w.spawn(BOSS, BOSS_TEAM, 800, 450, home=(800, 450), **BOSS_STATS)
    b = data.bosses
    w.boss_abilities = dict(b["abilities"], index=n, hp_scale=1, dmg_scale=1)
    return w, hs, boss


def run(w, seconds, dt=0.05):
    for _ in range(int(seconds / dt)):
        w.step(dt)


# ------------------------------------------------------------------ boss skills
def test_pounce_is_telegraphed_then_lands(data):
    w, (h,), boss = arena(data, 1)
    h.x, h.y = 300, 450                      # 500 away: inside pounce range, outside min range
    w.step(0.05)
    assert boss.busy > 0                      # winding up, standing still
    tele = [f for f in w.fx if f[0] == "t"]
    assert len(tele) == 1 and tele[0][3] == data.bosses["abilities"]["pounce"]["r"]
    hp0 = h.hp
    run(w, 0.5)
    assert h.hp == hp0                        # warning phase: no damage yet
    h.x, h.y = 300, 450                       # player stays put -> gets hit
    run(w, 0.6)
    assert h.hp < hp0 and h.stunned > 0
    assert abs(boss.x - 300) < 1             # the boss leapt to the marked spot


def test_player_can_dodge_the_telegraph(data):
    w, (h,), boss = arena(data, 1)
    h.x, h.y = 300, 450
    w.step(0.05)
    h.x, h.y = 60, 450                        # step out of the ring
    run(w, 1.2)
    assert h.hp == h.max_hp


def test_stun_interrupts_pounce(data):
    w, (h,), boss = arena(data, 1)
    h.x, h.y = 300, 450
    w.step(0.05)
    boss.stunned = 5.0                        # e.g. Warden's hook
    run(w, 1.5)
    assert boss.x == 800 and h.hp == h.max_hp


def test_skills_unlock_by_boss_number(data):
    def casts(n, seconds=30):
        w, (h,), boss = arena(data, n)
        h.x, h.y = 700, 450                   # near the boss so slam is possible
        h.max_hp = h.hp = 1e9
        seen = set()
        for _ in range(int(seconds / 0.05)):
            w.step(0.05)
            for k in ("pounce", "slam", "summon", "meteor"):
                if boss.cds.get(k, 0) > 0:
                    seen.add(k)
            h.x, h.y = (700, 450) if w.t % 10 < 5 else (250, 450)
        return seen
    assert casts(1) == {"pounce"}
    assert "slam" in casts(2) and "summon" not in casts(2)
    assert "summon" in casts(3) and "meteor" not in casts(3)
    assert "meteor" in casts(4)


def test_meteor_rain_targets_every_hero_and_scales(data):
    w, hs, boss = arena(data, 4, heroes=2)
    for h in hs:
        h.max_hp = h.hp = 1e9
    boss.cds.update({"pounce": 99, "slam": 99, "summon": 99})
    w.step(0.05)
    tele = [f for f in w.fx if f[0] == "t"]
    assert len(tele) == 3                     # base count at boss 4
    w2, hs2, boss2 = arena(data, 5, heroes=2)
    boss2.cds.update({"pounce": 99, "slam": 99, "summon": 99})
    w2.step(0.05)
    assert len([f for f in w2.fx if f[0] == "t"]) == 4   # one more at boss 5


def test_bloodlust_heals_boss_from_boss_five(data):
    w4, _, b4 = arena(data, 4); w4.step(0.05)
    w5, _, b5 = arena(data, 5); w5.step(0.05)
    assert b4.lifesteal == 0 and b5.lifesteal == data.bosses["abilities"]["bloodlust"]["lifesteal"]


# ------------------------------------------------------------------ potions
def test_potions_spawn_randomly_and_heal(data):
    w, (h,), boss = arena(data, 1, potions=POTIONS)
    boss.cds["gcd"] = 1e9
    h.hp = 400
    run(w, 5.2)
    pots = [p for p in w.pickups.values() if p.kind == "potion"]
    assert len(pots) == 1
    h.x, h.y = pots[0].x, pots[0].y
    w.step(0.05)
    assert h.hp == 400 + 0.3 * h.max_hp and not w.pickups
    assert any(f[0] == "h" for f in w.fx)


def test_full_health_hero_leaves_the_potion(data):
    w, (h,), boss = arena(data, 1, potions=POTIONS)
    boss.cds["gcd"] = 1e9
    pk = w.add_potion(h.x, h.y)
    w.step(0.05)
    assert pk.id in w.pickups                 # not wasted at full health
    h.hp = 10
    w.step(0.05)
    assert pk.id not in w.pickups


def test_potions_expire_and_are_capped(data):
    w, (h,), boss = arena(data, 1, potions=POTIONS)
    boss.cds["gcd"] = 1e9
    for _ in range(6):
        w.add_potion(100, 100)
    assert len(w.pickups) == 3
    run(w, 4.9)                               # next random spawn is capped too
    assert len(w.pickups) <= 3
    w2, (h2,), b2 = arena(data, 1, potions=POTIONS)
    b2.cds["gcd"] = 1e9
    w2.add_potion(100, 100)
    pot = next(iter(w2.pickups.values()))
    w2.potion_timer = 1e9                     # stop new spawns, watch this one expire
    run(w2, POTIONS["lifetime_s"] + 0.5)
    assert pot.id not in w2.pickups


def test_minions_can_drop_potions(data):
    w = World(1600, 900, 999, random.Random(2), potion_cfg=POTIONS)
    h = w.spawn(HERO, "p0", 100, 100, owner="o", **HERO_STATS)
    m = w.spawn(MINION, CREEP_TEAM, 500, 500, **{**HERO_STATS, "max_hp": 10})
    w.damage(h.id, m, 1e6)
    assert any(p.kind == "potion" and (p.x, p.y) == (500, 500) for p in w.pickups.values())


# ------------------------------------------------------------------ boss loot
def fight(data, rng, n=2):
    m = Match(data, 6, rng)
    for i in range(n):
        m.add_player(f"p{i}", f"P{i}", "ronin")
    m.start()
    m.step(m.timer + 0.01)
    assert m.phase == FIGHT
    return m


def boss_round(data, rng):
    """Play round 1 out (everyone suicides), then walk shop -> fight into boss round 2."""
    m = fight(data, rng)
    for pid in list(m.players):
        m.command(pid, {"t": "suicide"})
    m.step(0.05)                              # round 1 over
    m.step(m.timer + 0.01)                    # round-end pause -> shop 2
    assert m.round == 2 and m.phase == "shop"
    m.step(m.timer + 0.01)                    # shop -> fight
    assert m.is_boss_round() and m.phase == FIGHT
    return m


def test_boss_drops_loot_and_first_hero_to_touch_it_gets_it(data, rng):
    m = boss_round(data, rng)
    w = m.world
    boss = next(u for u in w.units.values() if u.kind == BOSS)
    assert w.boss_loot == data.bosses["loot"][0]
    h0 = w.units[m.players["p0"].unit_id]
    h0.max_hp = h0.hp = 1e9
    w.damage(h0.id, boss, 1e9, true_dmg=True)
    m.step(0.05)
    loot = [p for p in w.pickups.values() if p.kind == "item"]
    assert len(loot) == 1 and loot[0].item == "gorefang"
    h1 = w.units[m.players["p1"].unit_id]
    dmg0, ls0 = h1.dmg, h1.lifesteal
    h1.x, h1.y = loot[0].x, loot[0].y
    m.step(0.05)
    assert "gorefang" in m.players["p1"].items and not [p for p in w.pickups.values() if p.kind == "item"]
    assert h1.dmg == dmg0 + 20 and h1.lifesteal == ls0 + 0.12      # applied instantly, mid-fight
    assert any("claimed" in line for line in m.feed)


def test_item_stays_on_floor_when_pack_is_full(data, rng):
    m = boss_round(data, rng)
    w = m.world
    p = m.players["p1"]
    p.items = ["blade"] * data.game["max_items"]
    pk = w.add_pickup("item", 500, 500, item="cleaver")
    h = w.units[p.unit_id]
    h.x, h.y = 500, 500
    for _ in range(40):                       # 2 s of standing on it
        m.step(0.05)
    assert pk.id in w.pickups and "cleaver" not in p.items
    assert sum("pack is full" in line for line in m.feed) == 1      # warned once, not spammed


def test_loot_item_carries_into_next_round_stats(data, rng):
    m = fight(data, rng)
    p = m.players["p0"]
    base = m.hero_stats(p)["max_hp"]
    p.items.append("ashheart")
    assert m.hero_stats(p)["max_hp"] == base + 600 and m.hero_stats(p)["armor"] == data.heroes["ronin"]["armor"] + 6


def test_boss_only_items_cannot_be_bought(data, rng):
    m = Match(data, 6, rng)
    m.add_player("a", "A", "ronin")
    m.start()
    m.players["a"].gold = 99999
    assert m.buy("a", "sovereign") == "That item only drops from bosses."


def test_boss_announcement_lists_skills_and_drop(data, rng):
    m = boss_round(data, rng)
    text = " | ".join(m.feed)
    assert "Skills: Pounce" in text and "Slam" not in text      # boss #1 only has Pounce
    assert "Drops: Gorehound's Fang" in text


def test_every_boss_has_a_loot_item(data):
    for item_id in data.bosses["loot"]:
        assert data.items[item_id].get("drop_only")


# ------------------------------------------------------------------ network
def test_pickups_are_sent_only_when_asked(data, rng):
    m = fight(data, rng)
    m.world.add_pickup("item", 400, 300, item="gorefang")
    m.world.add_potion(10, 10) if m.world.potion_cfg else None
    quiet = protocol.shared_snapshot(m, [], [], False)
    loud = protocol.shared_snapshot(m, [], [], False, with_pickups=True)
    assert '"pk"' not in quiet and '"pk"' in loud
    assert [1, 400, 300, "gorefang"] == protocol.pickups(m)[0][1:]


def test_potions_keep_appearing_late_in_the_round(data):
    w = World(1600, 900, 60, random.Random(3), potion_cfg=POTIONS)
    w.spawn(HERO, "p0", 100, 100, owner="o", **{**HERO_STATS, "max_hp": 1e9})
    run(w, 40)
    w.pickups.clear()
    run(w, 6)
    assert any(p.kind == "potion" for p in w.pickups.values())
