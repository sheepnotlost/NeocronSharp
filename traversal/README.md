# Traversal

The Traversal engine (`traversal.exe`, this folder) walks the character to a zone on its
own, crossing zone lines, riding lifts and the subway, and opening doors. The suite's
**Traversal** tab drives it: pick a zone and press **Go**. Paths below are relative to the
repository root.

## Build

The Traversal tab builds the engine itself the first time, if
`traversal/bin/Release/net9.0/traversal.exe` is missing. To build it by hand (needs the
.NET 9 SDK), in `traversal/`:

    dotnet build -c Release -nologo -v q

It uses `NeocronSharp/src/NeocronSharp.Core` and links the read-only memory reader
(`PlayerReader.cs`, `Native.cs`, `EntityReader.cs`) from `NeocronSharp/src/NeocronSharp`.
The in-game route panel needs the NeocronHook overlay, which is not in this repository;
without it the engine runs the same and simply draws nothing in game.

**Status (29 Oct 2026):** it works across the Plaza and into Pepper Park 1 and 2.
Pepper Park 3, Plaza 4, Via Rosso and Industrial have not been reached live yet.
Live runs are paused at your request; the character was left in NeoFrag 1.

## Use

1. Start the suite with **Launch.cmd** in the repository root.
2. In Neocron, stand in a city street with no game window open (no terminal, container or
   chat line), and press **Tab** so the mouse pointer is hidden.
3. Open the **Traversal** tab. Pick a **Zone**, and optionally a **Place** in it; the default
   "Arrive" stops as soon as you are in the zone. **Run** holds Shift.
4. Optionally press **Preview** first. It never moves the character. It shows the chain of sectors, each leg's length, how each zone line was found (learned crossing, map arrow or corridor tip) and a time estimate, then opens a picture of the first leg.
5. Press **Go**. The game comes to the front and the walk starts after 5 s. Hands off.
   **F8**, **Stop**, or clicking away from the game stops it and releases the keys.

## Live results

| Crossing | Result |
|---|---|
| Plaza 1 → Plaza 2 | works |
| Plaza 2 → Plaza 3 | works (3 times) |
| Plaza 3 → Plaza 1 | works |
| Plaza 3 → Pepper Park 1 | works (twice; once walked round a box it mapped as an obstacle) |
| Pepper Park 1 → Pepper Park 2 | works (after reading the map rotation live) |
| Pepper Park 2 → NeoFrag 1 | it walked into the arena; you stopped it with F8. Interiors are now never used as a way through |
| Plaza 2 → Plaza 1 directly | did not zone (at the old fixed rotation). Retried with live rotation: not yet |
| Pepper Park 2 → Pepper Park 3 | not reached: no arrow matched, so it fell back and took the NeoFrag detour (now fixed, untested) |
| Plaza 4, Via Rosso 1-3, Industrial 1-2 | not reached yet |

## Self-learning

Every live trip teaches it. All of this is kept in `traversal/logs/` and used on the next trip:

| File | What it learns | How it is used |
|---|---|---|
| `traversal-crossings.txt` | the exact spot and heading where a zone actually changed | first choice for that sector-to-sector crossing; forgotten if it stops working |
| `traversal-arrows.txt` | which sector-map arrow leads where, and which do nothing | known arrows tried first, dead or wrong ones skipped |
| `traversal-obstacles.txt` | props found blocking the way (boxes, barrels) | cut out of that sector's navmesh so routes go round |
| `traversal-blocked.txt` | exits with no way through at all | skipped by the planner (delete the file to retry them) |
| `traversal-links.jsonl` | every crossing attempt with time and outcome | history, and the source for seeding crossings |

The learned files above (except the links history), `door-graph.txt`, `wasteland-places.json`
and the `arrows-*.json` map caches are committed as seeds. Everything else in `logs/` (run
logs, `terrain/` navmesh caches) stays on this PC, as do `bin/`, `obj/` and `out/`.

The crossings were seeded from this morning's successful runs (7 so far):
- Plaza 1 to Plaza 2, and Plaza 1 to Plaza 3;
- Plaza 2 to Plaza 3;
- Plaza 3 to Plaza 1, and Plaza 3 to Pepper Park 1;
- Pepper Park 1 to Pepper Park 2;
- Pepper Park 2 to NeoFrag 1 (a destination only).

Trips along these go straight to where the zone triggered.

## What the morning video showed

`2026-10-29 08-49-43.mp4` (kept on this PC, not in the repository) was lined up with the walk logs:

- **1420 s:** at the Plaza 2 to Plaza 1 line, the character was already in the zone corridor, with "Entering new district: PLAZA SEC-1" showing. The push then stopped at its target point and circled, short of the line.
- **1442 s:** at the second Plaza 1 line it pressed into a wall for 16 s. The walkable corridor goes round it.
- **1502 s:** the Plaza 2 to Plaza 3 line that worked is a corridor ending at a "Synchronizing into city zone" wall.

**Fixed (not yet tried live):** the push now follows the walkable corridor toward the line, and past its end keeps going the way the corridor runs, instead of steering at a single point.

### Full scan of the video (banners and sector changes)

Every frame (2 per second) was read for the "Entering new district" banner and the Location panel, then lined up with the walk logs. Tools: `traversal/video/scan.py` and `pair.py`; results: `traversal/logs/video-paired.json` (local only).

- **Only 6 real zone changes happened on video:** Plaza 2 → 3, 3 → 1, 1 → 3, 3 → Pepper Park 1, Pepper Park 1 → 2, Pepper Park 2 → NeoFrag 1. All six are already learned crossings.
  - The 12 "zoned" legs at 13:50 and the one at 13:53:59 were false: the panel read Plaza 2 throughout.
- **The banner marks the zone-line corridor**, not the line. It shows from the corridor's mouth onward, while the Location panel still names the old sector.
- **Every learned crossing is within about 150-250 units of that link's exit record** (Pepper Park 1 → 2: 410). The exit record (arrival spot) sits right by the line.
- **Plaza 2 → Plaza 1 (never zoned, 3 tries):** the corridor mouth is at about -720, 2640 (all 3 tries agree). The corridor runs south-west to the exit record at -1072, 2112.
  - Tries 1-2 pressed south into the wall at that exit record for 16 s (`frames/t652.jpg`, `t976.jpg`). Try 3 stopped short at -970, 2750 and circled.
  - The map arrows used (-198, 2750 and -198, 3411) push west from the corridor's mouth, 500-650 units from either exit record.
  - On the navmesh the floor goes on west from the exit record (to about -1600, 2114, or via -1412, 2334). The line is probably that way. Not yet tried.
- **Pepper Park 2 → 3 (never zoned):** the corridor mouth is at about 1970, 1690. The walker went north-west and pressed into a wall at x = 1407, z 2050-2230 (`frames/t2357.jpg`).
  - The exit record is at 1568, 1920, and the navmesh floor runs north from it to 1568, 2472. The line is probably on that stretch. Not yet tried.

**Wired in (not yet tried live):** a map arrow is now skipped when its push passes more than 450 units from every exit record of that link.
- Instead, the walker walks to the exit record and pushes along the floor beyond it, to the corridor end nearest the sector's outer edge (within a 1,200-unit walk).
- If that push does not zone, it is remembered as dead and the arrow is used again.
- Learned crossings still come first.
- Offline results:
  - Plaza 2 → 1 (via the exit at -1072, 2112) now heads west to -1868, 2782.
  - Pepper Park 2 → 3 heads north along x 1568 to 1760, 2620.
  - Pepper Park 3 → 2 also switches to this rule.
- Plaza 2 → 1 via the north exit (-1072, 3232) keeps its arrow, because that arrow's push passes within 223 units of the exit record.

## How it works

- **Engine:** `traversal/` (C#, `traversal.exe`) bakes a Recast navmesh from each sector's own level file (about 5 s), reads the live position, heading, sector and map rotation from the client's memory (read-only), and steers with W, Shift and the mouse.
- **Which sectors connect:** the worlds' `WorldChange` records say this. Only exits with a real arrival point (NextLevelStartIndex above 0) and an exit back are used.
- **Where the zone line is:** the in-game sector map says this, through its exit arrows. A WorldChange's own position is where people arriving from the other side appear, not the line.
- **Map rotation:** the arrows are placed using the map rotation read live from the HUD compass. Each sector's map differs: Plaza 270°, Pepper Park 0°.
- **Learning the arrows:** which arrow leads where is not written anywhere, so it is learned.
  - Known-good arrows are tried first.
  - Arrows that led elsewhere, or did nothing, are skipped.
  - The results are stored in `traversal/logs/traversal-arrows.txt`.
- **Crossing:** at an arrow it pushes through and keeps pressing for up to 16 s. The game halts you at a zone line while the next zone loads.
- **Obstacles:** props such as boxes and barrels are not in the level files. When the walk stops short, the spot is saved to `traversal/logs/traversal-obstacles.txt` and the map is rebuilt around it.
- **What is never used as a way through:** interiors with no sector map (arenas, HQs, clubs). They can still be destinations. The subway is used by train (see "The subway").
- **Never sent:** right-click "use" (it opened a loot box and a CityCom terminal) and Esc. With nothing open, Esc starts the logout countdown; this logged the character out once.

## Known limits

- **Plaza 2 straight to Plaza 1** does not zone. The walk goes through Plaza 3 instead.
- **Doors:** exits that are doors (labs, HQs) cannot be opened.
- **Game windows:** any open window or chat line steals the keys. The test step then reports "went 0 units" and stops.
- **Calibration step:** a short step is taken before each trip. It fails next to a wall unless one of four directions is clear.

## Files

- `traversal/tour.py` runs the live acceptance tour; results go to `traversal/logs/tour-*.md`.
- `traversal/arrows.py` exports the sector maps' zone-line arrows.
- **Learned data,** in `traversal/logs/`:
  - `traversal-links.jsonl`: every crossing;
  - `traversal-arrows.txt`: which arrow leads where;
  - `traversal-obstacles.txt`: obstacle spots;
  - `traversal-blocked.txt`: exits to avoid (delete it to retry them).

- `traversal/rotations.py` works out each sector map's rotation offline and writes `traversal/rotations.json`.

## Offline checks

Double-click **`traversal/Run checks.cmd`**. It runs the engine tests, then the city-route simulation. No game is needed.

- **Engine tests** (`traversal/tests`, `dotnet run -c Release` there; needs the local Neocron install): 53 pass. They cover:
  - route following and aiming, and steering limits;
  - mouse-gain learning;
  - real exits only, street-only plans, and the solved rotations;
  - learned crossings and arrows;
  - obstacle routing;
  - unreachable arrows, corridor following, and a simulated walk.
- **City routes** (`traversal.exe simcity`): every city sector, every street neighbour, every way in. Each leg picks its zone line as a live trip would, then drives the simulated character there on the real navmesh with the morning's measured lag and mouse error. **36 of 36 legs pass** for Plaza 1-4, Via Rosso 1-3, Pepper Park 1-3 and Industrial 1-2.
- **Map rotations** (`traversal/rotations.py`), solved offline by matching map arrows to exit records:
  - **Matches the compass:** all 5 sectors read live (Plaza 1-3 at 270, Pepper Park 1-2 at 0).
  - **New:** Via Rosso 1-3 at 90, Plaza 4 and Pepper Park 3 at 270.
  - A live compass reading still wins when there is one.
- **Industrial and Outzone maps:** they are wireframe blueprints that mark no exits at all, so there is nothing to read (checked by eye). There the walker heads for the corridor tip that runs off the sector's edge beyond the exit record: the farthest walkable point outward, up to 1,500 units. It follows the corridor to that tip and pushes on. The first success is learned as a crossing. In the simulation every Industrial leg has 270-1,020 units of corridor to push along.
- **Zone list:** 56 zones reachable on foot from Plaza 1, through city streets only. This includes all city sectors and the interiors one step off a street.

**What the simulation cannot check:** whether the game actually zones at a given arrow. That is only learned live. The guesses most worth watching on the next live run:
- which Pepper Park 2 arrow leads to Pepper Park 3;
- the Industrial and Outzone outward pushes;
- Plaza 3 to Plaza 2 and Plaza 4 to Plaza 1, where the floor ends right at the arrow.

## Through doors and interiors (29 Oct)

- **Door graph:** `Travel.Links` lists every way out of a sector. Besides exits with an arrival point, it adds game-routed doors (sewers, cellars, clubs), found from the far side: another world's exit arrives at this door's `Index`. The scan of every world takes about 20 s and is cached in `traversal/logs/door-graph.txt` until the game's world files change.
- **Routes:** `Reach`/`SectorPath` use streets only when that works. Only when it must does a route pass through interiors (up to 20 doors). The subway: see "The subway" below.
- **Door legs:** any leg into or out of an interior walks to the door itself, with no map arrow. If the door stops the walk, it right-clicks it open (the same rule as entrances).
- **Result:** the walker now reaches 107 sectors from Plaza 1, up from 56. Six more Nav-Ray entries (the Abandoned Cellars) are placed inside buildings. Not tried live.
- **Still unreachable (124 Nav-Ray entries):**
  - **Wasteland (Tech Haven, Military Base, Canyon, the wasteland dungeons):** wasteland cells ("E 07 - MOUNTAINS") join at their edges, not by doors, and baking one cell took over 5 minutes. They need a different kind of walker.
  - **Game-routed doors with no link in the files (about 75):** apartment complexes 1 and 2, Outzone side streets, sewers, bunkers and storage, and Jones mission places. `pak_appplaces` names them in ENTRANCE/EXIT pairs. But the street side's entity number is not a WorldChange `Index` (Pepper Park 1 has no door 19; it may be a door model), so they can't be placed reliably yet.
  - **Outzone Station:** reached only by subway train (now ridden: see "The subway").
- **Offline check:** `traversal.exe reachreport [--all]` lists the sectors linked from Plaza 1, which of them the walker reaches, and why not for the rest.

## Doors that are objects (29 Oct, offline)

- **How the game routes these doors:** the door is a placed object in the street's spawn file (`pak_<world>.dat`), not a WorldChange. Its `pak_worldmodels` row (Type 20 "Entrance" or 18 "Sewer entrance") has `Value` = a `pak_appplaces` EntryId, and that row's `ExitWorldId` is where it leads. The exit back is the next row (EntryId + 1). The street-side numbers in the EXIT rows (Pepper Park 1 "19") are arrival spots, not doors.
  - **Checked on known doors:** Plaza 1's sewer objects carry appplaces 52, 54 and 56, the same numbers as the WorldChange `Index` of the sewer doors placed before.
  - **Inside**, the way out is the object whose Value is the EXIT row; else the "Underground exit" (Type 29); else the place's one exit object. Outzone dungeons are copies of Dome of York maps, and the client's file still points that object at the DoY, so the pair is used instead. A place with no spawn file at all (the Jones places, Outzone Water Treatment) uses its start point. That spot is a guess, and only matters when you start inside.
- **In the engine:** `Travel.ObjectDoors` reads every spawn file (about 1 s) and `Links` adds those doors. A leg to one walks to the object and right-clicks it open, like other doors. Street-to-street pairs are never added.
- **Result:** the walker reaches 158 sectors from Plaza 1, up from 107. Placed Nav-Ray entries went from 107 to 170 (61 still greyed, down from 124):
  - 54 of the 75 game-routed doors: both apartment complexes (18), Outzone side streets, sewers, storage and cargo holds, the Jones places, Tiki Tornado, Electric Vibes (and through it Outzone Station), The Pit, the Abandoned Labs and Basements, and three Pepper Park sewers;
  - the 3 Jones Hacknet entries, placed at their login terminals.
- **Still greyed (each with its reason):**
  - **Water Cleaning Sec 7 and 9:** no door leads to them in any file.
  - **Water Cleaning Sec 8:** its only door is in a Dome of York sector.
  - **Wasteland doors:** the Military Base storage rooms, Canyon caves and Dangerous Canyon Cave now have their doors linked. They become walkable once the wasteland walker reaches those places.
- **Not tried live.**

## The wasteland (29 Oct, offline)

Tech Haven, the Military Base, Canyon, the wasteland dungeons and the 36 outposts are now "walk there" destinations. **Not tried live.**

### What the files say

- **Cells:** world id = 2000 + 20 × row + column (row A = 0). `E 07 - MOUNTAINS` is 2087. 125 cells are on disk, rows A-L, columns 01-16.
  - Row A is the north (+z); columns run east (+x).
  - Each cell is 32,768 units square, centred on 0.
  - The cell's own `terrain\pak_e_07.bsp` is only a sky box: no floor, no exits.
- **Heightfield:** `terrain\pak_e_07.tfl` (zlib like every `pak_` file) is a "VF00" container. Its "DT01" directory holds:
  - 256 JPEG texture tiles;
  - `qtree.dat` (render LOD);
  - `map.dat`: 512 × 512 u16 after a 4-byte header. Height = value / 4. Sample (i, j) is at x = -16384 + 64 i, z = -16384 + 64 j.
  - Checked against the 908 plants and stones placed in E 07: they sit within about 23 units of it.
- **Placed models:** `terrain\pak_e_07.dat` record 1000008 places a BSP model: position, a second vector that is *not* a translation (models fit the ground far better without it), yaw in degrees, then the path.
  - The `worlds\terrainchange\` models hold the cell's doors as WorldChanges: Tech Haven (E 07, F 07), Canyon (E 13), the Military Entrance (J 01), the Outzone gates (A 06-A 09), Darkmetal (E 03), the Crystal Caves, the Mining Facility, and the Dome of York sectors (K 11, K 16). 45 doors in all.
  - Each model is a sealed level whose outer box would wall in the whole model. Its box faces are dropped: A 07's city gate was an island before that.
  - Outpost GenReps also carry a WorldChange; they are teleporters, not doors, and are skipped.
- **Edges:** cells join edge to edge, with no door. The two heightfields do not meet exactly at the seam (often 100-300 units apart): the game must place you on the new cell's ground. Which edge leads where is from the grid above (the heightfield mosaic is continuous that way).
- **Outposts:** `definitions\pak_outposts.csv` EntryId is the cell's world id (2006 Simmons Factory = A 06). The walk target is the outpost's gate model.

### How it walks

- **Navmesh per cell** (`TerrainNav.cs`): the heightfield plus the placed models, at 16-unit voxels in 512-voxel tiles.
  - Slopes up to 55 degrees count as walkable. **This is a guess.** At 45 degrees, thin one-sample ridges cut every cell into pockets.
  - First bake about 5-7 s per cell, then cached in `traversal/logs/terrain/` (0.2 s to load).
- **Walking grid for the whole wasteland** (`TerrainMap.cs`): 128 × 128 squares of 256 units per cell, with the same 55-degree rule. Squares either side of a cell edge join.
  - Built from all 125 cells in about 1.3 s, then cached (0.2 s).
  - The first time in a cell, squares its navmesh cannot reach from where you stand are blocked, so plans only use ways the navmesh can walk.
- **Planning** (`TerrainTravel.cs`, used by `Travel.SectorPath`/`Reach`/`Go`):
  - City trips are planned exactly as before. Only when the street and interior searches fail does a third search run.
  - The third search is shortest-path over sectors. Each stretch of wasteland is one step, costed by its length; a street costs 1 and an interior 6. Faction offices and HQs are never a way through.
  - The stretch is then routed on the grid, which names the cells crossed.
- **Walking** (`Go`): in a cell, each leg replans from where you stand, then walks either to the next cell edge (96 units inside it, then presses 900 units on, as at a zone line) or to the door. The game changing sector ends the leg.
  - Doors whose hall is not on the navmesh (Tech Haven, Canyon) are walked to as close as the floor goes (262 and 369 units off). It then pushes on, right-clicking if stopped, as for city doors.
  - Props that stop the walk are mapped as obstacles and the cell is rebaked, as in the city.

### Offline results

`traversal.exe wasteplan <to> [from] [--at x,y,z]` plans a whole trip leg by leg and simulates every wasteland leg on its cell's navmesh. From Plaza 1:

| To | Route | Legs | Length |
|---|---|---|---|
| Tech Haven SEC-1 | Industrial, Outzone 3, 9 → A 07, B 07, C 07, D 07, E 07 → door | 14, all ok | 196,000 units (about 16-26 min) |
| Military Base SEC-1 | Outzone 9 → A 07 … I 02, J 02, J 01 → Military Entrance | 27, all ok | 436,000 units (about 36-58 min) |
| Canyon Facility | Outzone 3 → (Outzone 6 is a dead end on its navmesh, backed out) → Outzone 9 → A 07 … E 12, E 13 → door | 25, all ok | 324,000 units (about 27-43 min) |

- **Planning takes 7-9 s**, mostly the existing city searches. The first run bakes each cell on the way.
- **The Nav-Ray list:** `Reach` now includes the cells and everything behind wasteland doors, so Tech Haven, Military Base, Canyon and the dungeons are placed as "arrive" entries. Water Cleaning Sec 8 is now placed, through the Dome of York.
- **Outposts:** `traversal.exe wastelandplaces` lists the 36 outposts as JSON (cell id plus an "x,y,z" walk target). 34 are on the navmesh; Nemesis Lab and Soliko Lab are not.
- **Preview** handles wasteland trips (about 30 s the first time).
- **Diagnostics:**
  - `traversal.exe wasteland [--portals] [--cells]`;
  - `terraincell <id> [--all] [--bake]`;
  - `cellisland <cell> x,y,z [x0,z0,x1,z1,step]` (which part of a cell its navmesh reaches).
- **Engine tests:** 7 new wasteland tests in `traversal/tests/TerrainTests.cs`. All 40 tests pass; `simcity` still passes 36 of 36.

### Watch on the first live run

- **Cell edges:** that the game zones at the edge and the walker's push gets there. Also whether the seam's height jump stops you.
- **The 55-degree slope limit:** if it is too generous, walks stall on ridges; each stall becomes an obstacle and a 6 s rebake.
- **Tech Haven's and Canyon's doors:** the last 262-369 units are a push, not a route.
- **Legs are long:** 20,000-40,000 units, 1-2.5 min each. LiveSteer still gives up after 6 replans in one leg.
- **Outzone 6 and 8:** their navmeshes are in pieces from the arrival spots used offline. Canyon's shortest route goes through them; a live run may need to back out as the offline plan does.
- **Not handled:** creatures that attack, water, and props (908 per cell, not in the navmesh).

## Gravity lifts, doors and props (29 Oct, offline)

**Not tried live.** Walks and Follow now use lifts and open doors inside a sector, and route round props.

### Gravity lifts ("Polarized Gravity Fields")

- **In the files:** each beam is an `AntiGravParticle` entity in the sector's BSP. Origin is the beam's foot, Length its height, Dir 1 lifts you up and Dir -1 lowers you. They come in pairs about 100 units apart.
- **Where they are:** 37 sectors have them.
  - Plaza 1: two pairs. At -2136/-2232, -272 (to the y 130, 418 and 706 floors: Archer & Wesson upstairs and the showrooms), and at -672/-768, 1000 (to the y 578 floor).
  - Also Plaza 2 and 4, Via Rosso 1, Pepper Park 2, Industrial 2, and many interiors.
- **On the navmesh:** for each beam, the floor nearest it at each height it passes (within 128 units, with room to step on) is a stop. Up beams link each stop to every higher one, down beams to every lower one, as one-way off-mesh links. Plaza 1 has 18 links.
- **Riding** (`LiftRider` in `Lifts.cs`), a timed step:
  1. walk to the beam's middle, release W;
  2. face the landing and wait to rise or sink;
  3. at the landing's height, walk off;
  4. re-plan from there.
- **Failure messages** start "The gravity lift..." (did not move you, stopped short, could not step off, wrong height).

### Doors inside a sector

- **In the files:** spawn-file record 1000005 places doors: position, id, and text such as "DDOOR2,78,3,1", where 78 is the other half of a split door. Worldmodel doors (DOOR, LIFT DOOR, AIRLOCK, SHUTTERS) count too. Plaza 1 has 6 doors; city sectors have 3-19.
- **The rule** (yours): when a walk or Follow stalls for 1.2 s within 150 units of a door, facing it along the route:
  - it stops, right-clicks once, waits 1.5 s and goes on;
  - at most 2 tries per door, then it stops with "The door did not open (locked or in use)."
  - Esc is never sent.

### Props

- **In the files:** the spawn file's placed objects (record 1000003) carry a bounding box at byte 52 (already scaled) and a yaw at byte 16.
- **Cut out of every bake:** each prop's turned box, plus 12 units. City sectors have 109-347 props each.
- **Not cut:**
  - doors and entrances; holograms, lights and decals;
  - anything under 24 high, under 20 across, or over 400 across;
  - for trees, only the trunk (32 units).
- **Wasteland cells** cut their rocks, crates and tree trunks too. The cache version is bumped, so each cell rebakes once.

### Offline checks

- **New tests** (`traversal/tests/LiftDoorTests.cs`):
  - Plaza 1's lift links;
  - routes street ↔ upstairs use a lift, and the simulation rides it;
  - doors found at Plaza 1's door models;
  - Pepper Park 1's barrels are off the mesh;
  - the door rule.
- **Simulation:** `simcity` still passes 36 of 36.

### Live test steps

1. **Lift, walk:** in Plaza 1, walk to the showrooms or to Archer & Wesson upstairs from the street. Watch that it steps into the up beam, rises, and walks off at the right floor.
2. **Lift, Follow:** follow someone who takes a lift.
3. **Door:** follow someone through the glass door, or walk through it. Expect one right-click, then it goes on.
4. **Props:** walk Pepper Park 1 past the barrels and crates.

The step logs (`logs/steer-*.jsonl`, `follow-*.jsonl`) record `lift-*` and `use` events.

## The subway (29 Oct, offline)

**Not ridden live yet.** A trip may ride the subway, mainly to leave the city for the wasteland by Outzone Station. The first live try (Plaza 1 → Tech Haven, 29 Oct) walked to Pepper Park 1's entrance and could not get in; both problems are fixed offline below.

### What the files say

- **One world (1000) with four station halls.** Each hall is its own floor; between halls there is only track.
  - Plaza hall: doors to Plaza 1 and 2.
  - Pepper Park hall: Pepper Park 1 and 2.
  - Via Rosso hall: Via Rosso 3.
  - Outzone hall: Outzone 1 (two doors) and Outzone Station. Outzone Station's other door opens on wasteland cell A 08.
- **The track** is one line, Plaza - Via Rosso - Pepper Park - Outzone, with turning loops at both ends. Lengths: Plaza to Outzone 58,900 units; Pepper Park to Outzone 23,200.
- **Trains:** 11 `SubwayTrain` entities start 30 s apart (StartTime 0-300).
  - A train is vehicle 200 "Subway" (`pak_vehicles`): 4 passenger seats. That file has no speed for it.
  - A seat hides you (ShowPlayer 0) and switches to the outside camera.
  - Leaving puts you 220 units to the side (LeavePosition), on the platform.
- **The timetable** is in the subway's spawn file (`worlds/pak_subway.dat`, section 4, block "MTNB"): one motion path that all trains follow.
  - A loop of 133,000 units takes 329 s, so 11 trains 30 s apart fill it.
  - It has 8 timed stops (STOP, OPEN, CLOSE, START), two per hall, each 8-13 s.
  - Between stops a train averages 150-680 u/s, with peaks about 1,280 u/s. Walking is 280-340 u/s.
  - Trains run one way round the loop: Pepper Park, Via Rosso, Plaza (twice, round the turning loop), Via Rosso, Pepper Park, Outzone (twice).
  - So from a hall's boarding spot, the ride to Outzone takes 137 s from Plaza (stopping at Via Rosso and Pepper Park on the way), but only 51 s from Pepper Park.
- So you must board: walking between halls is not possible.

### Street entrances (from the level geometry)

- **The door's record is not the way in.** It is where people coming out of the subway appear: on the landing halfway down the station stairs.
- **Plaza 1** (record 64,-240,2112):
  - The street ramps 128 units down to the landing.
  - A second ramp goes 128 further down to a closed room (floor -382).
  - The far end of that room is at -447,1276, about 1,050 units of walk from the record.
- **Pepper Park 1** (record 1808,-816,1056): the same layout.
  - The live walker pushed west along the landing toward 1588,1157, which is street.
  - The room at the bottom (floor -958, x 1568-2072, z 176-528) is a closed space. The far end is at 2045,281, about 990 units from the record.
- **The others** follow the same pattern: Plaza 2, Pepper Park 2, Via Rosso 3 and Outzone 1 (both doors).
  - Plaza 2 and Outzone 1 go down two flights, about 260 units.
  - Only Outzone Station's door (864,-16,2960) has no floor below it.
- **No door objects** stand at any of them in the spawn files.
- **The subway world's arrival points** are at the top of each hall's own stairs (for example 146 above Pepper Park's platform), so these geometries cannot be matched coordinate for coordinate.

### How it plans

- **Plan costs are seconds** (`TerrainTravel.cs`, `Subway.cs`).
  - **Walking:** the straight line × 1.5 (live routes ran 1.25-2.45 × as far) at 200 u/s. That is the live walker's average along a route, turns and stairs included.
  - **Each zone line or door:** 20 s. That is 6-11 s to push through and load, plus 10 s for the chance of a second try.
  - **An interior on the way:** 200 s more, so trips keep to the streets.
  - **Wasteland:** as before, two half-cells plus the straight length, at 280 u/s (58.5 s a half-cell).
  - **The subway:**
    - The walk to the station door, plus 1,000 units of stairs.
    - The walk across the hall to the boarding spot.
    - A wait of 20 s: half the 30 s headway, plus boarding.
    - The ride by the timetable, plus 5 s to step off.
    - The walk across the far hall to the door.
- **Each sector is timed from where you appear in it.** That is the exit record whose Index is the door's arrival point. The start is timed from where you stand: the live position in Go and in `wasteplan --at`, or else the middle of the sector's exits.
- **City trips keep to the streets** unless the cost search finds a quicker way by train. A street path quicker than 100 s is never compared.
- **Plaza 1 → Tech Haven:**
  - From where the live trip started (-869,-256,790): Plaza 1's own entrance, train Plaza → Outzone, Outzone Station, A 08, B 08, C 08, C 07, D 07, E 07, Tech Haven. That is 10 legs, all ok in `wasteplan 500 1 --at -869,-256,790`.
  - `wasteplan 500 1`, starting on Plaza 1's subway door, gives the same.
  - The two ways are close. Through Plaza 3 and Pepper Park 1 is 2 more zone lines and about 13,000 more units of walk, but 86 s less on the train. By the plan's times, Plaza 1's own entrance is 7 s quicker from the live start and 12 s quicker from its door.
  - From Plaza 1's line into Plaza 3 (-1024,3120), walking on to Pepper Park 1 is 10 s quicker, so it does that.
- **Where to wait:** the middle of each hall's platform edge, facing the track. `traversal.exe subway` prints it, the ride times and the timetable. It also rewrites `traversal/subway.json`, which plans use and which is rebuilt from the navmesh when the game files change.
  - Each boarding spot is on one side of its hall, so it serves one direction. Pepper Park → Via Rosso rides round by Outzone (167 s).

### How it walks in (`Travel.LineFor`, `Subway.SubwayEntrance`)

- **A leg from a street into the subway** walks past the door's record and on down.
  - Of the floor reachable from the record by only going down (never back above it), it takes the lowest within 1,600 units.
  - On that floor, it walks to the far end of the route.
  - Then it presses on 300 units the same way, into the room's far wall.
- **No right-click** at a subway entrance, unless a door object from the spawn file stands within 400 units of the record or the stairs' end. None does today.
- **No floor below the record** (Outzone Station): it walks to the record and on past it, as before.
- `wasteplan` names these legs "subway stairs".

### How it rides (`SubwayRide.cs`)

1. Walk to the boarding spot and face the track.
2. Press "use" (right-click) every 3 s until the train takes you aboard: the position jumps, moves on its own, or stops reading. It gives up after 150 s.
3. Ride. When the train stands still for 1.5 s beside the platform wanted, press "use" to step off (4 tries at most). Other stops are ignored.
4. Done when standing on that platform's floor. Put off at another platform: it plans again from there (at most 4 rides a trip).
5. It gives up after 8 min aboard (a wrong-way train goes to the end of the line and back).
- Failures start with "Subway:", for example "No train took us aboard", "Could not read the position while on the train".
- F8 and focus loss stop it, as on a walk. Each ride logs to `logs/steer-*-ride.jsonl`.

### Watch on the first live ride

- **The way in:** where the game changes sector on the way down the stairs or in the room at the bottom. Once it zones, the crossing is learned and used next time.
- **Boarding:** whether "use" while facing the track boards a standing train. The facing direction comes from the navmesh.
- **Reading aboard:** whether the position reads while seated and moves with the train. If not, it cannot see the stop and fails after 8 min.
- **Stepping off:** whether "use" steps off, or the game puts you off by itself (both are handled).
- **Right-click on the platform:** if a window opens (a box, a terminal), press F8.

### Offline checks

- `traversal.exe subway`: the halls, boarding spots, track lengths, ride times and the timetable.
- `traversal.exe wasteplan 500 1 --at -869,-256,790`: the Plaza 1 → Tech Haven trip above.
- **Engine tests** (`traversal/tests/SubwayTests.cs`, 7 subway tests):
  - The ride's decisions on made-up readings.
  - The four halls, and the plans.
  - The timetable: 8 stops, a 329 s loop, Plaza → Outzone 137 s and Pepper Park → Outzone 51 s.
  - The entrances: in Plaza 1 and Pepper Park 1, the walk ends on the room's floor 128 below the landing. It is reached only going down, about 1,000 units from the record, with no right-click. In Pepper Park 1 it is not the corridor where the live push failed.
  - The choice: Plaza 1's own entrance from the live start and from its door, and Pepper Park 1 from the line into Plaza 3.
- **Results:** 53 of 53 tests pass, and `simcity` passes 36 of 36.
