"""Pure simulation of one round: units, combat, skills, AI, projectiles, storm.

No networking and no I/O, so everything here is easy to unit-test.

Teams decide who fights whom (``hostile = different team``):
  * every hero is its own team (free-for-all),
  * all farmable minions share team "creep" (they don't kill each other,
    but they DO attack heroes and the boss),
  * the boss and its summoned adds share team "boss".
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

HERO, MINION, BOSS, ADD = 0, 1, 2, 3
CREEP_TEAM = "creep"
BOSS_TEAM = "boss"


@dataclass(slots=True, eq=False)
class Unit:
    id: int
    kind: int
    team: str
    x: float
    y: float
    radius: float
    max_hp: float
    dmg: float
    armor: float
    atk_range: float
    atk_cd: float
    speed: float
    hp: float = 0.0
    owner: str | None = None            # player id (heroes only)
    home: tuple[float, float] | None = None
    aggro: float = 300.0
    leash: float = 9999.0
    spell_power: float = 1.0
    lifesteal: float = 0.0
    dmg_mult: float = 1.0
    atk_timer: float = 0.0
    move_to: tuple[float, float] | None = None
    target_id: int | None = None
    stunned: float = 0.0
    shield: float = 0.0
    shield_t: float = 0.0
    alive: bool = True
    cds: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.hp <= 0:
            self.hp = self.max_hp


@dataclass(slots=True, eq=False)
class Projectile:
    owner_uid: int
    team: str
    x: float
    y: float
    vx: float
    vy: float
    range_left: float
    dmg: float
    radius: float
    aoe: float = 0.0
    stun: float = 0.0


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


class World:
    def __init__(self, width: int, height: int, round_seconds: float, storm: dict,
                 rng: random.Random | None = None) -> None:
        self.w, self.h = width, height
        self.units: dict[int, Unit] = {}
        self.projectiles: list[Projectile] = []
        self.registry: dict[int, tuple[int, str | None]] = {}  # uid -> (kind, owner); survives death
        self.events: list[tuple] = []   # ("death", victim_uid, killer_uid|None) -- drained by Match
        self.fx: list[list] = []        # short visual effects for clients -- drained by Room
        self.t = 0.0
        self.storm_at = round_seconds
        self.storm = storm
        self.boss_abilities: dict = {}
        self.rng = rng or random.Random()
        self._next_id = 1

    # ------------------------------------------------------------------ spawn
    def spawn(self, kind: int, team: str, x: float, y: float, **stats) -> Unit:
        uid = self._next_id
        self._next_id += 1
        unit = Unit(id=uid, kind=kind, team=team, x=x, y=y, **stats)
        self.units[uid] = unit
        self.registry[uid] = (kind, unit.owner)
        return unit

    # --------------------------------------------------------------- queries
    def hero_of(self, pid: str) -> Unit | None:
        for u in self.units.values():
            if u.kind == HERO and u.owner == pid:
                return u
        return None

    def alive_heroes(self) -> list[Unit]:
        return [u for u in self.units.values() if u.kind == HERO and u.alive]

    def _nearest_hostile(self, u: Unit, max_range: float) -> Unit | None:
        best, best_d = None, max_range
        for o in self.units.values():
            if o.alive and o.team != u.team:
                d = dist(u.x, u.y, o.x, o.y) - o.radius
                if d <= best_d:
                    best, best_d = o, d
        return best

    # -------------------------------------------------------------- commands
    def command_move(self, uid: int, x: float, y: float) -> None:
        u = self.units.get(uid)
        if u and u.alive:
            u.move_to = (self._cx(x), self._cy(y))
            u.target_id = None

    def command_attack(self, uid: int, target_uid: int) -> None:
        u, t = self.units.get(uid), self.units.get(target_uid)
        if u and t and u.alive and t.alive and t.team != u.team:
            u.target_id = t.id
            u.move_to = None

    def command_stop(self, uid: int) -> None:
        u = self.units.get(uid)
        if u:
            u.move_to = None
            u.target_id = None

    def cast(self, uid: int, slot: str, skill: dict, x: float, y: float) -> bool:
        """Cast a hero skill toward (x, y). Returns False if not possible."""
        u = self.units.get(uid)
        if not u or not u.alive or u.stunned > 0 or u.cds.get(slot, 0) > 0:
            return False
        u.cds[slot] = float(skill["cd"])
        sp = u.spell_power
        kind = skill["type"]

        if kind == "projectile":
            dx, dy = x - u.x, y - u.y
            n = math.hypot(dx, dy) or 1.0
            spd = float(skill["speed"])
            self.projectiles.append(Projectile(
                owner_uid=u.id, team=u.team, x=u.x, y=u.y, vx=dx / n * spd, vy=dy / n * spd,
                range_left=float(skill["range"]), dmg=skill["dmg"] * sp, radius=float(skill["r"]),
                aoe=float(skill.get("aoe", 0)), stun=float(skill.get("stun", 0))))
        elif kind == "nova":
            self._nova(u, u.x, u.y, skill["r"], skill["dmg"] * sp, skill.get("stun", 0))
        elif kind == "dash":
            dx, dy = x - u.x, y - u.y
            n = math.hypot(dx, dy) or 1.0
            step = min(n, float(skill["dist"]))
            u.x, u.y = self._cx(u.x + dx / n * step), self._cy(u.y + dy / n * step)
            u.move_to, u.target_id = None, None
            if skill.get("dmg"):
                self._nova(u, u.x, u.y, skill["hit_r"], skill["dmg"] * sp, 0)
            self.fx.append(["d", round(u.x), round(u.y)])
        elif kind == "buff":
            if skill.get("heal"):
                u.hp = min(u.max_hp, u.hp + skill["heal"] * sp)
            if skill.get("shield"):
                u.shield = skill["shield"] * sp
                u.shield_t = float(skill.get("dur", 4))
            self.fx.append(["b", u.id])
        return True

    def kill(self, uid: int, killer_uid: int | None = None) -> None:
        """Instantly kill a unit (used for suicide / disconnect)."""
        u = self.units.get(uid)
        if u and u.alive:
            self._die(u, killer_uid)

    # ---------------------------------------------------------------- combat
    def damage(self, src_uid: int | None, victim: Unit, amount: float, *, true_dmg: bool = False) -> None:
        if not victim.alive or amount <= 0:
            return
        if not true_dmg:
            amount /= 1.0 + 0.06 * max(victim.armor, 0.0)
            if victim.shield > 0:
                absorbed = min(victim.shield, amount)
                victim.shield -= absorbed
                amount -= absorbed
        victim.hp -= amount

        src = self.units.get(src_uid) if src_uid is not None else None
        if src and src.alive and src.lifesteal > 0:
            src.hp = min(src.max_hp, src.hp + amount * src.lifesteal)
        # AI units fight back against whoever hits them.
        if src and victim.kind != HERO and victim.target_id is None:
            victim.target_id = src.id
        if victim.hp <= 0:
            self._die(victim, src_uid)

    def _die(self, u: Unit, killer_uid: int | None) -> None:
        u.alive = False
        u.hp = 0
        u.move_to = u.target_id = None
        self.events.append(("death", u.id, killer_uid))

    def _nova(self, src: Unit, x: float, y: float, r: float, dmg: float, stun: float) -> None:
        for o in list(self.units.values()):
            if o.alive and o.team != src.team and dist(x, y, o.x, o.y) <= r + o.radius:
                if stun:
                    o.stunned = max(o.stunned, float(stun))
                self.damage(src.id, o, dmg)
        self.fx.append(["n", round(x), round(y), round(r)])

    # ------------------------------------------------------------------ step
    def step(self, dt: float) -> None:
        self.t += dt
        for u in list(self.units.values()):
            if not u.alive:
                continue
            self._tick_timers(u, dt)
            if u.kind == BOSS:
                self._boss_abilities(u)
            if u.stunned > 0:
                continue
            self._think(u)
            self._act(u, dt)
        self._step_projectiles(dt)
        self._storm(dt)
        # Dead AI units leave the world; dead heroes stay (Match needs them).
        for uid in [uid for uid, u in self.units.items() if not u.alive and u.kind != HERO]:
            del self.units[uid]

    def _tick_timers(self, u: Unit, dt: float) -> None:
        u.atk_timer = max(0.0, u.atk_timer - dt)
        u.stunned = max(0.0, u.stunned - dt)
        if u.shield_t > 0:
            u.shield_t -= dt
            if u.shield_t <= 0:
                u.shield = 0.0
        for k in u.cds:
            u.cds[k] = max(0.0, u.cds[k] - dt)

    def _think(self, u: Unit) -> None:
        tgt = self.units.get(u.target_id) if u.target_id is not None else None
        if tgt is not None and (not tgt.alive or tgt.team == u.team):
            u.target_id, tgt = None, None

        if u.kind == HERO:
            # Auto-acquire only when idle (WC3 style).
            if tgt is None and u.move_to is None:
                near = self._nearest_hostile(u, u.atk_range + u.radius + 80)
                if near:
                    u.target_id = near.id
            return

        home = u.home or (self.w / 2, self.h / 2)
        if tgt is not None and dist(u.x, u.y, home[0], home[1]) > u.leash:
            u.target_id = None              # chased too far: give up and walk home
            u.move_to = home
            return
        if tgt is None:
            near = self._nearest_hostile(u, u.aggro)
            if near:
                u.target_id = near.id
                u.move_to = None
            elif dist(u.x, u.y, home[0], home[1]) > 20:
                u.move_to = home

    def _act(self, u: Unit, dt: float) -> None:
        tgt = self.units.get(u.target_id) if u.target_id is not None else None
        if tgt is not None:
            reach = u.atk_range + u.radius + tgt.radius
            if dist(u.x, u.y, tgt.x, tgt.y) <= reach:
                if u.atk_timer <= 0:
                    self.damage(u.id, tgt, u.dmg * u.dmg_mult)
                    u.atk_timer = u.atk_cd
            else:
                self._move_toward(u, tgt.x, tgt.y, dt)
        elif u.move_to is not None:
            if self._move_toward(u, *u.move_to, dt):
                u.move_to = None

    def _move_toward(self, u: Unit, x: float, y: float, dt: float) -> bool:
        dx, dy = x - u.x, y - u.y
        d = math.hypot(dx, dy)
        step = u.speed * dt
        if d <= step:
            u.x, u.y = x, y
            return True
        u.x = self._cx(u.x + dx / d * step)
        u.y = self._cy(u.y + dy / d * step)
        return False

    def _step_projectiles(self, dt: float) -> None:
        keep: list[Projectile] = []
        for p in self.projectiles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.range_left -= math.hypot(p.vx, p.vy) * dt
            hit = None
            for o in self.units.values():
                if o.alive and o.team != p.team and dist(p.x, p.y, o.x, o.y) <= p.radius + o.radius:
                    hit = o
                    break
            if hit is not None:
                if p.aoe:
                    for o in list(self.units.values()):
                        if o.alive and o.team != p.team and dist(p.x, p.y, o.x, o.y) <= p.aoe + o.radius:
                            if p.stun:
                                o.stunned = max(o.stunned, p.stun)
                            self.damage(p.owner_uid, o, p.dmg)
                    self.fx.append(["n", round(p.x), round(p.y), round(p.aoe)])
                else:
                    if p.stun:
                        hit.stunned = max(hit.stunned, p.stun)
                    self.damage(p.owner_uid, hit, p.dmg)
                continue
            if p.range_left > 0 and 0 <= p.x <= self.w and 0 <= p.y <= self.h:
                keep.append(p)
        self.projectiles = keep

    def _storm(self, dt: float) -> None:
        """After round_seconds everything bleeds out, so every round is guaranteed to end."""
        if self.t < self.storm_at:
            return
        steps = int((self.t - self.storm_at) // self.storm["growth_every_s"])
        pct = self.storm["start_pct"] + self.storm["growth_pct"] * steps
        for u in list(self.units.values()):
            if u.alive:
                self.damage(None, u, u.max_hp * pct * dt, true_dmg=True)

    def _boss_abilities(self, boss: Unit) -> None:
        ab = self.boss_abilities
        if not ab:
            return
        enrage = ab.get("enrage")
        if enrage and self.t >= enrage["after_s"]:
            boss.dmg_mult = enrage["dmg_mult"]
        if boss.stunned > 0:
            return
        n = ab.get("index", 1)
        slam = ab.get("slam")
        if slam and n >= slam["unlock"] and boss.cds.get("slam", 0) <= 0:
            if self._nearest_hostile(boss, slam["r"]):
                boss.cds["slam"] = float(slam["cd"])
                self._nova(boss, boss.x, boss.y, slam["r"], boss.dmg * boss.dmg_mult * slam["dmg_mult"], slam["stun"])
        summon = ab.get("summon")
        if summon and n >= summon["unlock"] and boss.cds.get("summon", 0) <= 0:
            boss.cds["summon"] = float(summon["cd"])
            for _ in range(summon["count"]):
                ang = self.rng.uniform(0, math.tau)
                self.spawn(ADD, BOSS_TEAM, self._cx(boss.x + math.cos(ang) * 70), self._cy(boss.y + math.sin(ang) * 70),
                           radius=16, max_hp=summon["hp"] * ab.get("hp_scale", 1), dmg=summon["dmg"] * ab.get("dmg_scale", 1),
                           armor=2, atk_range=40, atk_cd=1.1, speed=170, aggro=500,
                           home=(boss.x, boss.y), leash=900)

    # --------------------------------------------------------------- helpers
    def _cx(self, x: float) -> float:
        return min(max(x, 10.0), self.w - 10.0)

    def _cy(self, y: float) -> float:
        return min(max(y, 10.0), self.h - 10.0)
