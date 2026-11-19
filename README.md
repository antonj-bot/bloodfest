# Bloodfest Arena

A browser free-for-all arena game for you and your friends. Host it once on Render and share a link.

- **Everyone vs everyone.** Heroes attack each other. Farmable minions attack anything that isn't a minion, **including the boss**. The boss attacks everyone.
- **Boss every 2 rounds**, and each boss is stronger: HP ×1.5, damage ×1.3, +1 armor per boss. Boss 2 adds a stunning slam, boss 3+ also summons adds, and every boss enrages after 90 s.
- **When you die, you're out** and spectate until every hero is dead. The last hero standing gets +3 points.
- **Suicide:** press **K twice**. Leaving the game counts as dying.
- **Storm:** after 150 s everything bleeds out with growing damage, so every round is guaranteed to end.
- **Shop** between rounds (25 s). After 10 rounds, the player with the most points wins.

| Points | |
|---|---|
| Kill a hero | +2 (plus gold and XP) |
| Last hit on the boss | +5 (plus 300 gold and 300 XP) |
| Last hero standing | +3 |

**Controls:** right-click to move or attack · **Q W E R** cast at the mouse · **S** stop · **K K** suicide

---

## Free-tier guarantees (hard requirements)

| Limit | Free allowance | How Bloodfest stays under it |
|---|---|---|
| Render bandwidth | 5 GB/month (Hobby) | Every WebSocket byte is metered. **No new matches after 3.5 GB.** A running match is force-ended if the month's cap is hit or the match passes 150 MB. Snapshots are compact integer arrays at about 6.7/s during fights and 1/s in the shop, with per-message compression. A full 6-player room uses about 0.07 GB/hour *before* compression (`tests/test_bandwidth.py`). |
| Render instance hours | 750/month | One free service (744 h max in a month). Free services spin down after 15 min idle. Lobbies send nothing on their own, and idle clients are kicked after 3 min. |
| Render build minutes | 500/month | `buildFilter` skips builds for README and test changes. |
| Neon compute | 100 CU-hours/month | **1 short DB session per match** (written at the end; a cold start adds one read), with no pool, no polling, and no DB in `/health`. Capped at 1500 sessions/month, which is about 31 CU-hours worst case at 0.25 CU. |
| Neon storage | 1 GB | Leaderboard rows plus only the newest 500 matches. |
| Unknown usage | — | **Fail closed:** if Neon can't be reached, usage can't be counted, so matches don't start. |

Usage totals live in Neon (`usage_month`), so they survive Render restarts and spin-downs. Check them at `/api/status`.

**Two account settings make this airtight:**
1. **Render: don't add a payment method to your workspace.** Without one, Render suspends free services when a quota runs out instead of charging you.
2. **Neon:** stay on the Free plan, which never bills overages, and set the compute size to a max of **0.25 CU**.

---

## Run locally (PowerShell)

```powershell
cd "C:\Python Projects\Bloodfest"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest -q
uvicorn server.main:app --reload --port 8000
```

Open http://localhost:8000, click **Create room**, then open the copied link in a second browser window to play against yourself. Without `DATABASE_URL`, usage is saved to `local_usage.json` instead of Neon.

## Deploy

1. **GitHub:** push this folder to a new repository.
2. **Neon:** create a project in region **AWS Asia Pacific (Singapore)**, open **Compute → Edit**, and set the size to **0.25 CU**. Copy the connection string (it includes `sslmode=require`). Tables are created automatically on the first match, or you can run `schema.sql` in the SQL editor.
3. **Render:** go to **New → Blueprint**, pick the repo, and paste the Neon string when asked for `DATABASE_URL`.
4. Share `https://<your-service>.onrender.com/?room=CODE` with your friends.

> The first visit after 15 idle minutes takes about 1 minute while Render wakes the server. Open the link yourself before your friends join.

## Project layout

```
server/
  config.py          limits (env-overridable) + game data loader
  budget.py          free-tier guard: metering, caps, fail-closed
  store.py           Neon (2 sessions/match) + local JSON store
  main.py            FastAPI routes + WebSocket endpoint
  game/world.py      pure simulation: combat, skills, AI, projectiles, storm
  game/match.py      rounds, boss rounds, shop, XP, rewards, scoring
  net/protocol.py    compact snapshot format
  net/room.py        game loop, rate limiting, idle kick, bandwidth caps
  data/*.json        heroes, items, bosses, game rules (tune without code)
client/              index.html, style.css, game.js (plain canvas, no libraries)
tests/               world, match, budget, app, bandwidth
```

## Tuning

Balance changes go in the `server/data/*.json` files: `game.json` (rounds, storm, rewards, minions), `heroes.json`, `items.json` and `bosses.json`. Free-tier limits are environment variables (see `.env.example`). Only *lower* them.
