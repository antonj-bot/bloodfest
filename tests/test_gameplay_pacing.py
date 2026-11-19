import random
from server.game.match import Match, FIGHT, ROUND_END, SHOP


def arena(data, count=2):
    m = Match(data, 6, random.Random(4))
    for i in range(count):
        m.add_player(str(i), "Player" + str(i), "ronin")
    m.start()
    m.step(m.timer + 0.01)
    return m


def test_round_ends_at_the_time_limit_even_with_huge_health(data):
    m = arena(data)
    for u in m.world.alive_heroes():
        u.hp = 1e12
        u.max_hp = 1
        u.speed = 0
    for _ in range(1720):
        m.step(0.05)
        if m.phase != FIGHT:
            break
    assert m.phase == ROUND_END
    assert m.timer == data.game["round_end_seconds"]
    assert not m.world.alive_heroes()


def test_dead_player_cannot_move_or_cast(data):
    m = arena(data)
    m.command("0", {"t":"suicide"})
    u = m.world.units[m.players["0"].unit_id]
    pos = (u.x, u.y)
    m.command("0", {"t":"move", "x":800, "y":450})
    m.command("0", {"t":"cast", "slot":"q", "x":800, "y":450})
    m.step(0.05)
    assert not u.alive and (u.x, u.y) == pos
    assert m.phase == FIGHT


def test_shop_ready_skips_wait(data):
    m = Match(data, 6)
    m.add_player("a", "A", "ronin")
    m.start()
    assert m.phase == SHOP
    m.set_ready("a")
    m.step(0.05)
    assert m.phase == FIGHT


def test_boss_enrages_before_time_runs_out(data):
    assert data.bosses["abilities"]["enrage"]["after_s"] < data.game["round_seconds"]
