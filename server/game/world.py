"""Pure simulation of one round: units, combat, skills, AI, projectiles, pickups.

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
    variant: str = ""                  # enemy visual/stats id (goblin, brute, archer, wisp)
    reward_mult: float = 1.0            # gold/xp multiplier for this enemy type
    basic_visual: str = ""             # ranged basic attack: arrow, fire_bolt, arc_bolt, thorn, bone_arrow
    home: tuple[float, float] | None = None
    aggro: float = 300.0
    leash: float = 9999.0
    spell_power: float = 1.0
    lifesteal: float = 0.0
    dmg_mult: float = 1.0
    base_atk_cd: float = 0.0
    base_speed: float = 0.0
    effects: list[dict] = field(default_factory=list)
    phased: float = 0.0
    atk_timer: float = 0.0
    move_to: tuple[float, float] | None = None
    target_id: int | None = None
    stunned: float = 0.0
    busy: float = 0.0               # channelling a skill: can't move or attack
    shield: float = 0.0
    shield_t: float = 0.0
    alive: bool = True
    cds: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.hp <= 0:
            self.hp = self.max_hp
        if self.base_atk_cd <= 0:
            self.base_atk_cd = self.atk_cd
        if self.base_speed <= 0:
            self.base_speed = self.speed


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
    style: str = "fire"
    visual: str = "orb"
    pierce_left: int = 0
    execute_pct: float = 0.0
    execute_mult: float = 1.0
    root: float = 0.0
    hit_ids: set[int] = field(default_factory=set)


@dataclass(slots=True, eq=False)
class Pickup:
    """Something lying on the floor. kind: "potion" (heals) or "item" (boss loot)."""
    id: int
    kind: str
    x: float
    y: float
    ttl: float | None = None        # seconds left; None = stays until the round ends
    item: str | None = None
    retry: float = 0.0              # cooldown between failed item pick-up attempts (full inventory)


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


class World:
    def __init__(self, width: int, height: int, time_limit: float,
                 rng: random.Random | None = None, potion_cfg: dict | None = None) -> None:
        self.w, self.h = width, height
        self.units: dict[int, Unit] = {}
        self.projectiles: list[Projectile] = []
        self.registry: dict[int, tuple[int, str | None, float]] = {}  # uid -> (kind, owner, reward_mult); survives death
        self.events: list[tuple] = []   # ("death", victim_uid, killer_uid|None) -- drained by Match
        self.fx: list[list] = []        # short visual effects for clients -- drained by Room
        self.t = 0.0
        self.time_limit = float(time_limit)   # round length in seconds; nothing bleeds, it just ends
        self.time_up = False
        self.boss_abilities: dict = {}
        self.rng = rng or random.Random()
        self._next_id = 1
        # --- pickups (potions + boss loot) and delayed boss attacks ---
        self.pickups: dict[int, Pickup] = {}
        self.pk_version = 0                  # bumps on every add/remove -> network sends pickups only on change
        self._next_pk = 1
        self.potion_cfg = potion_cfg or {}   # empty = no potions
        self.potion_timer = 0.0
        if self.potion_cfg:
            self.potion_timer = self.rng.uniform(self.potion_cfg["spawn_min_s"], self.potion_cfg["spawn_max_s"]) * 0.6
        self.boss_loot: str | None = None    # item id dropped when the boss dies
        self.pending: list[dict] = []        # telegraphed attacks waiting to land
        self.zones: list[dict] = []          # damage/slow fields, mines, drones, timed pulses

    # ------------------------------------------------------------------ spawn
    def spawn(self, kind: int, team: str, x: float, y: float, **stats) -> Unit:
        uid = self._next_id
        self._next_id += 1
        unit = Unit(id=uid, kind=kind, team=team, x=x, y=y, **stats)
        self.units[uid] = unit
        self.registry[uid] = (kind, unit.owner, unit.reward_mult)
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
            if o.alive and o.team != u.team and o.phased <= 0:
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

        self.fx.append(["c", skill.get("color", "plain"), kind, round(u.x), round(u.y), round(x), round(y)])
        if kind in ("pierce", "execute", "root_projectile"):
            dx, dy = x - u.x, y - u.y
            n = math.hypot(dx, dy) or 1.0
            self.projectiles.append(Projectile(owner_uid=u.id, team=u.team, x=u.x, y=u.y,
                vx=dx/n*skill["speed"], vy=dy/n*skill["speed"], range_left=skill["range"],
                dmg=skill["dmg"]*sp, radius=skill["r"], style=skill.get("color", "plain"), visual=skill.get("visual", "orb"),
                pierce_left=skill.get("max_hits", 1) - 1, execute_pct=skill.get("execute_pct", 0),
                execute_mult=skill.get("execute_mult", 1), root=skill.get("root", 0)))
        elif kind == "cone":
            ang = math.atan2(y-u.y, x-u.x); count=max(1,int(skill["count"])); spread=skill["spread"]
            for i in range(count):
                a=ang + (i-(count-1)/2)*spread/max(1,count-1)
                self.projectiles.append(Projectile(owner_uid=u.id, team=u.team, x=u.x, y=u.y,
                    vx=math.cos(a)*skill["speed"], vy=math.sin(a)*skill["speed"], range_left=skill["range"],
                    dmg=skill["dmg"]*sp, radius=skill["r"], style=skill.get("color","wind"), visual=skill.get("visual", "arrow")))
        elif kind == "dash_buff":
            self._dash(u,x,y,skill["dist"]); u.atk_cd *= skill["haste"]
            u.effects.append({"kind":"haste","left":skill["dur"],"undo":1/skill["haste"]})
        elif kind == "teleport_strike":
            tgt=self._nearest_point_hostile(u,x,y,skill["range"])
            if tgt:
                dx,dy=tgt.x-u.x,tgt.y-u.y; n=math.hypot(dx,dy) or 1
                u.x,u.y=self._cx(tgt.x-dx/n*(u.radius+tgt.radius+4)),self._cy(tgt.y-dy/n*(u.radius+tgt.radius+4))
                self.damage(u.id,tgt,skill["dmg"]*sp); self.fx.append(["x","shadow",round(u.x),round(u.y),tgt.id])
        elif kind == "drain_nova":
            healed=0.0
            for o in list(self.units.values()):
                if o.alive and o.team!=u.team and dist(u.x,u.y,o.x,o.y)<=skill["r"]+o.radius:
                    before=o.hp; self.damage(u.id,o,skill["dmg"]*sp); healed += max(0,before-o.hp)*skill["heal_pct"]
            u.hp=min(u.max_hp,u.hp+healed); self.fx.append(["n",round(u.x),round(u.y),skill["r"],"shadow"])
        elif kind == "phase":
            u.phased=max(u.phased,skill["dur"]); u.speed*=skill["speed_mult"]
            u.effects.append({"kind":"phase","left":skill["dur"],"undo":1/skill["speed_mult"]})
        elif kind == "pulse_ult":
            self.zones.append({"kind":"pulse","owner":u.id,"x":u.x,"y":u.y,"r":skill["r"],"dmg":skill["dmg"]*sp,
                               "left":skill["pulses"]*skill["interval"],"tick":skill["interval"],"next":0.0,"pulses":skill["pulses"],"follow":True,"style":"shadow"})
        elif kind == "zone":
            self.zones.append({"kind":"zone","owner":u.id,"x":x,"y":y,"r":skill["r"],"dmg":skill["dmg"]*sp,
                               "left":skill["dur"],"tick":skill["tick"],"next":0.0,"slow":skill["slow"],"style":"nature"})
            self.fx.append(["z","nature",round(x),round(y),skill["r"],round(skill["dur"]*1000)])
        elif kind == "hot":
            u.effects.append({"kind":"hot","left":skill["dur"],"tick":skill["tick"],"next":0.0,"heal":skill["heal"]*sp/skill["dur"]*skill["tick"]})
        elif kind == "transform":
            u.max_hp+=skill["hp_bonus"]*sp; u.hp+=skill["hp_bonus"]*sp; u.dmg*=skill["dmg_mult"]; u.armor+=skill["armor_bonus"]; u.speed*=skill["speed_mult"]
            u.effects.append({"kind":"transform","left":skill["dur"],"hp":skill["hp_bonus"]*sp,"dmg":1/skill["dmg_mult"],"armor":skill["armor_bonus"],"speed":1/skill["speed_mult"]})
            self.fx.append(["b",u.id,"nature"])
        elif kind == "chain":
            tgt=self._nearest_point_hostile(u,x,y,skill["range"]); hit=[]; dmg=skill["dmg"]*sp
            while tgt and len(hit)<skill["jumps"]:
                self.damage(u.id,tgt,dmg); hit.append(tgt.id); dmg*=skill["falloff"]
                nxt=[o for o in self.units.values() if o.alive and o.team!=u.team and o.id not in hit and dist(tgt.x,tgt.y,o.x,o.y)<=skill["range"]*.65]
                tgt=min(nxt,key=lambda o:dist(tgt.x,tgt.y,o.x,o.y)) if nxt else None
            self.fx.append(["l","arc",*hit])
        elif kind == "mine":
            self.zones.append({"kind":"mine","owner":u.id,"x":x,"y":y,"r":skill["r"],"dmg":skill["dmg"]*sp,"left":skill["dur"],"arm":skill["arm"],"stun":skill["stun"],"style":"arc"})
            self.fx.append(["m","arc",round(x),round(y),skill["r"],round(skill["dur"]*1000)])
        elif kind == "drone":
            self.zones.append({"kind":"drone","owner":u.id,"x":u.x,"y":u.y,"range":skill["range"],"dmg":skill["dmg"]*sp,"left":skill["dur"],"tick":skill["atk_cd"],"next":0.0,"style":"arc"})
            self.fx.append(["o","arc",u.id,round(skill["dur"]*1000)])
        elif kind == "beam":
            self._beam(u,x,y,skill["range"],skill["width"],skill["dmg"]*sp); self.fx.append(["e","arc",round(u.x),round(u.y),round(x),round(y),skill["width"]])
        elif kind == "projectile":
            dx, dy = x - u.x, y - u.y
            n = math.hypot(dx, dy) or 1.0
            spd = float(skill["speed"])
            self.projectiles.append(Projectile(
                owner_uid=u.id, team=u.team, x=u.x, y=u.y, vx=dx / n * spd, vy=dy / n * spd,
                range_left=float(skill["range"]), dmg=skill["dmg"] * sp, radius=float(skill["r"]),
                aoe=float(skill.get("aoe", 0)), stun=float(skill.get("stun", 0)), style=skill.get("color", "fire"),
                visual=skill.get("visual", "orb")))
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

    def _dash(self, u: Unit, x: float, y: float, distance: float) -> None:
        dx,dy=x-u.x,y-u.y; n=math.hypot(dx,dy) or 1; step=min(n,float(distance))
        u.x,u.y=self._cx(u.x+dx/n*step),self._cy(u.y+dy/n*step); u.move_to,u.target_id=None,None
        self.fx.append(["d",round(u.x),round(u.y)])

    def _nearest_point_hostile(self, u: Unit, x: float, y: float, max_range: float) -> Unit | None:
        candidates=[o for o in self.units.values() if o.alive and o.team!=u.team and o.phased<=0 and dist(u.x,u.y,o.x,o.y)<=max_range]
        return min(candidates,key=lambda o:dist(x,y,o.x,o.y)) if candidates else None

    def _beam(self, u: Unit, x: float, y: float, reach: float, width: float, dmg: float) -> None:
        dx,dy=x-u.x,y-u.y; n=math.hypot(dx,dy) or 1; dx,dy=dx/n,dy/n
        for o in list(self.units.values()):
            if not o.alive or o.team==u.team or o.phased>0: continue
            px,py=o.x-u.x,o.y-u.y; along=px*dx+py*dy; side=abs(px*dy-py*dx)
            if 0<=along<=reach and side<=width+o.radius: self.damage(u.id,o,dmg)

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
        if u.kind == MINION and self.potion_cfg and self.rng.random() < self.potion_cfg["minion_drop_chance"]:
            self.add_potion(u.x, u.y)
        elif u.kind == BOSS and self.boss_loot:
            self.add_pickup("item", u.x, u.y, item=self.boss_loot)
            self.fx.append(["n", round(u.x), round(u.y), 90])

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
        self._step_pending(dt)
        for u in list(self.units.values()):
            if not u.alive:
                continue
            self._tick_timers(u, dt)
            if u.kind == BOSS:
                self._boss_abilities(u)
            if u.stunned > 0 or u.busy > 0:
                continue
            self._think(u)
            self._act(u, dt)
        self._step_projectiles(dt)
        self._step_zones(dt)
        self._step_pickups(dt)
        self._check_time_limit()
        # Dead AI units leave the world; dead heroes stay (Match needs them).
        for uid in [uid for uid, u in self.units.items() if not u.alive and u.kind != HERO]:
            del self.units[uid]

    def _tick_timers(self, u: Unit, dt: float) -> None:
        u.atk_timer = max(0.0, u.atk_timer - dt)
        u.stunned = max(0.0, u.stunned - dt)
        u.busy = max(0.0, u.busy - dt)
        u.phased = max(0.0, u.phased - dt)
        self._step_effects(u, dt)
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
                    if u.atk_range >= 120 and u.basic_visual:
                        dx, dy = tgt.x - u.x, tgt.y - u.y
                        n = math.hypot(dx, dy) or 1.0
                        speed = 760.0
                        style = {"arrow":"wind", "fire_bolt":"fire", "arc_bolt":"arc", "thorn":"nature", "bone_arrow":"plain"}.get(u.basic_visual, "plain")
                        self.projectiles.append(Projectile(owner_uid=u.id, team=u.team, x=u.x, y=u.y,
                            vx=dx/n*speed, vy=dy/n*speed, range_left=max(u.atk_range*1.45, 420),
                            dmg=u.dmg*u.dmg_mult, radius=8, style=style, visual=u.basic_visual))
                    else:
                        self.damage(u.id, tgt, u.dmg * u.dmg_mult)
                        self.fx.append(["a", "melee", u.id, tgt.id])
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

    def _step_effects(self, u: Unit, dt: float) -> None:
        keep=[]
        for e in u.effects:
            e["left"]-=dt; e["next"]=e.get("next",0)-dt
            if e["kind"]=="hot" and e["next"]<=0:
                u.hp=min(u.max_hp,u.hp+e["heal"]); e["next"]=e["tick"]; self.fx.append(["h",round(u.x),round(u.y),"nature"])
            if e["left"]>0: keep.append(e); continue
            if e["kind"]=="haste": u.atk_cd*=e["undo"]
            elif e["kind"]=="phase": u.speed*=e["undo"]
            elif e["kind"]=="slow": u.speed*=e["undo"]
            elif e["kind"]=="transform":
                u.max_hp=max(1,u.max_hp-e["hp"]);u.hp=min(u.hp,u.max_hp);u.dmg*=e["dmg"];u.armor-=e["armor"];u.speed*=e["speed"]
        u.effects=keep

    def _step_zones(self, dt: float) -> None:
        keep=[]
        for z in self.zones:
            z["left"]-=dt; z["next"]=z.get("next",0)-dt; owner=self.units.get(z["owner"])
            if not owner or not owner.alive: continue
            if z.get("follow"): z["x"],z["y"]=owner.x,owner.y
            if z["kind"] in ("zone","pulse") and z["next"]<=0 and z.get("pulses",1)>0:
                for o in list(self.units.values()):
                    if o.alive and o.team!=owner.team and dist(z["x"],z["y"],o.x,o.y)<=z["r"]+o.radius:
                        self.damage(owner.id,o,z["dmg"])
                        if z.get("slow") and not any(e["kind"]=="slow" for e in o.effects):
                            o.speed*=1-z["slow"];o.effects.append({"kind":"slow","left":z["tick"]*1.5,"undo":1/(1-z["slow"])})
                z["next"]=z["tick"];z["pulses"]=z.get("pulses",999)-1;self.fx.append(["n",round(z["x"]),round(z["y"]),round(z["r"]),z["style"]])
            elif z["kind"]=="mine":
                z["arm"]-=dt
                if z["arm"]<=0:
                    targets=[o for o in self.units.values() if o.alive and o.team!=owner.team and dist(z["x"],z["y"],o.x,o.y)<=z["r"]+o.radius]
                    if targets:
                        for o in targets:self.damage(owner.id,o,z["dmg"]);o.stunned=max(o.stunned,z["stun"])
                        self.fx.append(["n",round(z["x"]),round(z["y"]),round(z["r"]),"arc"]);continue
            elif z["kind"]=="drone" and z["next"]<=0:
                tgt=self._nearest_hostile(owner,z["range"])
                if tgt:self.damage(owner.id,tgt,z["dmg"]);self.fx.append(["l","arc",owner.id,tgt.id])
                z["next"]=z["tick"]
            if z["left"]>0:keep.append(z)
        self.zones=keep

    def _step_projectiles(self, dt: float) -> None:
        keep: list[Projectile] = []
        for p in self.projectiles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.range_left -= math.hypot(p.vx, p.vy) * dt
            hit = None
            for o in self.units.values():
                if o.alive and o.team != p.team and o.phased <= 0 and o.id not in p.hit_ids and dist(p.x, p.y, o.x, o.y) <= p.radius + o.radius:
                    hit = o
                    break
            if hit is not None:
                p.hit_ids.add(hit.id)
                if p.execute_pct and hit.hp / hit.max_hp <= p.execute_pct:
                    p.dmg *= p.execute_mult
                if p.root:
                    hit.stunned = max(hit.stunned, p.root)
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
                self.fx.append(["i", p.style, round(p.x), round(p.y), hit.id])
                if p.pierce_left > 0:
                    p.pierce_left -= 1
                    if p.range_left > 0:
                        keep.append(p)
                continue
            if p.range_left > 0 and 0 <= p.x <= self.w and 0 <= p.y <= self.h:
                keep.append(p)
        self.projectiles = keep

    def _check_time_limit(self) -> None:
        """When the clock runs out the round is over: every hero still standing is out (no damage dealt
        before that). This guarantees a round can never stall forever."""
        if self.time_up or self.t < self.time_limit:
            return
        self.time_up = True
        self.events.append(("timeup",))
        for h in self.alive_heroes():
            self.kill(h.id)

    # ------------------------------------------------------------ boss skills
    def add_telegraph(self, src: Unit, x: float, y: float, r: float, dmg: float, stun: float,
                      windup: float, *, leap: bool = False, interruptible: bool = False) -> None:
        """A warning circle that explodes after `windup` seconds. Players can run out of it."""
        self.pending.append({"left": float(windup), "src": src.id, "x": self._cx(x), "y": self._cy(y),
                             "r": float(r), "dmg": float(dmg), "stun": float(stun),
                             "leap": leap, "intr": interruptible})
        self.fx.append(["t", round(self._cx(x)), round(self._cy(y)), round(r), int(windup * 1000)])

    def _step_pending(self, dt: float) -> None:
        keep = []
        for p in self.pending:
            p["left"] -= dt
            if p["left"] > 0:
                keep.append(p)
                continue
            src = self.units.get(p["src"])
            if not src or not src.alive:
                continue                              # caster died: the attack fizzles
            if p["intr"] and src.stunned > 0:
                src.busy = 0.0                        # a stun interrupts big wind-ups
                continue
            if p["leap"]:
                src.x, src.y = p["x"], p["y"]
                self.fx.append(["d", round(src.x), round(src.y)])
            self._nova(src, p["x"], p["y"], p["r"], p["dmg"], p["stun"])
        self.pending = keep

    def _boss_abilities(self, boss: Unit) -> None:
        """Skills unlock with the boss number. At most one cast per global cooldown (`gcd`)."""
        ab = self.boss_abilities
        if not ab:
            return
        n = ab.get("index", 1)
        enrage = ab.get("enrage")
        if enrage and self.t >= enrage["after_s"]:
            boss.dmg_mult = enrage["dmg_mult"]
        bloodlust = ab.get("bloodlust")
        if bloodlust and n >= bloodlust["unlock"]:
            boss.lifesteal = bloodlust["lifesteal"]
        if boss.stunned > 0 or boss.busy > 0 or boss.cds.get("gcd", 0) > 0:
            return
        heroes = self.alive_heroes()
        if not heroes:
            return
        base = boss.dmg * boss.dmg_mult
        gcd = float(ab.get("gcd", 1.5))

        def ready(name: str):
            a = ab.get(name)
            return a if isinstance(a, dict) and "cd" in a and n >= a["unlock"] and boss.cds.get(name, 0) <= 0 else None

        def used(name: str, a: dict) -> None:
            boss.cds[name] = float(a["cd"])
            boss.cds["gcd"] = gcd

        a = ready("meteor")
        if a:
            used("meteor", a)
            count = min(int(a.get("max_count", 6)), int(a["count"]) + max(0, n - a["unlock"]))
            spots = [(h.x + self.rng.uniform(-50, 50), h.y + self.rng.uniform(-50, 50)) for h in heroes]
            self.rng.shuffle(spots)
            spots = spots[:count]
            while len(spots) < count:
                spots.append((self.rng.uniform(120, self.w - 120), self.rng.uniform(100, self.h - 100)))
            for sx, sy in spots:
                self.add_telegraph(boss, sx, sy, a["r"], base * a["dmg_mult"], 0, a["windup"])
            return

        a = ready("summon")
        if a:
            used("summon", a)
            for _ in range(a["count"]):
                ang = self.rng.uniform(0, math.tau)
                self.spawn(ADD, BOSS_TEAM, self._cx(boss.x + math.cos(ang) * 70), self._cy(boss.y + math.sin(ang) * 70),
                           radius=16, max_hp=a["hp"] * ab.get("hp_scale", 1), dmg=a["dmg"] * ab.get("dmg_scale", 1),
                           armor=2, atk_range=40, atk_cd=1.1, speed=170, aggro=500,
                           home=(boss.x, boss.y), leash=900)
            return

        a = ready("slam")
        if a and any(dist(boss.x, boss.y, h.x, h.y) <= a["r"] + h.radius for h in heroes):
            used("slam", a)
            boss.busy = float(a["windup"])
            boss.move_to = None
            self.add_telegraph(boss, boss.x, boss.y, a["r"], base * a["dmg_mult"], a["stun"], a["windup"],
                               interruptible=True)
            return

        a = ready("pounce")
        if a:
            far = [h for h in heroes if a["min_range"] <= dist(boss.x, boss.y, h.x, h.y) <= a["range"]]
            if far:
                tgt = self.rng.choice(far)
                used("pounce", a)
                boss.busy = float(a["windup"])
                boss.move_to = None
                self.add_telegraph(boss, tgt.x, tgt.y, a["r"], base * a["dmg_mult"], a["stun"], a["windup"],
                                   leap=True, interruptible=True)

    # ---------------------------------------------------------------- pickups
    def add_pickup(self, kind: str, x: float, y: float, *, ttl: float | None = None, item: str | None = None) -> Pickup:
        pk = Pickup(id=self._next_pk, kind=kind, x=self._cx(x), y=self._cy(y), ttl=ttl, item=item)
        self._next_pk += 1
        self.pickups[pk.id] = pk
        self.pk_version += 1
        return pk

    def add_potion(self, x: float, y: float) -> Pickup | None:
        cfg = self.potion_cfg
        if not cfg or sum(1 for p in self.pickups.values() if p.kind == "potion") >= cfg["max_on_ground"]:
            return None
        return self.add_pickup("potion", x, y, ttl=float(cfg["lifetime_s"]))

    def remove_pickup(self, pid: int) -> None:
        if self.pickups.pop(pid, None) is not None:
            self.pk_version += 1

    def _step_pickups(self, dt: float) -> None:
        cfg = self.potion_cfg
        heroes = self.alive_heroes()
        if cfg and heroes:                                  # potions appear at random spots
            self.potion_timer -= dt
            if self.potion_timer <= 0:
                self.potion_timer = self.rng.uniform(cfg["spawn_min_s"], cfg["spawn_max_s"])
                self.add_potion(self.rng.uniform(120, self.w - 120), self.rng.uniform(100, self.h - 100))
        for pk in list(self.pickups.values()):
            if pk.ttl is not None:
                pk.ttl -= dt
                if pk.ttl <= 0:
                    self.remove_pickup(pk.id)
                    continue
            pk.retry = max(0.0, pk.retry - dt)
            pad = cfg.get("pickup_pad", 18) if cfg else 18
            for h in heroes:
                if not h.alive or dist(h.x, h.y, pk.x, pk.y) > h.radius + pad:
                    continue
                if pk.kind == "potion":
                    if h.hp >= h.max_hp:                    # full health: leave it for someone who needs it
                        continue
                    h.hp = min(h.max_hp, h.hp + h.max_hp * cfg["heal_pct"])
                    self.fx.append(["h", round(h.x), round(h.y)])
                    self.remove_pickup(pk.id)
                    break
                if pk.retry <= 0:                           # items: Match decides (inventory space)
                    pk.retry = 0.75
                    self.events.append(("loot", h.id, pk.id))
                    break

    # --------------------------------------------------------------- helpers
    def _cx(self, x: float) -> float:
        return min(max(x, 10.0), self.w - 10.0)

    def _cy(self, y: float) -> float:
        return min(max(y, 10.0), self.h - 10.0)
