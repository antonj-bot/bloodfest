"""Free-tier guard. Refuses or ends matches before Render/Neon free limits can be hit.

Bandwidth: every byte the server sends over WebSockets is metered in memory
(uncompressed size, so the real compressed traffic is LOWER than what we count),
plus a fixed estimate per page load. The running total is written to Neon at the
end of each match, so the count survives Render spin-downs and restarts.

Neon: a warm server costs 1 short DB session per match (written at the end); a cold start adds 1.
Sessions are counted too.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Limits
from .store import Store, Usage


def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@dataclass
class Verdict:
    ok: bool
    reason: str = ""


class Budget:
    def __init__(self, store: Store, limits: Limits, month_fn=current_month) -> None:
        self.store = store
        self.limits = limits
        self.month_fn = month_fn
        self.unflushed_bytes = 0            # metered but not yet written to the DB
        self.usage: Usage | None = None     # last value read from the DB
        self.usage_month: str | None = None
        self.leaderboard: list[dict] = []   # cached; HTTP never touches the DB

    # ------------------------------------------------------------ metering
    def meter(self, nbytes: int) -> None:
        self.unflushed_bytes += nbytes

    def month_egress(self) -> int:
        stored = self.usage.egress_bytes if self.usage and self.usage_month == self.month_fn() else 0
        return stored + self.unflushed_bytes

    def egress_exhausted(self) -> bool:
        """Cheap in-memory check, safe to call every tick."""
        return self.month_egress() >= self.limits.monthly_egress_cap_bytes

    # ------------------------------------------------------------ match hooks
    async def begin_match(self) -> Verdict:
        """Warm server: zero DB sessions (counters are already in memory).
        Cold start / new month: one session to load the stored counters."""
        month = self.month_fn()
        cap = self.limits.monthly_db_sessions_cap
        if self.usage is None or self.usage_month != month:
            try:
                usage, top = await self.store.begin_match(month)
            except Exception as exc:  # noqa: BLE001 - any DB failure
                if self.limits.fail_closed:
                    return Verdict(False, f"Database unreachable, refusing to start to protect the free tier ({type(exc).__name__}).")
                return Verdict(True, "Database unreachable; playing without saving.")
            self.usage, self.usage_month, self.leaderboard = usage, month, top

        # +1 because saving this match at the end needs one more session.
        if self.usage.db_sessions + 1 > cap:
            return Verdict(False, "Monthly database budget reached. Games resume next month.")
        if self.egress_exhausted():
            used = self.month_egress() / 1024 ** 3
            cap_gb = self.limits.monthly_egress_cap_bytes / 1024 ** 3
            return Verdict(False, f"Monthly bandwidth budget reached ({used:.2f}/{cap_gb:.2f} GB). Games resume next month.")
        return Verdict(True)

    async def end_match(self, seconds: int, result: dict | None) -> None:
        month = self.month_fn()
        flush = self.unflushed_bytes
        try:
            usage, top = await self.store.end_match(month, flush, seconds, result)
        except Exception:  # noqa: BLE001 - keep bytes in memory; next flush retries
            return
        self.unflushed_bytes -= flush
        self.usage, self.usage_month, self.leaderboard = usage, month, top

    def status(self) -> dict:
        lim = self.limits
        return {
            "month": self.month_fn(),
            "egress_gb": round(self.month_egress() / 1024 ** 3, 3),
            "egress_cap_gb": round(lim.monthly_egress_cap_bytes / 1024 ** 3, 3),
            "db_sessions": self.usage.db_sessions if self.usage and self.usage_month == self.month_fn() else None,
            "db_sessions_cap": lim.monthly_db_sessions_cap,
            "note": "Values refresh only when a match starts or ends (the DB is never polled).",
        }


class MatchClock:
    """Tracks wall-clock match length for the hard time cap."""

    def __init__(self) -> None:
        self.started = time.monotonic()

    def seconds(self) -> int:
        return int(time.monotonic() - self.started)
