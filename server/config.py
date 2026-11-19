"""All tunable limits live here.

Every limit exists to keep Bloodfest inside the FREE tiers:
  * Render Hobby: 5 GB outbound bandwidth / month, 750 instance hours, 500 build minutes.
  * Neon Free:    100 CU-hours / project / month, 1 GB storage, 5 GB transfer.

Defaults are deliberately conservative. Override with environment variables.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
GB = 1024 ** 3
MB = 1024 ** 2


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Limits:
    # --- Render bandwidth (the tightest free limit: 5 GB/month) ---------------
    monthly_egress_cap_bytes: int   # refuse new matches above this (default 3.5 GB = 70% of 5 GB)
    match_egress_cap_bytes: int     # a single match is force-ended above this
    page_load_estimate_bytes: int   # charged to the meter per WebSocket join (covers HTML/JS/TLS overhead)

    # --- Neon compute (100 CU-hours/month) ------------------------------------
    # Each DB session wakes Neon for at most ~5 min at 0.25 CU = ~0.021 CU-h.
    # 1500 sessions x 0.021 = ~31 CU-h worst case, far below 100.
    monthly_db_sessions_cap: int
    fail_closed: bool               # if Neon can't be reached, refuse to start matches

    # --- Server load / abuse ----------------------------------------------------
    max_rooms: int
    max_players_per_room: int
    sim_hz: int                     # game simulation rate
    net_hz: int                     # snapshot broadcast rate (bandwidth driver)
    idle_kick_seconds: int          # no input for this long -> disconnected
    max_msgs_per_second: int
    max_msg_bytes: int
    max_match_seconds: int          # hard wall-clock cap per match


def load_limits() -> Limits:
    return Limits(
        monthly_egress_cap_bytes=int(_env_float("BF_MONTHLY_EGRESS_GB", 3.5) * GB),
        match_egress_cap_bytes=int(_env_float("BF_MATCH_EGRESS_MB", 150) * MB),
        page_load_estimate_bytes=_env_int("BF_PAGE_LOAD_BYTES", 120_000),
        monthly_db_sessions_cap=_env_int("BF_MONTHLY_DB_SESSIONS", 1500),
        fail_closed=_env_bool("BF_FAIL_CLOSED", True),
        max_rooms=_env_int("BF_MAX_ROOMS", 2),
        max_players_per_room=_env_int("BF_MAX_PLAYERS", 6),
        sim_hz=_env_int("BF_SIM_HZ", 20),
        net_hz=_env_int("BF_NET_HZ", 6),
        idle_kick_seconds=_env_int("BF_IDLE_KICK_S", 180),
        max_msgs_per_second=_env_int("BF_MAX_MSGS_PER_S", 20),
        max_msg_bytes=_env_int("BF_MAX_MSG_BYTES", 256),
        max_match_seconds=_env_int("BF_MAX_MATCH_S", 45 * 60),
    )


@dataclass(frozen=True)
class GameData:
    game: dict
    heroes: dict
    items: dict
    bosses: dict


def load_game_data(data_dir: Path = DATA_DIR) -> GameData:
    def read(name: str) -> dict:
        return json.loads((data_dir / name).read_text(encoding="utf-8"))

    return GameData(
        game=read("game.json"),
        heroes=read("heroes.json"),
        items=read("items.json"),
        bosses=read("bosses.json"),
    )
