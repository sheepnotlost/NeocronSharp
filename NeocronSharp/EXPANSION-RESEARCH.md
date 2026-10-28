# Local NPC data, loot, skins and environment research

Validated against the bundled Evolution 2.5.902 client on October 27, 2026.
The application reads game memory and assets; this update sends no game input.

## Numeric HP and equipment

AOSharp `AOSharp.Core/Dynel/SimpleChar.cs` exposes `Health`, `MaxHealth`, their
calculated percentage, and a weapon-holder equipment dictionary. That is a useful
API pattern, but the offsets and engine methods are Anarchy Online-specific.
Neocron uses its own validated `SCRIPTEDPLAYER` layout, documented in
`TRACKER-MIGRATION.md`: current/max HP at 0x79c/0x7a0 and weapon ID at 0x948.

The main list now displays numeric client HP and the named native weapon ID.
The selected detail panel includes live rank, faction, alive/dead, armor profile,
damage modifier/frequency, coordinates, height, AI/dialog scripts, template base
HP/rank and base weapon TL/range/magazine/shots-per-burst. Local definitions
remain separate from live readings and never replace them.

Live example: COPBOT, rank 120, City Administration; maximum HP 15,168;
weapon 1651 joins to `NPC CopBot Plasma Rifle TL 128`. Its weapon definition
has range 500, ClipSize 20 and ShotCount 4. These are base configuration values,
not a measurement of effective range, remaining ammo or combat damage.
The observed raw HP accumulator was 18,413; the game-style display clamps that
to 15,168 / 15,168. The raw reading remains in the tooltip and JSON export.
This is not independently verified server HP, and damage/death transitions were
not deliberately tested by attacking an NPC.

Additional data needs further mapping before it can be promised: current target,
attack state, hostility, line of sight, actual inventory and remaining ammunition.
AOSharp's implementations of those properties cannot be reused as Neocron offsets.

The sector-title blink came from assigning `Sector map` then the real sector name
on each refresh. The title now changes only when its value changes. The NPC grid
uses double buffering, updates changed cells and preserves selection/scroll
without clearing all rows every 500 ms. A live check verifies repeated refreshes
cause zero sector-title changes.

## Local loot coverage

The library loads enabled rows from the exact installation's `pak_npcs.csv`,
`pak_characters.csv`, `pak_items.csv`, `pak_itemgroups.csv`,
`pak_itemcontainers.csv` and `pak_itemcontainerchildren.csv`.

* 2,644 enabled NPC templates; 829 with assigned, resolvable loot containers.
* 362 container definitions and 4,459 enabled named item definitions.
* All 829 assigned NPC templates resolve at least one candidate.
* Offline search supports NPC names, template IDs, item names and rule/group names.
* Selecting a tracked NPC before opening Loot library jumps to its template.
* Export includes template, source note, raw rules and all candidate references.

NPC `ItemContainerId` selects repeated child rows. Negative child IDs reference
item LootGroupId; positive IDs directly reference items. Container zero is not
interpreted as the dummy table-zero loot assignment for shop NPCs or COPBOTs.
Small Spider 440 resolves insect eyes, fluids, limbs, glands, chemicals and other
configured group candidates. Warbot 195 resolves container 1032 and its tech-part
group plus other rules. Variants keep separate assignments.

Chance and quality retain their original signed fields. They are not percentages.
Negative-quality rules, including the tech-part group, can reference a base weapon
while generating another output. A rare weapon name in that rule is not evidence
that a completed rare weapon drops. The browser explicitly labels this distinction.
The library describes configuration candidates, not observed corpse inventory.

The [official community Q&A](https://neocron-game.com/announcements/neocron-community-q-a-answers)
describes the old loot logic as complex and also discusses the map/world pipeline.
The [Tech Haven Warbot entry](https://wiki.techhaven.org/Warbot) is useful community
corroboration for tech-part loot; it does not establish the installation's drop odds.

## Eleven selectable styles

Skin 1 retains the basic layout with soft matte cream surfaces. Ten original
Winamp-inspired adaptations add Classic 2.x, MMD3 Titanium, Bento Amber, Sputnik
Steel, Leather Box, XP Metallic, Pioneer OEL, Matrix Xtream, iBDE HiFi and WinAqua.
The selector persists to `settings/appearance.json`. Colors apply to navigation,
loot and environment windows too. Non-basic skins add period metal/LCD/gloss or
leather details. The LCD shows real sector/NPC status. No audio visualization is
invented. These are original application skins, not imported Winamp packages.

References: [Winamp's Classic/Modern/Bento support](https://support.winamp.com/winamp-desktop-player-for-windows),
the [Winamp community's historical download charts](https://forums.winamp.com/forum/skinning-and-design/classic-skins/311827-top-20-most-downloaded-classic-skins),
and [MMD3's archived listing](https://winampheritage.com/skin/mmd3/122902).
These establish popular period references, not an exact universal top-ten ranking.
All eleven palettes are tested for readable body, secondary, data-accent and LCD
text contrast. `logs/skins/` contains rendered examples of every style.

## How AOSharp maps its environment

Source checkout: `../aosharp-master/aosharp-master`.

| Source | Actual responsibility |
| --- | --- |
| `AOSharp.Recast/NavmeshGenerator.cs` | Extract terrain/dungeon chunks and room/zone surface geometry, transform vertices to world space, triangulate, build Recast tiles and off-mesh connections. |
| `NavmeshMovementController/Pathfinder.cs` | Project endpoints onto a navmesh, query polygon paths and straighten a route corridor. |
| `AOSharp.Navigator/AONavigator.cs` | Use playfield links, enqueue zoning/teleport actions and wait for the expected destination. |
| `AOSharp.Navigator/PlayfieldLinks.json` | Explicit cross-playfield connection records. |
| `AOSharp.Core/Playfield/Playfield.cs` | Expose terrain, rooms, zones, doors and other engine-backed environment data. |

AOSharp does not derive walkability from a sector-map bitmap or NPC positions.
Its agent dimensions and step/slope thresholds use AO units; they must be measured
again for Neocron rather than copied unchanged.

## Neocron mapping implemented in this update

The new Environment window indexes worldinfo and worlds.ini, decompresses local
GBSP assets (or reads worlds.pak), parses actual world geometry and retains
GroundPathPoint, AirPathPoint, WorldChange, ModelController and start metadata
with 3D positions. The [Genesis3D GBSP header](https://raw.githubusercontent.com/RealityFactory/Genesis3D/master/World/Gbspfile.h)
is a primary format reference. Its version is 15; the installed Neocron files
use version 17 and their chunk layouts were checked against actual local assets.

Full-install scan: 791 world definitions, 787 readable, covering 391 unique BSP
source paths. Variants share geometry, so 787 is not a claim of 787 unique maps.
The four missing placeholder assets are emptyzone.bsp (worlds 1590,1591,1593)
and emptystorage.bsp (1592). They are reported unavailable, never replaced by
invented geometry. The scan retains 158 authored ground points and 543 world
transition records across world definitions; shared/variant assets can duplicate
those records.

Plaza SEC-1 contains 27,549 vertices, 20,396 faces, 15 models, 41 authored ground
points, 16 air points and 17 world-change records. The app can overlay authored
ground points/exits on the current sector map and export static model-zero
geometry as OBJ plus entity/transition JSON. Moving models are counted and their
controller entities retained; their live states and collision are not resolved.

The zone-link planner uses only explicit WorldChange.NextLevel edges. Plaza 1 to
Plaza 2 resolves directly. It does not invent reverse links or connect nearby
points through walls. DAT spawn overrides do not change the BSP resource mapping.

**Seamless traversal is not implemented.** This provides actual geometry and
sector topology as inputs. Remaining work is a collision-aware local navmesh,
measured player clearance/step/slope limits, handling water and dynamic doors,
endpoint projection, transition actions and live route validation. The existing
flat, unobstructed saved-spot movement remains the available movement feature.

## Validation

Release build: zero warnings/errors. The harness has 70 passing tests covering
navigation, native telemetry, loot joins, special generation semantics, skins,
archive bounds, BSP extraction, world-resource precedence and directional links.
Live UI checks cover numeric HP/weapon visibility, filters, selection preservation,
native map projection, zoom and steady sector titles. Loot and environment forms
were rendered and checked using local files without sending game input.
Evidence: `logs/tracker-ui-check.json`, `logs/tracker-ui.png`, `logs/loot-ui.png`,
`logs/environment-ui.png`, `logs/loot-index.json`, `logs/environment-index.json`.
