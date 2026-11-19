# Bloodfest Arena

A browser free-for-all arena game for you and your friends. Host it once on Render and share a link.

- **Everyone vs everyone.** Heroes attack each other. Farmable minions attack anything that isn't a minion, **including the boss**. The boss attacks everyone.
- **Boss every 2 rounds**, and each boss is stronger: HP ×1.5, damage ×1.3, +1 armor per boss. Boss 2 adds a stunning slam, boss 3+ also summons adds, and every boss enrages after 90 s.
- **When you die, you're out** and spectate until every hero is dead. The last hero standing gets +3 points.
- **Suicide:** press **K twice**. Leaving the game counts as dying.
- **Storm:** after 45 s everything bleeds out with growing damage, so every round is guaranteed to end.
- **Shop** between rounds (12 s). After 10 rounds, the player with the most points wins.

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

## Pacing (v2)

| Phase | Time |
|---|---|
| Shop | 12 s (ends early when everyone clicks Ready) |
| Fight | storm starts at 45 s, hard cap 70 s, boss enrages at 30 s |
| Round break / results | 2 s / 8 s |

A 10-round match takes roughly 8 minutes (bot-simulated; humans will vary).
All art is drawn on the canvas in the browser, so it adds **zero** network traffic.
Network update rate and database use are unchanged.

## Boss skills, boss loot and potions (v3)

Every skill shows a **red warning circle** that fills up before it lands, so you can run out of it.
A **stun interrupts** Pounce and Ground Slam. Skills unlock with the boss number and stack:

| Boss | Name | New skill | Loot |
|---|---|---|---|
| 1 | Gorehound | **Pounce**: marks a hero, leaps there, damage + stun | Gorehound's Fang |
| 2 | The Butcher | **Ground Slam**: big stunning ring around itself | Butcher's Cleaver |
| 3 | Ashen Colossus | **Summon Imps** | Ashen Heart |
| 4 | Maw of Ruin | **Meteor Rain**: several circles, always one on every hero | Maw Crown |
| 5 | Blood Sovereign | **Bloodlust**: heals itself from damage it deals (one more meteor too) | Sovereign's Brand |

- **Boss loot:** when a boss dies (by anyone, or the storm) its item drops on the floor with a golden beam.
  **Whoever touches it first claims it**, and it applies instantly. Your pack holds 6 items; if it is full the item stays on the floor.
  Boss-only items are never in the shop and sell for half their listed value.
- **Healing potions** appear at random spots (every 10-18 s, at most 2 on the floor, they vanish after 16 s)
  and drop from minions (6%). A potion heals 25% of max HP and **can only be picked up when you are hurt**.
  No new potions spawn once the storm starts.

Everything above is in `server/data/` (`bosses.json`, `items.json`, `game.json` -> `potions`).

**Free-tier impact: none.** Pickups are sent only when they change (plus a resync every 5 s), warning circles are
one short message each, and all art is drawn in the browser. Bandwidth in `tests/test_bandwidth.py` is unchanged.

## Combat stats HUD and shop recipes (v5)

The HUD now shows live **HP / max HP, ATK, DEF, movement speed, attacks per second, attack range,
spell power, lifesteal and shield**. Values update during combat, including damage, shields and boss-loot bonuses.

Shop components remain individually useful. Completed items are crafted during the shop by owning both
components and paying the combine fee. Green component names mean owned; red names mean missing.

| Completed item | Recipe | Combine | Final stats |
|---|---|---:|---|
| Titan Heart | Vital Gem + Heavy Plate | 275 g | +500 HP, +4 DEF |
| Duelist Reaver | Iron Blade + Frenzy Gloves | 225 g | +28 ATK, attack interval x0.82 |
| Archmage Core | Spell Tome + Vital Gem | 225 g | +250 HP, +45% spell power |
| Windstep Greaves | Swift Boots + Frenzy Gloves | 205 g | +70 speed, attack interval x0.88 |
| Vampiric Edge | Iron Blade + Bloodthirst Fang | 200 g | +18 ATK, +22% lifesteal |

Crafting consumes both components and replaces them with one completed item, so it works even with a full
6-slot inventory. Completed items sell for half their total value. Boss-drop items remain drop-only.

## More heroes and random enemies (v6)

Four heroes join the original three, bringing the roster to seven:

| Hero | Role | Q / W / E / R |
|---|---|---|
| Storm Ranger | Fast marksman | Piercing Arrow / Scatter Shot / Tumble / Heartseeker |
| Night Reaper | Melee assassin | Shadowstep / Soul Sweep / Dark Pact / Death Blossom |
| Wild Druid | Healing bruiser | Thorn Bolt / Bramble Burst / Renewal / Ancient Bark |
| Arc Artificer | AoE caster | Arc Bolt / Shock Mine / Overcharge / Plasma Bomb |

Every camp and respawn rolls enemies independently from weighted data in `game.json`: Goblin Raider (35%),
Ogre Brute (20%), Bone Archer (25%), and Chaos Wisp (20%). Brutes are slow and durable; archers fight from
range; wisps are fast glass cannons. Harder enemies give proportionally more gold and XP. The random sequence
is server-authoritative and deterministic for a given match seed.

All new hero and enemy art is drawn in the browser, so there are no image downloads. Enemy variants add a
small compact string to unit snapshots: the conservative full-room estimate is about 0.092 GB/hour uncompressed.
Database use and all free-tier guards are unchanged.

## Unique hero mechanics and matching effects (v7)

The four added heroes no longer reuse only projectile/nova/dash/buff behavior. They now use 16 mechanics:

- **Storm Ranger:** Piercing Arrow hits up to 3 units; Volley fires 5 arrows in a cone; Tumble grants
  3.5 s attack haste; Heartseeker deals double damage below 32% HP. Wind skills use green-white trails.
- **Night Reaper:** Shadowstep teleports beside the selected target; Soul Sweep heals from damage; Wraith
  Form becomes untargetable and faster for 3 s; Death Blossom pulses four times while Reaper can move.
  Effects use purple shadow bursts and rings.
- **Wild Druid:** Entangling Roots immobilizes; Bramble Field persists for 5 s, damages and slows; Regrowth
  heals over 6 s; Bear Form temporarily adds 320 HP, 55% damage and 5 armor. Effects use roots, vines and green healing.
- **Arc Artificer:** Chain Lightning jumps up to 4 targets; Shock Mine arms then explodes/stuns; Sentry Drone
  attacks nearby enemies for 9 s; Arc Laser damages every unit in a line. Effects use cyan lightning, mine fields and beams.

Projectiles now carry a 1-word effect style (`wind`, `shadow`, `nature`, `arc`) so browsers can render matching
colors. No image assets were added. The full-room conservative estimate remains under 0.10 GB/hour uncompressed.

## Theme-shaped skill effects (v8)

Projectiles are no longer colored circles with different labels. The compact projectile packet now carries a
visual id and direction, and the browser draws the object facing its actual travel direction:

- Ranger Piercing Arrow and each Volley projectile are arrows with a shaft, arrowhead and red fletching.
  Heartseeker is a larger glowing arrow with a wind trail.
- Druid Entangling Roots is a travelling seed wrapped in roots and leaves. Bramble Field visibly draws vines;
  Regrowth emits leaves; Bear Form displays a paw mark.
- Pyromancer Fireball is a flame with a tail; Meteor is a burning rock.
- Warden Chain Hook is a visible metal hook and chain segment.
- Reaper effects use purple scythe crescents, ghost images and shadow bursts.
- Artificer effects use visible chain lightning, a persistent mine, an orbiting sentry drone and a wide cyan laser.

No PNG or sprite downloads were added. Shapes are rendered using Canvas paths. Projectiles add their visual id
and angle to existing snapshots; the conservative full-room estimate is about 0.094 GB/hour uncompressed.

## Clearer basic attack range (v9)

Press **A** to toggle a dashed basic-attack circle around the player. The label shows the precise base range
from the server HUD stats. Hovering an enemy also reveals the circle automatically, draws a line to the target,
and shows **IN RANGE** in green or the remaining distance as **N TOO FAR** in red. Right-clicking an enemy keeps
the circle visible while chasing; right-clicking the ground, pressing S or leaving the canvas clears it.

The drawn circle includes the player's collision radius. The range check adds the target's collision radius, exactly
matching server melee/ranged attack reach. This is entirely client-side and adds zero network or database usage.

## Visible ranged basic attacks (v10)

Ranged basic attacks are now real server projectiles instead of delayed invisible damage. The projectile starts at
the attacker, travels to the target at 760 world units/second, can be visually dodged only by movement if collision
no longer occurs, and applies the ordinary basic-attack damage on contact:

- Storm Ranger fires a visible arrow with shaft, arrowhead, fletching and green trail.
- Pyromancer throws a small fire bolt with flame tail.
- Wild Druid launches a thorn branch with leaves.
- Arc Artificer fires a cyan zigzag arc bolt.
- Bone Archers fire pale bone arrows; Chaos Wisps fire arc bolts.
- Ronin, Warden, Night Reaper, Goblins and Brutes remain instant melee strikes.

The existing projectile stream is reused, so no new message type or database work is added.
