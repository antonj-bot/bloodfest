"""Compact wire format. Bandwidth is the scarcest free resource (Render: 5 GB/month),
so snapshots are short arrays of integers instead of verbose objects.

Snapshot (server -> client, net_hz times per second while a match runs):
  {"t":"s","ph":phase,"rd":round,"boss":0|1,"tm":seconds,
   "u":[[id,kind,x,y,hp%,slot,flags],...],   flags: 1=stunned 2=shielded
   "pr":[[x,y,r],...],                        projectiles
   "fx":[...], "feed":[...], "sb":[...],      only when present
   "me":[unit_id,gold,level,xp%,cdQ,cdW,cdE,cdR,[items]]}   cds in tenths of a second
"""
from __future__ import annotations

import json

from ..game.match import FIGHT, Match, Player
from ..game.world import HERO


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


def shared_snapshot(match: Match, fx: list, feed: list, with_scoreboard: bool) -> str:
    """Everything every player sees. Returned as a JSON *fragment* (no braces)."""
    w = match.world
    slot_of = {p.pid: p.slot for p in match.players.values()}
    units, projs, tm = [], [], int(max(0, match.timer))
    if match.phase == FIGHT and w is not None:
        for u in w.units.values():
            if not u.alive:
                continue
            flags = (1 if u.stunned > 0 else 0) | (2 if u.shield > 0 else 0)
            units.append([u.id, u.kind, round(u.x), round(u.y), max(1, round(100 * u.hp / u.max_hp)),
                          slot_of.get(u.owner, -1) if u.kind == HERO else -1, flags])
        projs = [[round(p.x), round(p.y), round(p.radius)] for p in w.projectiles]
        tm = int(max(0, w.storm_at - w.t))   # countdown to the storm
    body = {"ph": match.phase, "rd": match.round, "boss": int(match.is_boss_round()), "tm": tm,
            "u": units, "pr": projs}
    if fx:
        body["fx"] = fx
    if feed:
        body["feed"] = feed
    if with_scoreboard:
        body["sb"] = scoreboard(match)
    return dumps(body)[1:-1]


def scoreboard(match: Match) -> list:
    rows = []
    w = match.world
    for p in sorted(match.players.values(), key=lambda p: p.slot):
        alive = 0
        if w is not None and p.unit_id is not None:
            u = w.units.get(p.unit_id)
            alive = int(bool(u and u.alive))
        rows.append([p.slot, p.name, p.hero, p.level, p.points, p.kills, alive, int(p.connected)])
    return rows


def private_part(match: Match, p: Player) -> str:
    uid, cds = 0, [0, 0, 0, 0]
    w = match.world
    if w is not None and p.unit_id is not None:
        u = w.units.get(p.unit_id)
        if u and u.alive:
            uid = u.id
            cds = [int(u.cds.get(s, 0) * 10) for s in ("q", "w", "e", "r")]
    xp_pct = int(100 * p.xp / match.xp_needed(p.level))
    return dumps([uid, p.gold, p.level, xp_pct, *cds, p.items])


def snapshot_for(shared: str, match: Match, p: Player) -> str:
    return '{"t":"s",' + shared + ',"me":' + private_part(match, p) + "}"
