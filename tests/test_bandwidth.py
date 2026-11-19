"""Worst-case bandwidth estimate: 6 players, boss round, full minion camps."""
import random

from server.game.match import FIGHT, Match
from server.net import protocol

GB = 1024 ** 3


def test_full_room_stays_well_inside_free_bandwidth(data, limits):
    m = Match(data, 6, random.Random(3))
    for i in range(6):
        m.add_player(f"p{i}", f"Player{i}", ["ronin", "pyro", "warden"][i % 3])
    m.start()
    m.step(m.timer + 0.01)      # round 1 shop -> fight
    sizes = []
    last_key = None
    dt = 1 / limits.sim_hz
    net_every = max(1, round(limits.sim_hz / limits.net_hz))
    for tick in range(limits.sim_hz * 60):
        if m.phase != FIGHT:
            break
        for i, pid in enumerate(m.players):
            m.command(pid, {"t": "cast", "slot": "q", "x": 800, "y": 450})
        m.step(dt)
        if tick % net_every == 0:
            key = (id(m.world), m.world.pk_version if m.world else -1)       # same rule the Room uses
            send_pk = key != last_key or tick % (limits.sim_hz * 5) == 0
            last_key = key
            shared = protocol.shared_snapshot(m, m.world.fx[:20] if m.world else [], [], tick % 100 == 0,
                                              with_pickups=send_pk)
            if m.world:
                m.world.fx = []
            sizes.extend(len(protocol.snapshot_for(shared, m, p)) for p in m.players.values())
    avg = sum(sizes) / len(sizes)
    rate = limits.sim_hz / net_every
    gb_per_hour = avg * rate * 6 * 3600 / GB
    import json, zlib
    sample = protocol.snapshot_for(protocol.shared_snapshot(m, [], [], False), m, next(iter(m.players.values())))
    print(f'one snapshot: {len(sample)} B raw, {len(zlib.compress(sample.encode()))} B deflated')
    print(f"avg snapshot {avg:.0f} B -> {gb_per_hour:.3f} GB per hour for a full 6-player room (uncompressed)")
    # 3.5 GB cap must allow at least ~10 hours of full-room play per month.
    assert gb_per_hour * 10 < limits.monthly_egress_cap_bytes / GB
