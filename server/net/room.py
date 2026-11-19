"""A room = one match + its WebSocket clients + the game loop.

Free-tier rules enforced here:
  * The game loop only runs while a match is in progress. Lobbies send nothing
    except when something actually changes.
  * Every byte sent is metered into the Budget.
  * A match is force-ended if it exceeds its own bandwidth cap, the monthly cap,
    or the wall-clock cap.
  * Idle clients (no input for idle_kick_seconds) are disconnected, so a
    forgotten browser tab can't burn bandwidth.
"""
from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from dataclasses import dataclass, field

from ..budget import Budget, MatchClock
from ..config import GameData, Limits
from ..game.match import FIGHT, LOBBY, OVER, Match
from . import protocol


@dataclass
class Client:
    ws: object
    pid: str
    name: str
    last_input: float = field(default_factory=time.monotonic)
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.monotonic)


class Room:
    def __init__(self, code: str, data: GameData, limits: Limits, budget: Budget, on_empty) -> None:
        self.code = code
        self.data = data
        self.limits = limits
        self.budget = budget
        self.on_empty = on_empty
        self.match = Match(data, limits.max_players_per_room)
        self.clients: dict[str, Client] = {}
        self.host: str | None = None
        self.match_bytes = 0
        self.clock: MatchClock | None = None
        self._task: asyncio.Task | None = None
        self._starting = False
        self._closed = False

    # ============================================================ membership
    def join(self, ws, name: str, hero: str) -> Client:
        name = self._unique_name(name)
        pid = secrets.token_hex(4)
        self.match.add_player(pid, name, hero)   # raises ValueError if full / running
        c = Client(ws=ws, pid=pid, name=name, tokens=self.limits.max_msgs_per_second)
        self.clients[pid] = c
        self.host = self.host or pid
        self.budget.meter(self.limits.page_load_estimate_bytes)
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
        return c

    async def leave(self, pid: str) -> None:
        self.clients.pop(pid, None)
        self.match.remove_player(pid)
        if self.host == pid:
            self.host = next(iter(self.clients), None)
        if not self.clients:
            await self._close()
        else:
            await self.broadcast_lobby()

    def _unique_name(self, name: str) -> str:
        taken = {p.name for p in self.match.players.values()}
        base, n = name, 2
        while name in taken:
            name = f"{base[:13]}{n}"
            n += 1
        return name

    # ============================================================ input
    def allow(self, c: Client) -> bool:
        """Token-bucket rate limit per client."""
        now = time.monotonic()
        rate = self.limits.max_msgs_per_second
        c.tokens = min(rate, c.tokens + (now - c.last_refill) * rate)
        c.last_refill = now
        if c.tokens < 1:
            return False
        c.tokens -= 1
        c.last_input = now
        return True

    async def handle(self, c: Client, msg: dict) -> None:
        t = msg.get("t")
        m = self.match
        if t == "start" and c.pid == self.host:
            await self._start_match()
        elif t == "hero" and isinstance(msg.get("hero"), str):
            m.set_hero(c.pid, msg["hero"])
            await self.broadcast_lobby()
        elif t == "buy" and isinstance(msg.get("item"), str):
            err = m.buy(c.pid, msg["item"])
            if err:
                await self.send(c, {"t": "err", "msg": err})
        elif t == "sell" and isinstance(msg.get("i"), int):
            m.sell(c.pid, msg["i"])
        elif t == "ready":
            m.set_ready(c.pid)
        elif t in ("move", "attack", "stop", "cast", "suicide"):
            m.command(c.pid, msg)
        # "ping" and unknown types are ignored (but still count as activity).

    async def _start_match(self) -> None:
        if self.match.phase != LOBBY or self._starting:
            return
        self._starting = True
        try:
            verdict = await self.budget.begin_match()
            if not verdict.ok:
                await self.broadcast({"t": "err", "msg": verdict.reason})
                return
            if verdict.reason:
                await self.broadcast({"t": "info", "msg": verdict.reason})
            self.match.start()
            self.match_bytes = 0
            self.clock = MatchClock()
        finally:
            self._starting = False

    # ============================================================ loop
    async def _loop(self) -> None:
        sim_dt = 1.0 / self.limits.sim_hz
        net_every = max(1, round(self.limits.sim_hz / self.limits.net_hz))
        tick = 0
        last_phase = None
        try:
            while not self._closed:
                started = time.monotonic()
                m = self.match
                if m.phase == LOBBY:
                    if last_phase not in (None, LOBBY):
                        await self.broadcast_lobby()
                    last_phase = LOBBY
                    await self._kick_idle()
                    await asyncio.sleep(0.5)       # lobby: no simulation, no snapshots
                    continue

                m.step(sim_dt)
                self._guard()
                if m.finished is not None:
                    result, m.finished = m.finished, None
                    asyncio.create_task(self.budget.end_match(self.clock.seconds() if self.clock else 0, result))
                    await self.broadcast({"t": "over", "result": result})

                tick += 1
                phase_changed = m.phase != last_phase
                # Fights stream at net_hz; shop / round-end / results only need 1 update per second.
                due = tick % net_every == 0 if m.phase == FIGHT else tick % self.limits.sim_hz == 0
                if due or phase_changed:
                    await self._broadcast_snapshot(scoreboard=phase_changed or tick % (net_every * 10) == 0)
                last_phase = m.phase
                if tick % self.limits.sim_hz == 0:
                    await self._kick_idle()
                await asyncio.sleep(max(0.0, sim_dt - (time.monotonic() - started)))
        except asyncio.CancelledError:
            pass

    def _guard(self) -> None:
        m = self.match
        if m.phase in (LOBBY, OVER):
            return
        if not m.connected_players():
            m.abort("everyone left")
        elif self.match_bytes >= self.limits.match_egress_cap_bytes:
            m.abort("match bandwidth cap reached")
        elif self.budget.egress_exhausted():
            m.abort("monthly bandwidth budget reached")
        elif self.clock and self.clock.seconds() >= self.limits.max_match_seconds:
            m.abort("time limit reached")

    async def _kick_idle(self) -> None:
        now = time.monotonic()
        for c in list(self.clients.values()):
            if now - c.last_input > self.limits.idle_kick_seconds:
                await self.send(c, {"t": "kicked", "msg": "Disconnected for being idle."})
                with contextlib.suppress(Exception):
                    await c.ws.close()
                await self.leave(c.pid)

    # ============================================================ output
    async def _broadcast_snapshot(self, scoreboard: bool) -> None:
        m = self.match
        fx = m.world.fx if m.world else []
        shared = protocol.shared_snapshot(m, fx[:20], m.feed[:8], scoreboard)
        if m.world:
            m.world.fx = []
        m.feed.clear()
        for c in list(self.clients.values()):
            p = m.players.get(c.pid)
            if p:
                await self._send_text(c, protocol.snapshot_for(shared, m, p))

    async def broadcast_lobby(self) -> None:
        m = self.match
        players = [[p.slot, p.name, p.hero] for p in sorted(m.players.values(), key=lambda p: p.slot)]
        host_slot = m.players[self.host].slot if self.host in m.players else -1
        await self.broadcast({"t": "lobby", "code": self.code, "host": host_slot, "players": players,
                              "phase": m.phase})

    async def broadcast(self, obj: dict) -> None:
        text = protocol.dumps(obj)
        for c in list(self.clients.values()):
            await self._send_text(c, text)

    async def send(self, c: Client, obj: dict) -> None:
        await self._send_text(c, protocol.dumps(obj))

    async def _send_text(self, c: Client, text: str) -> None:
        n = len(text)                # ASCII JSON: chars == bytes (uncompressed, so we over-count)
        self.budget.meter(n)
        self.match_bytes += n
        try:
            await asyncio.wait_for(c.ws.send_text(text), timeout=2.0)
        except Exception:  # noqa: BLE001 - slow or dead socket: drop the client
            self.clients.pop(c.pid, None)
            self.match.remove_player(c.pid)

    async def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.match.phase not in (LOBBY, OVER):
            self.match.abort("everyone left")
            if self.match.finished:
                await self.budget.end_match(self.clock.seconds() if self.clock else 0, self.match.finished)
        self.on_empty(self.code)
        if self._task and self._task is not asyncio.current_task():
            self._task.cancel()
