import json
import random
from server.game.hook_wars import HookWarsMatch
from server.net.protocol import shared_snapshot, snapshot_for

def _snap(match, player):
    shared=shared_snapshot(match, [], [], False, False)
    return json.loads(snapshot_for(shared, match, player))

def test_pudge_wars_blind_side_filters_enemy_territory(data):
    m=HookWarsMatch(data,10,random.Random(1))
    left=m.add_player("l","Left","warden")
    right=m.add_player("r","Right","warden")
    m.start()
    lu=m.world.units[left.unit_id]; ru=m.world.units[right.unit_id]
    ls=_snap(m,left); rs=_snap(m,right)
    assert lu.id in {u[0] for u in ls["u"]}
    assert ru.id not in {u[0] for u in ls["u"]}
    assert ru.id in {u[0] for u in rs["u"]}
    assert lu.id not in {u[0] for u in rs["u"]}

def test_pudge_wars_pulled_enemy_becomes_visible(data):
    m=HookWarsMatch(data,10,random.Random(1))
    left=m.add_player("l","Left","warden")
    right=m.add_player("r","Right","warden")
    m.start()
    ru=m.world.units[right.unit_id]
    ru.x=m.world.mid-m.world.river_w/2-30
    assert ru.id in {u[0] for u in _snap(m,left)["u"]}

def test_normal_bloodfest_snapshot_is_not_filtered(data):
    from server.game.match import Match
    m=Match(data,6,random.Random(1))
    a=m.add_player("a","A","warden"); b=m.add_player("b","B","warden")
    m.start()
    # This test targets snapshot filtering, not the shop countdown.
    m._begin_fight()
    snap=_snap(m,a)
    ids={u[0] for u in snap["u"]}
    assert a.unit_id is not None and a.unit_id in ids
    assert b.unit_id is not None and b.unit_id in ids
