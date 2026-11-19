import collections
import random

from server.game.match import Match
from server.game.world import HERO, MINION
from server.net import protocol

NEW_HEROES = {"ranger", "reaper", "druid", "artificer"}


def match(data, seed=1, hero="ranger"):
    m = Match(data, 6, random.Random(seed))
    p = m.add_player("p", "P", hero)
    m.start(); m.step(m.timer + 0.01)
    return m, p


def test_seven_complete_heroes(data):
    assert set(data.heroes) == {"ronin", "pyro", "warden"} | NEW_HEROES
    for hero_id, hero in data.heroes.items():
        assert set(hero["skills"]) == {"q", "w", "e", "r"}
        assert all(isinstance(s["type"], str) and s["type"] for s in hero["skills"].values())
        assert hero["hp"] > 0 and hero["dmg"] > 0 and hero["speed"] > 0


def test_all_new_hero_skills_cast(data):
    for hero_id in NEW_HEROES:
        m = Match(data, 6, random.Random(3)); p = m.add_player("p", "P", hero_id); m.start(); m.step(m.timer + 0.01)
        u = m.world.units[p.unit_id]
        for slot in "qwer":
            assert m.world.cast(u.id, slot, data.heroes[hero_id]["skills"][slot], u.x + 200, u.y)


def test_random_enemy_mix_is_deterministic_per_seed(data):
    a, _ = match(data, seed=8); b, _ = match(data, seed=8)
    va = [u.variant for u in a.world.units.values() if u.kind == MINION]
    vb = [u.variant for u in b.world.units.values() if u.kind == MINION]
    assert va == vb
    assert set(va) <= {v["id"] for v in data.game["enemy_types"]}
    assert len(set(va)) >= 3


def test_enemy_weights_create_all_variants_over_many_camps(data):
    counts = collections.Counter()
    for seed in range(20):
        m, _ = match(data, seed=seed)
        counts.update(u.variant for u in m.world.units.values() if u.kind == MINION)
    assert set(counts) == {"goblin", "brute", "archer", "wisp"}
    assert counts["goblin"] > counts["brute"]       # weights 35 vs 20 are reflected over 360 spawns


def test_enemy_variants_have_distinct_stats(data):
    m = Match(data, 6)
    by_id = {v["id"]: m.minion_stats(v) for v in data.game["enemy_types"]}
    assert by_id["brute"]["max_hp"] > by_id["goblin"]["max_hp"] > by_id["wisp"]["max_hp"]
    assert by_id["archer"]["atk_range"] == 300
    assert by_id["wisp"]["speed"] > by_id["goblin"]["speed"] > by_id["brute"]["speed"]


def test_enemy_variant_and_new_hero_are_in_wire_snapshot(data):
    m, p = match(data, seed=4, hero="artificer")
    shared = protocol.shared_snapshot(m, [], [], True)
    assert '"artificer"' in shared                  # scoreboard hero id
    assert any(v in shared for v in ('"goblin"', '"brute"', '"archer"', '"wisp"'))


def test_harder_enemies_pay_more(data):
    m, p = match(data, seed=2)
    w = m.world; hero = w.units[p.unit_id]
    brute = next(u for u in w.units.values() if u.kind == MINION and u.variant == "brute")
    before_gold, before_xp = p.gold, p.xp
    w.damage(hero.id, brute, 1e9, true_dmg=True); m.step(0.01)
    assert p.gold - before_gold > data.game["minion"]["gold"]
    assert p.xp - before_xp > data.game["minion"]["xp"]
