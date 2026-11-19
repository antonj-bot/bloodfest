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
import math

from ..game.match import FIGHT, Match, Player
from ..game.world import HERO


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


def shared_snapshot(match: Match, fx: list, feed: list, with_scoreboard: bool, with_pickups: bool = False) -> str:
    """Everything every player sees. Returned as a JSON *fragment* (no braces)."""
    w = match.world
    slot_of = {p.pid: p.slot for p in match.players.values()}
    units, projs, tm = [], [], int(max(0, match.timer))
    if match.phase == FIGHT and w is not None:
        for u in w.units.values():
            if not u.alive:
                continue
            flags = (1 if u.stunned > 0 else 0) | (2 if u.shield > 0 else 0)
            # Last field is the enemy variant for non-heroes. Empty strings compress very well.
            units.append([u.id, u.kind, round(u.x), round(u.y), max(1, round(100 * u.hp / u.max_hp)),
                          slot_of.get(u.owner, -1) if u.kind == HERO else -1, flags, u.variant])
        projs = [[round(p.x), round(p.y), round(p.radius), p.style, p.visual,
                  round(math.degrees(math.atan2(p.vy, p.vx)))] for p in w.projectiles]
        tm = int(max(0, w.time_limit - w.t))   # seconds left in the round
    body = {"ph": match.phase, "rd": match.round, "boss": int(match.is_boss_round()), "tm": tm,
            "u": units, "pr": projs}
    if fx:
        body["fx"] = fx
    if feed:
        body["feed"] = feed
    if with_scoreboard:
        body["sb"] = scoreboard(match)
    if with_pickups:       # only sent when pickups changed (or on a phase change / periodic resync)
        body["pk"] = pickups(match)
    return dumps(body)[1:-1]


def pickups(match: Match) -> list:
    """[[id, 0 potion | 1 item, x, y, item_id?], ...] - empty outside fights."""
    w = match.world
    if match.phase != FIGHT or w is None:
        return []
    return [[p.id, 0, round(p.x), round(p.y)] if p.kind == "potion" else [p.id, 1, round(p.x), round(p.y), p.item]
            for p in w.pickups.values()]


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
    # stats: hp, max_hp, attack, armor, move_speed, attacks_per_100s, range,
    # spell_power_pct, lifesteal_pct, shield. Integers keep every snapshot compact.
    base = match.hero_stats(p)
    stats = [round(base["max_hp"]), round(base["max_hp"]), round(base["dmg"]), round(base["armor"]),
             round(base["speed"]), round(100 / base["atk_cd"]), round(base["atk_range"]),
             round(base["spell_power"] * 100), round(base["lifesteal"] * 100), 0]
    w = match.world
    if w is not None and p.unit_id is not None:
        u = w.units.get(p.unit_id)
        if u and u.alive:
            uid = u.id
            cds = [int(u.cds.get(s, 0) * 10) for s in ("q", "w", "e", "r")]
            stats = [round(u.hp), round(u.max_hp), round(u.dmg), round(u.armor), round(u.speed),
                     round(100 / u.atk_cd), round(u.atk_range), round(u.spell_power * 100),
                     round(u.lifesteal * 100), round(u.shield)]
    xp_pct = int(100 * p.xp / match.xp_needed(p.level))
    return dumps([uid, p.gold, p.level, xp_pct, *cds, p.items, stats])


def snapshot_for(shared: str, match: Match, p: Player) -> str:
    return '{"t":"s",' + shared + ',"me":' + private_part(match, p) + "}"
