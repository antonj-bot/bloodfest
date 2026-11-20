"""FastAPI entry point.

Routes:
  GET  /                 game page
  GET  /static/...       client files (long cache headers -> fewer bytes on repeat visits)
  GET  /health           Render health check. Never touches the DB.
  GET  /api/status       rooms + free-tier budget (from memory, never touches the DB)
  GET  /api/leaderboard  cached leaderboard (refreshed only at match start/end)
  POST /api/rooms        create a room, returns its code
  WS   /ws/{code}        play
"""
from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .budget import Budget
from .config import Limits, load_game_data, load_limits
from .net.protocol import dumps
from .net.room import Room
from .store import FileStore, NeonStore, Store

CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"
NAME_RE = re.compile(r"[^A-Za-z0-9_\- ]")
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class CachedStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp


def default_store() -> Store:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return NeonStore(url)
    return FileStore(Path(os.getenv("BF_LOCAL_STORE", "local_usage.json")))


def create_app(store: Store | None = None, limits: Limits | None = None) -> FastAPI:
    limits = limits or load_limits()
    data = load_game_data()
    budget = Budget(store or default_store(), limits)
    rooms: dict[str, Room] = {}

    app = FastAPI(title="Bloodfest", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=800)
    app.mount("/static", CachedStatic(directory=CLIENT_DIR), name="static")
    app.state.budget, app.state.rooms = budget, rooms

    hello_static = {
        "heroes": {k: {"name": h["name"], "range": h["range"],
                       "skills": {s: {"name": d["name"], "cd": d["cd"], "type": d["type"]}
                                  for s, d in h["skills"].items()}}
                   for k, h in data.heroes.items()},
        "items": {k: {"name": i["name"], "cost": i["cost"], "stats": i["stats"],
                       "drop": bool(i.get("drop_only")), "recipe": i.get("recipe"),
                       "combine": int(i.get("combine_cost", 0))}
                  for k, i in data.items.items()},
        "arena": data.game["arena"],
        "rounds": data.game["rounds_total"],
        "boss_every": data.game["boss_every"],
    }

    @app.get("/")
    async def index():
        return FileResponse(CLIENT_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/health")
    async def health():
        return PlainTextResponse("ok")

    @app.get("/api/status")
    async def status():
        return {"rooms": len(rooms), "max_rooms": limits.max_rooms,
                "players": sum(len(r.clients) for r in rooms.values()), "budget": budget.status()}

    @app.get("/api/leaderboard")
    async def leaderboard():
        return budget.leaderboard

    @app.post("/api/rooms")
    async def create_room(mode: str = "bloodfest", bots: int = 0):
        if mode not in {"bloodfest", "hook_wars"}:
            raise HTTPException(400, "Unknown game mode.")
        if len(rooms) >= limits.max_rooms:
            raise HTTPException(503, "All rooms are busy. Try again later.")
        if budget.egress_exhausted():
            raise HTTPException(503, "Monthly bandwidth budget reached.")
        code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(5))
        rooms[code] = Room(code, data, limits, budget, on_empty=lambda c: rooms.pop(c, None), mode=mode)
        if mode == "hook_wars":
            bots = max(0, min(8, int(bots)))
            for i in range(bots):
                rooms[code].match.add_bot("radiant" if i % 2 == 0 else "dire")
        return {"code": code}

    @app.websocket("/ws/{code}")
    async def play(ws: WebSocket, code: str):
        await ws.accept()
        room = rooms.get(code.upper())
        if room is None:
            await ws.send_text(dumps({"t": "err", "msg": "Room not found or expired. Create a new one."}))
            await ws.close(code=4001, reason="room not found")
            return
        name = NAME_RE.sub("", ws.query_params.get("name", ""))[:16].strip() or "Player"
        hero = ws.query_params.get("hero", "ronin")
        try:
            client = room.join(ws, name, hero)
        except ValueError as exc:
            msg = str(exc)
            await ws.send_text(dumps({"t": "err", "msg": msg}))
            close_code = 4002 if "full" in msg.lower() else 4003 if "start" in msg.lower() or "running" in msg.lower() else 4000
            await ws.close(code=close_code, reason=msg[:120])
            return

        p = room.match.players[client.pid]
        await room.send(client, {"t": "hello", "slot": p.slot, "name": p.name, "code": room.code, "mode": room.mode, **hello_static})
        if room.match.phase == "lobby":
            await room.broadcast_lobby()
        else:
            await room.send_current_state(client)
            await room.broadcast_lobby()
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > limits.max_msg_bytes or not room.allow(client):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    await room.handle(client, msg)
        except WebSocketDisconnect:
            pass
        except RuntimeError:
            pass
        finally:
            await room.leave(client.pid)

    return app


app = create_app() if os.getenv("BF_NO_AUTOAPP") != "1" else None
