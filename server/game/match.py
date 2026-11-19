"""Match flow: lobby -> (shop -> fight -> round end) x N -> results.

Rules:
  * Free-for-all. Every hero, the farmable minions and the boss are all hostile.
  * Every ``boss_every`` rounds a boss spawns; each boss is stronger than the last.
  * Dead = out until the round ends. A round ends when ALL heroes are dead.
  * You may suicide. The storm guarantees a round can't last forever.
  * Most points after ``rounds_total`` rounds wins.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..config import GameData
from .world import BOSS, BOSS_TEAM, CREEP_TEAM, HERO, MINION, World

LOBBY, SHOP, FIGHT, ROUND_END, OVER = "lobby", "shop", "fight", "round_end", "over"


@dataclass
class Player:
    pid: str
    name: str
    hero: str
    slot: int
    gold: int = 0
    level: int = 1
    xp: int = 0
    items: list[str] = field(default_factory=list)
    points: int = 0
    kills: int = 0
    boss_kills: int = 0
    unit_id: int | None = None
    connected: bool = True
    ready: bool = False

    def reset(self, start_gold: int) -> None:
        self.gold, self.level, self.xp = start_gold, 1, 0
        self.items, self.points, self.kills, self.boss_kills = [], 0, 0, 0
        self.unit_id, self.ready = None, False


class Match:
    def __init__(self, data: GameData, max_players: int, rng: random.Random | None = None) -> None:
        self.data = data
        self.g = data.game
        self.max_players = max_players
        self.rng = rng or random.Random()
        self.players: dict[str, Player] = {}
        self.phase = LOBBY
        self.round = 0
        self.timer = 0.0
        self.world: World | None = None
        self.feed: list[str] = []          # kill feed lines, drained by Room
        self.finished: dict | None = None  # results, set once when a match ends
        self._camps: list[dict] = []
        self._boss_name = ""
        self._alive_prev: set[str] = set()   # heroes alive at the end of the previous tick

    # ============================================================ lobby
    def add_player(self, pid: str, name: str, hero: str) -> Player:
        if self.phase != LOBBY:
            raise ValueError("Match already running. Wait for the lobby.")
        if len(self.players) >= self.max_players:
            raise ValueError("Room is full.")
        if hero not in self.data.heroes:
            raise ValueError("Unknown hero.")
        used = {p.slot for p in self.players.values()}
        slot = next(i for i in range(self.max_players) if i not in used)
        p = Player(pid=pid, name=name, hero=hero, slot=slot)
        self.players[pid] = p
        return p

    def set_hero(self, pid: str, hero: str) -> None:
        if self.phase == LOBBY and pid in self.players and hero in self.data.heroes:
            self.players[pid].hero = hero

    def remove_player(self, pid: str) -> None:
        p = self.players.get(pid)
        if not p:
            return
        if self.phase == LOBBY:
            del self.players[pid]
            return
        p.connected = False
        if self.world and p.unit_id is not None:
            self.world.kill(p.unit_id)       # leaving = suicide

    def connected_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.connected]

    def start(self) -> None:
        if self.phase != LOBBY or not self.players:
            raise ValueError("Cannot start.")
        for p in self.players.values():
            p.reset(self.g["start_gold"])
        self.round = 0
        self.finished = None
        self._begin_shop()

    def abort(self, reason: str) -> None:
        """End the match immediately (budget guard, everyone left, time cap)."""
        if self.phase in (LOBBY, OVER):
            return
        self.feed.append(f"Match ended: {reason}")
        self._finish(aborted=True)

    # ============================================================ rounds
    def is_boss_round(self, r: int | None = None) -> bool:
        r = self.round if r is None else r
        return r > 0 and r % self.g["boss_every"] == 0

    def boss_index(self, r: int | None = None) -> int:
        r = self.round if r is None else r
        return r // self.g["boss_every"]

    def _begin_shop(self) -> None:
        self.round += 1
        self.phase, self.timer = SHOP, float(self.g["shop_seconds"])
        self.world = None
        for p in self.players.values():
            p.ready, p.unit_id = False, None

    def _begin_fight(self) -> None:
        g = self.g
        w = World(g["arena"]["w"], g["arena"]["h"], g["round_seconds"], g["storm"], self.rng)
        self.world = w
        self.phase, self.timer = FIGHT, 0.0

        live = self.connected_players()
        cx, cy = w.w / 2, w.h / 2
        for i, p in enumerate(live):
            ang = math.tau * i / max(1, len(live))
            x, y = cx + math.cos(ang) * 380, cy + math.sin(ang) * 300
            p.unit_id = w.spawn(HERO, f"p{p.slot}", x, y, owner=p.pid, **self.hero_stats(p)).id

        self._camps = [{"spot": tuple(s), "uids": set(), "respawn": 0.0} for s in g["camps"]["spots"]]
        for camp in self._camps:
            self._spawn_camp(camp)

        if self.is_boss_round():
            self._spawn_boss(len(live))
        self._alive_prev = {u.owner for u in w.alive_heroes()}

    def _end_round(self, last_alive: list[str]) -> None:
        pts = self.g["rewards"]["survivor_points"]
        for pid in last_alive:
            p = self.players[pid]
            p.points += pts
            self.feed.append(f"{p.name} survived the longest (+{pts})")
        for p in self.players.values():
            p.gold += self.g["round_gold"]
        self.phase, self.timer = ROUND_END, float(self.g["round_end_seconds"])

    def _finish(self, aborted: bool = False) -> None:
        self.phase, self.timer = OVER, float(self.g["results_seconds"])
        self.world = None
        ranking = sorted(self.players.values(), key=lambda p: (-p.points, -p.kills, p.slot))
        self.finished = {
            "rounds": self.round,
            "winner": ranking[0].name if ranking and not aborted else None,   # aborted = no win counted
            "aborted": aborted,
            "players": [
                {"name": p.name, "hero": p.hero, "points": p.points, "kills": p.kills,
                 "boss_kills": p.boss_kills, "level": p.level}
                for p in ranking
            ],
        }

    # ============================================================ stats
    def hero_stats(self, p: Player) -> dict:
        h = self.data.heroes[p.hero]
        lv = self.g["leveling"]
        bonus = p.level - 1
        s = {
            "radius": float(h["radius"]),
            "max_hp": h["hp"] + lv["hp"] * bonus,
            "dmg": h["dmg"] + lv["dmg"] * bonus,
            "armor": float(h["armor"]),
            "atk_range": float(h["range"]),
            "atk_cd": float(h["atk_cd"]),
            "speed": float(h["speed"]),
            "spell_power": 1.0 + lv["spell_power"] * bonus,
            "lifesteal": 0.0,
        }
        for item_id in p.items:
            for k, v in self.data.items[item_id]["stats"].items():
                if k == "atk_cd_mult":
                    s["atk_cd"] *= v
                else:
                    s[k] += v
        return s

    def minion_stats(self) -> dict:
        m = self.g["minion"]
        scale = 1.0 + m["growth_per_round"] * (self.round - 1)
        return {"radius": float(m["radius"]), "max_hp": m["hp"] * scale, "dmg": m["dmg"] * scale,
                "armor": float(m["armor"]), "atk_range": float(m["range"]), "atk_cd": float(m["atk_cd"]),
                "speed": float(m["speed"]), "aggro": float(m["aggro"]), "leash": float(m["leash"])}

    def boss_stats(self, n: int, players: int) -> dict:
        b = self.data.bosses
        base, gr = b["base"], b["growth"]
        hp_scale = gr["hp"] ** (n - 1)
        dmg_scale = gr["dmg"] ** (n - 1)
        crowd = 1.0 + b["hp_per_extra_player"] * max(0, players - 1)
        return {"radius": float(base["radius"]), "max_hp": base["hp"] * hp_scale * crowd,
                "dmg": base["dmg"] * dmg_scale, "armor": float(base["armor"]) + n,
                "atk_range": float(base["range"]), "atk_cd": float(base["atk_cd"]),
                "speed": float(base["speed"]), "aggro": 600.0, "leash": 9999.0}

    def _spawn_camp(self, camp: dict) -> None:
        w, c = self.world, self.g["camps"]
        alive_minions = sum(1 for u in w.units.values() if u.kind == MINION)
        room = max(0, c["max_minions"] - alive_minions)
        sx, sy = camp["spot"]
        for i in range(min(c["size"], room)):
            ang = math.tau * i / c["size"]
            u = w.spawn(MINION, CREEP_TEAM, sx + math.cos(ang) * 30, sy + math.sin(ang) * 30,
                        home=(sx, sy), **self.minion_stats())
            camp["uids"].add(u.id)

    def _spawn_boss(self, players: int) -> None:
        w, b = self.world, self.data.bosses
        n = self.boss_index()
        stats = self.boss_stats(n, players)
        w.spawn(BOSS, BOSS_TEAM, w.w / 2, w.h / 2, home=(w.w / 2, w.h / 2), **stats)
        w.boss_abilities = dict(b["abilities"], index=n,
                                hp_scale=b["growth"]["hp"] ** (n - 1), dmg_scale=b["growth"]["dmg"] ** (n - 1))
        self._boss_name = b["names"][(n - 1) % len(b["names"])]
        self.feed.append(f"BOSS #{n}: {self._boss_name} has entered the arena!")

    # ============================================================ progression
    def xp_needed(self, level: int) -> int:
        return self.g["leveling"]["xp_per_level"] * level

    def give_xp(self, p: Player, amount: int) -> None:
        lv = self.g["leveling"]
        p.xp += amount
        while p.level < lv["max_level"] and p.xp >= self.xp_needed(p.level):
            p.xp -= self.xp_needed(p.level)
            p.level += 1
            u = self.world.units.get(p.unit_id) if self.world and p.unit_id else None
            if u and u.alive:     # level-ups apply instantly mid-fight
                u.max_hp += lv["hp"]
                u.hp += lv["hp"]
                u.dmg += lv["dmg"]
                u.spell_power += lv["spell_power"]
        if p.level >= lv["max_level"]:
            p.xp = 0

    # ============================================================ input
    def buy(self, pid: str, item_id: str) -> str | None:
        p = self.players.get(pid)
        item = self.data.items.get(item_id)
        if not p or not item:
            return "Unknown item."
        if self.phase != SHOP:
            return "Shop is closed."
        if len(p.items) >= self.g["max_items"]:
            return "Inventory full."
        if p.gold < item["cost"]:
            return "Not enough gold."
        p.gold -= item["cost"]
        p.items.append(item_id)
        return None

    def sell(self, pid: str, index: int) -> None:
        p = self.players.get(pid)
        if p and self.phase == SHOP and 0 <= index < len(p.items):
            p.gold += self.data.items[p.items.pop(index)]["cost"] // 2

    def set_ready(self, pid: str) -> None:
        if self.phase == SHOP and pid in self.players:
            self.players[pid].ready = True
            if all(p.ready for p in self.connected_players()):
                self.timer = 0.0

    def _my_unit(self, pid: str):
        p = self.players.get(pid)
        if self.phase != FIGHT or not p or p.unit_id is None:
            return None, None
        u = self.world.units.get(p.unit_id)
        return (p, u) if u and u.alive else (p, None)

    def command(self, pid: str, msg: dict) -> None:
        p, u = self._my_unit(pid)
        if not u:
            return
        t = msg.get("t")
        x, y = _num(msg.get("x")), _num(msg.get("y"))
        if t == "move" and x is not None and y is not None:
            self.world.command_move(u.id, x, y)
        elif t == "attack" and isinstance(msg.get("id"), int):
            self.world.command_attack(u.id, msg["id"])
        elif t == "stop":
            self.world.command_stop(u.id)
        elif t == "cast" and msg.get("slot") in ("q", "w", "e", "r") and x is not None and y is not None:
            skill = self.data.heroes[p.hero]["skills"][msg["slot"]]
            self.world.cast(u.id, msg["slot"], skill, x, y)
        elif t == "suicide":
            self.world.kill(u.id)
            self.feed.append(f"{p.name} chose death")

    # ============================================================ tick
    def step(self, dt: float) -> None:
        if self.phase == LOBBY:
            return
        if self.phase == FIGHT:
            self._step_fight(dt)
            return
        self.timer -= dt
        if self.timer > 0:
            return
        if self.phase == SHOP:
            self._begin_fight()
        elif self.phase == ROUND_END:
            if self.round >= self.g["rounds_total"]:
                self._finish()
            else:
                self._begin_shop()
        elif self.phase == OVER:
            self.phase = LOBBY
            for p in [p for p in self.players.values() if not p.connected]:
                del self.players[p.pid]

    def _step_fight(self, dt: float) -> None:
        w = self.world
        w.step(dt)
        self.timer += dt
        self._process_deaths()
        self._respawn_camps(dt)

        alive_now = {u.owner for u in w.alive_heroes()}
        if not alive_now:
            # Whoever was still standing at the previous tick outlasted everyone.
            self._end_round(sorted(pid for pid in self._alive_prev if pid in self.players))
        self._alive_prev = alive_now

    def _process_deaths(self) -> None:
        w, r = self.world, self.g["rewards"]
        for _, victim_uid, killer_uid in w.events:
            v_kind, v_owner = w.registry[victim_uid]
            k_kind, k_owner = w.registry.get(killer_uid, (None, None)) if killer_uid else (None, None)
            killer = self.players.get(k_owner) if k_kind == HERO else None

            if v_kind == HERO:
                victim = self.players.get(v_owner)
                if killer and victim and killer is not victim:
                    hk = r["hero_kill"]
                    killer.kills += 1
                    killer.points += hk["points"]
                    killer.gold += hk["gold"] + hk["gold_per_victim_level"] * victim.level
                    self.give_xp(killer, hk["xp"])
                    self.feed.append(f"{killer.name} slaughtered {victim.name}")
                elif victim and killer_uid is not None and k_kind != HERO:
                    who = self._boss_name if k_kind == BOSS else "the creeps"
                    self.feed.append(f"{victim.name} was destroyed by {who}")
            elif v_kind == BOSS:
                br = self.data.bosses["reward"]
                if killer:
                    killer.boss_kills += 1
                    killer.points += br["points"]
                    killer.gold += br["gold"]
                    self.give_xp(killer, br["xp"])
                    self.feed.append(f"{killer.name} took the last hit on {self._boss_name}! (+{br['points']})")
                else:
                    self.feed.append(f"{self._boss_name} fell (no hero got the last hit)")
            elif killer:     # minion or boss add
                m = self.g["minion"]
                killer.gold += m["gold"]
                self.give_xp(killer, m["xp"])
        w.events.clear()

    def _respawn_camps(self, dt: float) -> None:
        for camp in self._camps:
            camp["uids"] = {uid for uid in camp["uids"] if uid in self.world.units}
            if camp["uids"]:
                camp["respawn"] = float(self.g["camps"]["respawn_s"])
                continue
            camp["respawn"] -= dt
            if camp["respawn"] <= 0:
                self._spawn_camp(camp)
                camp["respawn"] = float(self.g["camps"]["respawn_s"])


def _num(v) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
        return float(v)
    return None
