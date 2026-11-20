# PUDGE_WARS_BANK_LOCK_BOTS_V3
# PUDGE_WARS_LEVELS_DYNAMIC_VISION_V1
# PUDGE_WARS_POLISH_V2
# PUDGE_WARS_ABILITIES_POTIONS_V1
# HOOK_WARS_MODE_V1
"""Team hook arena mode: two locked banks, hooks, pulls, respawns and team kills."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .match import LOBBY, SHOP, FIGHT, OVER, Player
from .world import HERO, Pickup, Projectile, Unit

LEFT, RIGHT = "radiant", "dire"

@dataclass
class Hook:
    owner: int
    team: str
    x: float
    y: float
    vx: float
    vy: float
    distance: float
    max_distance: float
    radius: float = 19.0
    victim: int | None = None
    potion: int | None = None
    returning: bool = False
    hit_ids: set[int] = field(default_factory=set)

class HookWorld:
    def __init__(self, w: int, h: int, river_w: int = 170):
        self.w, self.h = w, h
        self.river_w = river_w
        self.mid = w / 2
        self.units: dict[int, Unit] = {}
        self.registry = {}
        self.projectiles: list[Projectile] = []
        self.hooks: list[Hook] = []
        self.fx: list[list] = []
        self.pickups = {}
        self.pk_version = 0
        self.events: list[tuple] = []
        self.time_limit = 9999.0
        self.t = 0.0
        self._next_id = 1
        self._next_pk = 1
        self.potion_clock = 5.0

        self.potion_velocity: dict[int, tuple[float, float]] = {}
        self.rng = random.Random()
    def spawn_hero(self, p: Player, team: str, stats: dict, rng: random.Random) -> Unit:
        left = team == LEFT
        x = 230 if left else self.w - 230
        y = 120 + (p.slot % 5) * ((self.h - 240) / 4)
        u = Unit(self._next_id, HERO, team, x, y, stats["radius"], stats["max_hp"],
                 stats["dmg"], stats["armor"], stats["atk_range"], stats["atk_cd"], stats["speed"],
                 hp=stats["max_hp"], owner=p.pid, base_atk_cd=stats["atk_cd"], base_speed=stats["speed"])
        self._next_id += 1
        self.units[u.id] = u
        self.registry[u.id] = (HERO, p.pid, 1.0)
        return u

    def alive_heroes(self):
        return [u for u in self.units.values() if u.kind == HERO and u.alive]

    def _bank_limit(self, u: Unit, x: float) -> float:
        pad = self.river_w / 2 + u.radius + 4
        # Lock voluntary movement to the bank currently occupied. Forced hook
        # movement bypasses this method, so only another hook can cross the river.
        on_left_bank = u.x < self.mid
        return min(x, self.mid - pad) if on_left_bank else max(x, self.mid + pad)

    def move(self, uid: int, x: float, y: float):
        u = self.units.get(uid)
        if not u or not u.alive or u.stunned > 0:
            return
        u.move_to = (self._bank_limit(u, max(u.radius, min(self.w-u.radius, x))),
                     max(u.radius, min(self.h-u.radius, y)))
        u.target_id = None

    def cast_hook(self, uid: int, x: float, y: float, cfg: dict) -> bool:
        u = self.units.get(uid)
        if not u or not u.alive or u.stunned > 0 or u.cds.get("q", 0) > 0:
            return False
        dx, dy = x-u.x, y-u.y
        n = math.hypot(dx, dy)
        if n < 1:
            return False
        speed = float(cfg["speed"])
        self.hooks.append(Hook(uid, u.team, u.x, u.y, dx/n*speed, dy/n*speed, 0,
                               float(cfg["range"]), float(cfg.get("radius", 19))))
        u.cds["q"] = float(cfg["cooldown"])
        self.fx.append(["c", "hook", round(u.x), round(u.y), round(x), round(y)])
        return True

    def blink(self, uid: int, x: float, y: float, cfg: dict) -> bool:
        u = self.units.get(uid)
        if not u or not u.alive or u.stunned > 0 or u.cds.get("e", 0) > 0:
            return False
        dx, dy = x-u.x, y-u.y
        d = math.hypot(dx, dy)
        if d < 1: return False
        reach = min(d, float(cfg["range"]))
        nx, ny = u.x + dx/d*reach, u.y + dy/d*reach
        # Blink is mobility, not a river crossing tool.
        u.x = self._bank_limit(u, max(u.radius, min(self.w-u.radius, nx)))
        u.y = max(u.radius, min(self.h-u.radius, ny))
        u.move_to = None
        u.cds["e"] = float(cfg["cooldown"])
        self.fx.append(["c", "blink", round(u.x), round(u.y), 0, 0])
        return True

    def _spawn_potion(self, cfg: dict):
        side = LEFT if self.rng.random() < .5 else RIGHT
        margin = self.river_w/2 + 55
        lo, hi = (90, self.mid-margin) if side == LEFT else (self.mid+margin, self.w-90)
        p = Pickup(self._next_pk, "potion", self.rng.uniform(lo, hi), self.rng.uniform(80, self.h-80), float(cfg["ttl"]))
        # item carries the hidden effect name; wire format intentionally remains generic.
        p.item = self.rng.choice(["heal", "shield", "refresh"])
        self.pickups[p.id] = p; self._next_pk += 1; self.pk_version += 1
        ang = self.rng.random() * math.tau
        speed = float(cfg.get("move_speed", 55))
        self.potion_velocity[p.id] = (math.cos(ang)*speed, math.sin(ang)*speed)

    def _remove_potion(self, pid: int):
        self.pickups.pop(pid, None)
        self.potion_velocity.pop(pid, None)
        self.pk_version += 1

    def _step_potions(self, dt: float, cfg: dict):
        self.potion_clock -= dt
        if self.potion_clock <= 0 and len(self.pickups) < int(cfg["max_alive"]):
            self._spawn_potion(cfg); self.potion_clock = float(cfg["spawn_every"])
        margin = self.river_w/2 + 30
        for pid, p in list(self.pickups.items()):
            p.ttl = (p.ttl or 0)-dt
            if p.ttl <= 0:
                self._remove_potion(pid); continue
            # Hooked potions are positioned by the hook and do not drift independently.
            if any(h.potion == pid for h in self.hooks):
                continue
            vx, vy = self.potion_velocity.get(pid, (0.0, 0.0))
            p.x += vx*dt; p.y += vy*dt
            left_bank = p.x < self.mid
            min_x, max_x = (45, self.mid-margin) if left_bank else (self.mid+margin, self.w-45)
            if p.x <= min_x or p.x >= max_x:
                p.x=max(min_x,min(max_x,p.x));vx=-vx
            if p.y <= 45 or p.y >= self.h-45:
                p.y=max(45,min(self.h-45,p.y));vy=-vy
            self.potion_velocity[pid]=(vx,vy)
            for u in self.alive_heroes():
                if math.hypot(u.x-p.x,u.y-p.y) > u.radius+22: continue
                if p.item == "heal": u.hp=min(u.max_hp,u.hp+float(cfg["heal"])); label="MEGA HEAL"
                elif p.item == "shield": u.shield+=float(cfg["shield"]);u.shield_t=max(u.shield_t,8);label="IRON SKIN"
                else:
                    u.cds["q"]=max(0,u.cds.get("q",0)-float(cfg["refresh_seconds"]));u.cds["e"]=0;label="ARCANE REFRESH"
                self._remove_potion(pid)
                self.fx.append(["c","potion",round(u.x),round(u.y),0,0])
                self.events.append(("potion",u.id,label));break

    def damage(self, attacker: Unit | None, victim: Unit, amount: float):
        if not victim.alive:
            return
        amount = max(1.0, amount * 100.0 / (100.0 + max(-80.0, victim.armor * 6.0)))
        victim.hp -= amount
        if victim.hp <= 0:
            victim.hp, victim.alive, victim.move_to = 0, False, None
            self.events.append(("death", victim.id, attacker.id if attacker else None))

    def _step_hook(self, h: Hook, dt: float, cfg: dict) -> bool:
        owner = self.units.get(h.owner)
        if not owner or not owner.alive:
            return False
        if h.potion is not None:
            p = self.pickups.get(h.potion)
            if not p:
                return False
            dx, dy = owner.x-p.x, owner.y-p.y
            d = math.hypot(dx, dy)
            if d <= owner.radius + 28:
                # Drop beside the hooker. Any player can collect it immediately.
                side = 1 if owner.team == LEFT else -1
                p.x = max(30, min(self.w-30, owner.x + side*54)); p.y = owner.y
                ang = self.rng.random()*math.tau
                self.potion_velocity[p.id]=(math.cos(ang)*38,math.sin(ang)*38)
                self.pk_version += 1
                return False
            step=min(d,float(cfg["pull_speed"])*dt)
            p.x += dx/d*step; p.y += dy/d*step
            h.x,h.y=p.x,p.y
            self.pk_version += 1
            return True
        if h.victim is not None:
            v = self.units.get(h.victim)
            if not v or not v.alive:
                return False
            dx, dy = owner.x-v.x, owner.y-v.y
            d = math.hypot(dx, dy)
            if d <= owner.radius + v.radius + 18:
                # A hooked enemy is intentionally allowed across the river. Place it
                # beside the hook owner on the owner's bank; normal movement remains
                # locked to the victim's own bank afterward.
                side = 1 if owner.team == LEFT else -1
                v.x = owner.x + side * (owner.radius + v.radius + 22)
                v.x = max(v.radius, min(self.w - v.radius, v.x))
                v.y = owner.y
                v.move_to = None
                v.stunned = max(v.stunned, float(cfg["arrival_stun"]))
                return False
            step = min(d, float(cfg["pull_speed"])*dt)
            # Pull movement bypasses _bank_limit by design. Only player-issued
            # movement is constrained by the uncrossable river.
            v.x += dx/d*step; v.y += dy/d*step
            h.x, h.y = v.x, v.y
            return True
        if h.returning:
            dx, dy = owner.x-h.x, owner.y-h.y
            d = math.hypot(dx, dy)
            if d < 30:
                return False
            step = min(d, math.hypot(h.vx,h.vy)*dt)
            h.x += dx/d*step; h.y += dy/d*step
            return True
        h.x += h.vx*dt; h.y += h.vy*dt; h.distance += math.hypot(h.vx,h.vy)*dt
        if not (0 <= h.x <= self.w and 0 <= h.y <= self.h) or h.distance >= h.max_distance:
            h.returning = True
            return True
        for v in self.alive_heroes():
            if v.team == h.team or v.id in h.hit_ids:
                continue
            if math.hypot(v.x-h.x,v.y-h.y) <= v.radius+h.radius:
                h.victim = v.id
                v.stunned = max(v.stunned, float(cfg["pull_stun"]))
                self.damage(owner, v, float(cfg["damage"]))
                self.fx.append(["h", "hook", round(v.x), round(v.y), round(owner.x), round(owner.y)])
                return v.alive
        for p in self.pickups.values():
            if math.hypot(p.x-h.x,p.y-h.y) <= h.radius+22:
                h.potion=p.id
                self.potion_velocity[p.id]=(0.0,0.0)
                self.fx.append(["h","potion_hook",round(p.x),round(p.y),round(owner.x),round(owner.y)])
                return True
        return True

    def step(self, dt: float, hook_cfg: dict, potion_cfg: dict):
        self.t += dt
        for u in self.units.values():
            if not u.alive: continue
            u.stunned = max(0.0, u.stunned-dt)
            u.atk_timer = max(0.0, u.atk_timer-dt)
            for k in list(u.cds): u.cds[k] = max(0.0, u.cds[k]-dt)
            if u.move_to and u.stunned <= 0:
                dx,dy=u.move_to[0]-u.x,u.move_to[1]-u.y; d=math.hypot(dx,dy)
                if d <= u.speed*dt: u.x,u.y=u.move_to;u.move_to=None
                elif d: u.x+=dx/d*u.speed*dt;u.y+=dy/d*u.speed*dt
        self.hooks = [h for h in self.hooks if self._step_hook(h,dt,hook_cfg)]
        self._step_potions(dt, potion_cfg)
        # Reuse the normal compact projectile packet for hook heads. The client already draws chain_hook.
        self.projectiles = [Projectile(h.owner,h.team,h.x,h.y,h.vx,h.vy,1,0,h.radius,
                                       style="steel",visual="chain_hook") for h in self.hooks]

class HookWarsMatch:
    """Room-compatible Match implementation used only when mode=hook_wars."""
    mode = "hook_wars"
    def __init__(self, data, max_players: int, rng=None):
        self.data, self.g = data, data.game
        self.cfg = self.g.get("hook_wars", {})
        self.max_players = min(10, max(2, int(self.cfg.get("max_players", 10))))
        self.rng = rng or random.Random()
        self.players: dict[str,Player] = {}
        self.phase, self.round, self.timer = LOBBY, 0, 0.0
        self.world = None
        self.feed, self.finished = [], None
        self._respawns: dict[str,float] = {}
        self.team_score = {LEFT:0, RIGHT:0}
        self.bot_pids: set[str] = set()
        self._bot_seq = 0
        self._bot_think = 0.0

    def add_player(self,pid,name,hero):
        if len(self.players)>=self.max_players: raise ValueError("Room is full.")
        if hero not in self.data.heroes: raise ValueError("Unknown hero.")
        used={p.slot for p in self.players.values()}; slot=next(i for i in range(self.max_players) if i not in used)
        p=Player(pid,name,hero,slot,gold=0); self.players[pid]=p; return p
    def set_hero(self,pid,hero):
        if self.phase==LOBBY and hero in self.data.heroes: self.players[pid].hero=hero
    def add_bot(self, team: str):
        if self.phase != LOBBY: raise ValueError("Bots can only be added in the lobby.")
        if len(self.players) >= self.max_players: raise ValueError("Room is full.")
        self._bot_seq += 1
        pid=f"bot:{self._bot_seq}"
        hero=next(iter(self.data.heroes))
        p=self.add_player(pid,f"Hook Bot {self._bot_seq}",hero)
        want_even=team==LEFT
        occupied={q.slot for q in self.players.values() if q.pid!=pid}
        slots=[i for i in range(self.max_players) if i not in occupied and (i%2==0)==want_even]
        if slots:p.slot=slots[0]
        self.bot_pids.add(pid)
        return p

    def remove_player(self,pid):
        if pid in self.players: self.players[pid].connected=False
        if self.world and pid in self.players and self.players[pid].unit_id in self.world.units:
            self.world.units[self.players[pid].unit_id].alive=False
    def connected_players(self): return [p for p in self.players.values() if p.connected]
    def spawn_late_player(self,pid):
        if self.phase==FIGHT and self.world: self._spawn(self.players[pid])
    def set_ready(self,pid): pass
    def buy(self,*a): return "The shop is disabled in Hook Wars."
    craft=buy
    def sell(self,*a): pass
    def xp_needed(self,level): return 100
    def is_boss_round(self,*a): return False
    def hero_stats(self,p):
        h=self.data.heroes[p.hero]
        return {"max_hp":float(self.cfg.get("hero_hp",900)),"dmg":float(self.cfg.get("attack_damage",70)),
                "armor":float(self.cfg.get("armor",4)),"atk_range":float(h["range"]),"atk_cd":float(h["atk_cd"]),
                "speed":float(self.cfg.get("move_speed",215)),"radius":float(h["radius"]),
                "spell_power":1.0,"lifesteal":0.0}
    def _team(self,p): return LEFT if p.slot%2==0 else RIGHT
    def _spawn(self,p):
        u=self.world.spawn_hero(p,self._team(p),self.hero_stats(p),self.rng);p.unit_id=u.id;self._respawns.pop(p.pid,None)
    def start(self):
        if self.phase!=LOBBY or not self.connected_players(): return
        a=self.g["arena"];self.world=HookWorld(a["w"],a["h"],int(self.cfg.get("river_width",170)))
        self.team_score={LEFT:0,RIGHT:0};self.round=1;self.phase=FIGHT
        for p in self.connected_players(): self._spawn(p)
        self.feed.append("HOOK WARS: Q throws the hook. Pull enemies onto your bank and kill them.")
    def command(self,pid,msg):
        p=self.players.get(pid);u=self.world.units.get(p.unit_id) if p and self.world and p.unit_id else None
        if not u or not u.alive:return
        t=msg.get("t")
        if t=="move": self.world.move(u.id,float(msg.get("x",u.x)),float(msg.get("y",u.y)))
        elif t=="stop": u.move_to=None
        elif t=="cast" and msg.get("slot")=="q":
            hook_cfg = dict(self.cfg["hook"])
            growth = self.cfg["leveling"]
            bonus = max(0, p.level-1)
            hook_cfg["range"] += bonus * float(growth["range_per_level"])
            hook_cfg["radius"] += bonus * float(growth["radius_per_level"])
            hook_cfg["damage"] += bonus * float(growth["damage_per_level"])
            hook_cfg["cooldown"] = max(float(growth["min_cooldown"]), hook_cfg["cooldown"]-bonus*float(growth["cooldown_per_level"]))
            self.world.cast_hook(u.id,float(msg.get("x",u.x)),float(msg.get("y",u.y)),hook_cfg)
        elif t=="cast" and msg.get("slot")=="e": self.world.blink(u.id,float(msg.get("x",u.x)),float(msg.get("y",u.y)),self.cfg["blink"])
        elif t=="attack" and isinstance(msg.get("id"),int):
            v=self.world.units.get(msg["id"])
            if v and v.alive and v.team!=u.team and math.hypot(v.x-u.x,v.y-u.y)<=u.atk_range+v.radius and u.atk_timer<=0:
                self.world.damage(u,v,u.dmg);u.atk_timer=u.atk_cd
    def _step_bots(self, dt: float):
        self._bot_think -= dt
        if self._bot_think > 0 or not self.world: return
        self._bot_think = .30
        for pid in tuple(self.bot_pids):
            p=self.players.get(pid);u=self.world.units.get(p.unit_id) if p and p.unit_id else None
            if not u or not u.alive: continue
            enemies=[v for v in self.world.alive_heroes() if v.team!=u.team]
            if not enemies: continue
            target=min(enemies,key=lambda v:math.hypot(v.x-u.x,v.y-u.y))
            if u.cds.get("q",0)<=0:
                self.command(pid,{"t":"cast","slot":"q","x":target.x,"y":target.y+self.rng.uniform(-24,24)})
            elif math.hypot(target.x-u.x,target.y-u.y)<=u.atk_range+target.radius:
                self.command(pid,{"t":"attack","id":target.id})
            else:
                self.command(pid,{"t":"move","x":u.x+self.rng.uniform(-45,45),"y":max(55,min(self.world.h-55,target.y+self.rng.uniform(-80,80)))})

    def step(self,dt):
        if self.phase==OVER:
            self.timer-=dt
            if self.timer<=0:self.phase=LOBBY
            return
        if self.phase!=FIGHT:return
        self.world.step(dt,self.cfg["hook"],self.cfg["potions"])
        self._step_bots(dt)
        for event in self.world.events:
            if event[0]=="potion":
                who=next((p for p in self.players.values() if p.unit_id==event[1]),None)
                if who:self.feed.append(f"{who.name} found {event[2]}!")
                continue
            if event[0]!="death":continue
            victim=next((p for p in self.players.values() if p.unit_id==event[1]),None)
            killer=next((p for p in self.players.values() if p.unit_id==event[2]),None)
            if not victim:continue
            scoring=self._team(killer) if killer and killer.pid!=victim.pid else (RIGHT if self._team(victim)==LEFT else LEFT)
            self.team_score[scoring]+=1
            if killer:
                killer.kills += 1; killer.points += 1
                growth = self.cfg["leveling"]
                new_level = min(int(growth["max_level"]), 1 + killer.kills // int(growth["kills_per_level"]))
                if new_level > killer.level:
                    killer.level = new_level
                    self.feed.append(f"{killer.name} reached Hook Lv {new_level}: +{growth['range_per_level']} range, +{growth['radius_per_level']} width!")
            self.feed.append(f"{killer.name if killer else scoring.title()} scored! {self.team_score[LEFT]} - {self.team_score[RIGHT]}")
            self._respawns[victim.pid]=float(self.cfg.get("respawn_seconds",4))
        self.world.events.clear()
        for pid in list(self._respawns):
            self._respawns[pid]-=dt
            if self._respawns[pid]<=0 and self.players[pid].connected:self._spawn(self.players[pid])
        target=int(self.cfg.get("kills_to_win",20))
        winner=next((t for t,s in self.team_score.items() if s>=target),None)
        if winner:
            for p in self.players.values(): p.points=self.team_score[self._team(p)]
            self.finished={"rounds":1,"winner":winner.title(),"mode":"hook_wars","players":[{"name":p.name,"hero":p.hero,"points":p.points,"kills":p.kills,"boss_kills":0,"level":1} for p in self.players.values()]}
            self.phase=OVER;self.timer=float(self.g.get("results_seconds",8))
    def abort(self,reason):
        self.finished={"rounds":1,"winner":None,"aborted":True,"reason":reason,"mode":"hook_wars","players":[]};self.phase=OVER;self.timer=1
