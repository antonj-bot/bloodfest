from server.game.match import FIGHT, LOBBY, OVER, ROUND_END, SHOP, Match
from server.game.world import BOSS, HERO


def started(data, rng, n=2):
    m = Match(data, 6, rng)
    for i in range(n):
        m.add_player(f"p{i}", f"P{i}", "ronin")
    m.start()
    return m


def to_fight(m):
    m.step(m.timer + 0.01)
    assert m.phase == FIGHT


def kill_all_heroes(m, order):
    for pid in order:
        m.command(pid, {"t": "suicide"})
        m.step(0.05)


def test_boss_every_second_round(data, rng):
    m = Match(data, 6, rng)
    assert [m.is_boss_round(r) for r in range(1, 7)] == [False, True, False, True, False, True]
    assert [m.boss_index(r) for r in (2, 4, 6)] == [1, 2, 3]


def test_boss_gets_stronger(data, rng):
    m = Match(data, 6, rng)
    b1, b2, b3 = (m.boss_stats(n, 2) for n in (1, 2, 3))
    assert b1["max_hp"] < b2["max_hp"] < b3["max_hp"]
    assert b1["dmg"] < b2["dmg"] < b3["dmg"]
    assert m.boss_stats(1, 4)["max_hp"] > b1["max_hp"]     # more players = beefier boss


def test_round_ends_only_when_all_heroes_dead_and_last_gets_points(data, rng):
    m = started(data, rng)
    to_fight(m)
    m.command("p0", {"t": "suicide"})
    m.step(0.05)
    assert m.phase == FIGHT                     # p1 still alive -> round continues
    m.command("p1", {"t": "suicide"})
    m.step(0.05)
    assert m.phase == ROUND_END
    assert m.players["p1"].points == data.game["rewards"]["survivor_points"]
    assert m.players["p0"].points == 0


def test_boss_spawns_in_round_two(data, rng):
    m = started(data, rng)
    to_fight(m)
    assert not any(u.kind == BOSS for u in m.world.units.values())
    kill_all_heroes(m, ["p0", "p1"])
    m.step(m.timer + 0.01)
    assert m.phase == SHOP and m.round == 2
    to_fight(m)
    assert any(u.kind == BOSS for u in m.world.units.values())


def test_full_match_finishes_and_returns_to_lobby(data, rng):
    m = started(data, rng)
    for _ in range(data.game["rounds_total"]):
        to_fight(m)
        kill_all_heroes(m, ["p0", "p1"])
        m.step(m.timer + 0.01)
    assert m.phase == OVER and m.finished["rounds"] == data.game["rounds_total"]
    m.step(m.timer + 0.01)
    assert m.phase == LOBBY


def test_shop_and_items_apply(data, rng):
    m = started(data, rng, n=1)
    base = m.hero_stats(m.players["p0"])
    assert m.buy("p0", "blade") is None
    assert m.hero_stats(m.players["p0"])["dmg"] == base["dmg"] + 12
    assert m.buy("p0", "heart") == "Not enough gold."


def test_hero_kill_rewards(data, rng):
    m = started(data, rng)
    to_fight(m)
    w = m.world
    a, b = w.units[m.players["p0"].unit_id], w.units[m.players["p1"].unit_id]
    gold_before = m.players["p0"].gold
    w.damage(a.id, b, 1e9, true_dmg=True)
    m.step(0.01)
    assert m.players["p0"].kills == 1
    assert m.players["p0"].points == data.game["rewards"]["hero_kill"]["points"]
    assert m.players["p0"].gold > gold_before


def test_leaving_mid_fight_counts_as_death(data, rng):
    m = started(data, rng)
    to_fight(m)
    m.remove_player("p0")
    m.step(0.05)
    assert not m.world.units[m.players["p0"].unit_id].alive


def test_aborted_match_has_no_winner(data, rng):
    m = started(data, rng)
    m.abort("everyone left")
    assert m.phase == OVER and m.finished["winner"] is None and m.finished["aborted"]
