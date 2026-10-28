# NeocronSharp mob/NPC tracker and navigation

Open `dist/NeocronSharp.exe` on this computer. The application uses the installed
.NET 9 desktop runtime. Keep `dist` inside this project directory.

## Live NPC/player tracker

Double-click **Open NPC Tracker.cmd** in `Documents\Neocron AoSharp`.
The default application window is now the tracker. Log into the supported client;
the tracker connects automatically and refreshes every 500 ms while you play.

- Lists real loaded NPC and nearby player names in bold, nearest first, with 3D distance, direction relative
  to your character's heading, and signed height difference.
- Shows **current/maximum client HP** and **named weapon** directly in the list,
  alongside rank, health percentage, distance, faction and direction. Select an
  NPC for alive/dead, armor profile, template/base HP and rank, AI/dialog scripts,
  damage modifier/frequency and base weapon TL/range/magazine/shots per burst.
  Scroll the detail panel to see every field; resize columns or scroll horizontally
  for list columns beyond the pane.
- HP is bounded like the game's HUD; hovering its cell shows the raw client
  accumulator, which can exceed maximum. Client readings may remain unchanged
  until the game receives updates. Rank is the NPC skill/combat rank shown by
  the target display, capped at 255, rather than a separate player XP level.
- Faction/weapon names, AI/dialog scripts and weapon base stats come from the
  running installation's local definition files. They supplement native data;
  they do not overwrite current HP/rank. No server health, effective weapon range
  or attack-rate units are inferred from those definitions. Unknown values show
  an em dash; unmapped network characters keep null NPC stats.
- Click any list header to sort ascending; click it again for descending. Numeric
  HP, health percentage, rank and distance sort by actual values. Player rank pairs
  use the first rank, then the second. HP sorts current then maximum; unavailable
  values stay last in either direction. Direction sorts signed bearing from left
  through ahead to right. The arrow marks the active sort; live refreshes retain
  the chosen order and tracked instance. The opening order remains nearest first.
- Type into the search box to filter names. Radius uses world units; zero lists
  all loaded NPCs. A loaded actor can be behind a wall or on another floor.
- Select a row or map marker to track that particular actor's live distance and
  coordinates. Names and numeric hash keys alone are not treated as unique IDs.
- The radar has been replaced by the **native sector map**, chosen automatically
  from your current sector. It uses the game's original map image, reference
  points, scale and orientation. Your position is a blue heading triangle;
  brown markers are NPCs, the outlined marker is tracked, and a cross is dead.
- Use the wheel or **+/−** to zoom, drag to pan, **Fit** to reset, **You** to
  center your character, and **Tracked** to center the selection. **Names** adds
  labels. Hollow markers are more than 48 height units away; **Height ±48**
  filters those out. Map markers also respect the name, radius and character
  filters. The sector art is a ground plan, not a verified floor/line-of-sight map.
- Resize the divider between the list and map. Scroll the details below the
  list for every NPC attribute. Home resets the focused map; keyboard +/− zooms.
- The local catalog resolves 161 sector map definitions. Plaza SEC-1 is live
  verified; the other sectors have not all been visited. Sectors without an
  available image or orientation show an explicit unavailable message, with no
  reused map or estimated markers. Out-of-image entities remain in the list.
- Skin **1. Basic · Matte Cream** retains the basic layout with softened cream
  surfaces. The header selector offers ten additional Winamp-inspired styles and
  remembers the selection. All windows share the palette. Marker colors do not imply threat.
- **Loot library** browses 2,644 NPC templates, including 829 with assigned local
  loot tables. Search NPC/item/rule names, inspect variants and export. Selecting
  an NPC first opens its template. Candidates are not actual corpse inventory;
  raw signed chance fields are not verified drop percentages. Special-generation
  base weapon references can produce parts and do not prove finished-weapon drops.
- **Environment…** loads real BSP geometry, authored 3D path points and world
  exits, overlays points/exits for the current map, exports OBJ plus JSON and
  plans explicit sector links. Full scan resolves 787/791 world definitions
  (391 unique BSP source paths). This is navigation input: a collision-aware
  local navmesh and seamless macro traversal remain unimplemented.
- Sector titles no longer toggle during refresh. The table updates changed
  cells with double buffering instead of clearing and recreating every row.
- **Players** is enabled by default. Verified nearby players appear automatically
  and disappear when their records unload; unseen zone occupants are not enumerated.
  Double-click a player or use **Inspect player** for live published weapon slots,
  armor/body appearance models, attachments, HUD rank, faction, Soul Light and clan IDs.
  Blue diamonds distinguish players on the map. The inspector clears gear on unload
  or sector change. Appearance data is not a full inventory: player HP, exact armor
  item stats/condition, implants and quickbelt/backpack contents remain unavailable.
  **Unnamed actors** retains optional unclassified network records.
  See [PLAYER-TRACKING.md](PLAYER-TRACKING.md) for source evidence and limits.
- **Pause** freezes the display explicitly. **Stay on top** keeps the window
  visible above other windows. **Export** saves a timestamped JSON snapshot.
- Unavailable or changing telemetry clears the current list and retries. Lost
  selections require selecting a live row again. Change counts describe loaded
  registry appearances/disappearances, not confirmed births/deaths.

This iteration ports AOSharp's shared entity enumeration, name lookup/filtering,
per-instance selection and snapshot comparison patterns to Neocron. It is
read-only: tracking does not move, target or attack. It does not yet expose
verified hostility or line of sight, or provide follow or combat automation.
The current NPC mapping covers `SCRIPTEDPLAYER`, including observed COPBOTs,
shop/service NPCs and Small Spider. Other native NPC classes still need mapping.

Live validation on October 27, 2026: 860 actor-registry entries, 60 named NPCs
(25 COPBOTs) and 10 unclassified characters. The user stood beside a COPBOT;
the native reader independently found the closest COPBOT at roughly 71 units
at discovery, then 104.4 units after the player's position changed. The live
window passed filtering, row selection, empty-filter and preserved-selection
checks. Evidence is in `logs/entities-live-20261027.json`,
`logs/tracker-ui-check.json`, and `logs/tracker-ui.png`.

Expanded-data validation: 69 NPCs in the player's later area, including a COPBOT
with 15,168/15,168 client HP, rank 120, City Administration, and weapon 1651
(`NPC CopBot Plasma Rifle TL 128`). Small Spider was independently read as rank 1,
Wildlife, base/current maximum HP 15. Raw over-max HP and template overrides
were also observed. Evidence: `logs/entities-expanded-live.json`. These checks
did not involve attacking NPCs or deliberately testing damage/death transitions.

The implementation and exact native layout evidence are in `TRACKER-MIGRATION.md`.
New research, source links, loot coverage, skin references and the AOSharp-to-
Neocron environment mapping plan are in [EXPANSION-RESEARCH.md](EXPANSION-RESEARCH.md).
The tracker and navigation currently share the fingerprinted read-only backend.

## Continuous coordinate recording

Open **Open Coordinate Recorder.cmd** in Documents\Neocron AoSharp, or choose
**Recorder…** in the tracker. The recorder can run on its own with `--recorder`.

1. Log your character into the game and wait for live XYZ/sector readings.
2. Enter a recording name and keep the default 100 ms interval (up to 10 samples/s).
3. Click **Start recording**, focus Neocron, and walk normally. No manual point
   marking or stopping at intersections is needed. Stationary samples are retained.
4. Walk corridors, intersections, doorways, stairs, ramps and every floor; include
   alternate paths and revisit junctions. The optional height filter changes only
   the map preview, never the recorded 3D data.
5. Choose **Stop & save** when finished. CSV is appended/flushed while recording;
   JSON is finalized when stopping or closing the recorder. **Open folder** shows
   the files; **Export copy…** copies a completed CSV or JSON elsewhere.

Recordings live in `NeocronSharp/recordings/` with unique timestamped filenames.
Each sample includes UTC time, monotonic elapsed milliseconds, sector ID/name,
XYZ, forward direction, heading and segment/break metadata. X/Z are ground and
Y is height. Heading 0 degrees is negative Z; 90 degrees is positive X.

The recorder uses a separate lightweight read-only sampler and does not depend
on NPC enumeration. It continues while Neocron is focused and sends no game
input. Sampling is best effort; actual timestamps are saved. Gaps, zoning,
client-session changes and large position discontinuities split the trail and
are excluded from travelled distance. Unavailable data never produces fake or
stale coordinate samples. The current map shows only points in that sector;
full recordings retain all sectors and heights. Failed reads clear the live
position and resume as a new segment after telemetry recovers.

A recording shows where the character travelled, not walls or verified
walkability in unvisited space. Route playback/following remain separate work.
The session stops automatically at 100,000 samples (about 2 hours 47 minutes at
10/s); start another recording for longer surveys. If the process is forcibly
terminated, the CSV remains the recovery file; JSON needs a clean Stop/close.

Build validation covers 92 tests. Passive live UI verification uses:
`dotnet run --project src/NeocronSharp -c Release -- --recorder --smoke-ui --ui-evidence`.
It captures without moving the character and checks CSV/JSON sample counts.

## Walk back to a saved spot

1. Log into the supported Neocron Evolution client. Stand at the destination.
2. Open NeocronSharp, choose **Navigation…**, then **Save this spot**.
3. Walk somewhere else nearby, with an unobstructed path back on the same floor.
4. Choose **Walk to saved spot**, then focus Neocron within five seconds.
5. Close chat/RPOS and leave the mouse and movement keys alone while it runs.

The navigator briefly steps forward to check its heading, measures the response
to a small horizontal mouse movement, turns toward the saved location, and
approaches it. It releases movement and checks that the character is stationary
before reporting arrival. Small overshoots are corrected backwards.

**F8 stops immediately. Alt+Tab stops the run without automatic resumption.**
Closing the tool cancels the run and releases its held movement input.

Use the default W/S movement bindings. Stay in the same area and game session,
with a clear, flat path. The old 400-unit prototype restriction has been removed;
the outer sanity bound is now 10,000 units. Destination checks run before the
countdown so failures remain visible in the tool. Save the destination again after zoning or reconnecting.
Saved spots are intentionally kept in memory, not reused across game sessions.

## Other controls

- **Read position** checks the read-only connection without moving.
- **Test out/back twice** records a short segment directly ahead, then runs
  A -> B -> A -> B -> A. Endpoint arrival is measured after releasing movement.
- Keyboard access: Alt+S saves, Alt+W starts destination travel, Alt+P reads
  position, Alt+O starts the four-leg test, and Alt+T stops.

## Current limits and validation

This is direct travel to one saved spot. It does not yet follow the green
NavRay route, avoid obstacles, find doors, handle stairs, or navigate zones.
Blocked movement, invalid telemetry, focus loss, excessive travel, incorrect
heading calibration, and failed turning stop the run.

- Release build: zero warnings or errors.
- Automated harness: 92 passing tests: the original 28 navigation checks plus
  64 actor/player/data/map/loot/skin/environment/recording checks. Expanded coverage includes map projection, archive
  bounds, zoom/pan, unsupported maps, sector changes, HP bounds, native NPC stats,
  unknown fields, rank limits, compressed CSV, bad/missing definitions and
  preserving live values when joining reference data. Navigation coverage includes different starting headings,
  inverted mouse response, inertia, endpoint drift from the first live run,
  corrupt orientation, blocked calibration, different floor heights, the user's
  418/445/709-unit destinations, the observed second-outbound overshoot, and
  distributing mouse corrections across game frames.
- Live: player position reading and forward/backward input have been observed.
  Native orientation is being read successfully. The initial four-leg run
  stopped after its first return due to endpoint drift. A later user run reached
  the third endpoint but stopped on a small on-line overshoot. Both cases now have
  dedicated corrections and regression coverage. Earlier destination runs passed
  forward calibration but did not observe a mouse turn; frame-spread mouse pulses
  and detailed steering-probe logs have replaced the single-event approach.
- Live destination navigation confirmed by the user's run on October 27, 2026:
  started 532.03 units from the saved destination, verified forward heading and
  mouse response, made 13 steering decisions, and finished 0.887 units from the
  destination after 10.60 seconds. Arrival was confirmed after key release and
  stationary sampling. Evidence: `logs/navigation-20261027-222126-248.jsonl`.
- The corrected four-leg test still requires a complete live run. Destination
  navigation success does not imply obstacle avoidance or NavRay integration.

## Build and test

```powershell
dotnet build NeocronSharp.sln -c Release
dotnet run --project tests/NeocronSharp.Tests -c Release
dotnet run --project src/NeocronSharp -c Release -- --diagnose
dotnet run --project src/NeocronSharp -c Release -- --entities
dotnet run --project src/NeocronSharp -c Release -- --smoke-ui
dotnet run --project src/NeocronSharp -c Release -- --smoke-ui --ui-evidence
dotnet run --project src/NeocronSharp -c Release -- --smoke-ui --ui-evidence --skin-evidence --expansion-evidence
dotnet run --project src/NeocronSharp -c Release -- --smoke-ui --ui-evidence --player-evidence
dotnet run --project src/NeocronSharp -c Release -- --loot-index
dotnet run --project src/NeocronSharp -c Release -- --environment-index
dotnet run --project src/NeocronSharp -c Release -- --navigation
dotnet publish src/NeocronSharp -c Release --no-self-contained -o dist
```

The diagnose command reads position/orientation only; entities prints the full
loaded NPC/character snapshot as JSON. The smoke command opens and closes the
tracker without sending game input. Adding ui-evidence requires live COPBOT
records, checks the filter/selection flow, and renders the tool's own window to
`logs/tracker-ui.png`. Logs from actual movement runs are
stored in `logs/` as JSON lines with positions, actions and completion/failure.

## Native backend evidence

Supported local reference: `../Neocron Evolution 2.5/neocronclient.exe`,
Evolution 2.5.902, x64, SHA-256
`8fa50ebe20b5e15738cfac398bef19fef3c048f0f3e89a7a9bad7172b73d5d8c`.
Exactly one matching game process must be open. A launcher-started copy is
accepted only if it has the identical fingerprint. Updates require revalidation.

All addresses below are relative to the executable's loaded base:

| Item | Evidence |
| --- | --- |
| Player controller root | Global pointer RVA `0x6d3db0`; RTTI/vtable identifies `WORLDCTRLPLAYER` |
| World client root | Global pointer RVA `0xd68330`; RTTI/vtable identifies `WORLDCLIENT` |
| Player physics | World client + `0xa8` equals player controller + `0x498` |
| Position getter | Physics vtable + `0x98` resolves to RVA `0x248270`: `lea rax,[rcx+0xd8]; ret` |
| Transform getter | Physics vtable + `0x88` resolves to RVA `0x335a30`: `lea rax,[rcx+0xf0]; ret` |

The backend verifies executable hashes, getter instructions, object vtables,
pointer relationships, finite coordinates, and orthonormal rotation rows.
Its proposed forward-axis convention must independently match a small measured
forward step in each destination run. Mouse response is measured afresh too.
It opens game memory with query/read access only; it does not write memory or
inject AOSharp into Neocron. Movement uses ordinary keyboard and mouse input.

`tools/inspect_client.py` contains the local PE/disassembly inspector;
`tools/probe_position.py` contains the read-only discovery probe. Their optional
development dependency is Capstone 5.0.7 in `tools/.deps`; the built application
does not depend on Python or Capstone.

