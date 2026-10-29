# What to build after the player inspector

The strongest next investment is a route recorder/editor connected to a macro runner that reacts to verified game state. That directly serves the requested destination travel and supplies a foundation for following, gathering, missions and encounter routines. Nearby watchlists and an observation atlas are the quickest useful additions alongside it.

This is a source-based proposal, not a claim these features have been added. The Neocron tracker remains unchanged by this research.

## Review scope and evidence

Indexed all five supplied source trees: 75 C# projects, 1,267 C# files and 122,634 lines, excluding dependency packages, build output and Git metadata. The three main archives account for 73 projects and 118,614 lines; the two Mali plugins add 4,020 lines. Also inventoried XML/JSON assets. The full path/type inventory is in source-inventory.md and the machine-readable index is source-index.json.

This broad indexing/search pass was followed by focused inspection of the implementations supporting the recommendations: core entity/events, movement, inventory, combat, buffs, requirements, missions/dialogue and IPC; Roamba's editor/target selection/state machine; NewBots' runner, tree viewer, roster and dungeon solver; follow/assist/sync/loot/tradeskill utilities; and the damage-meter/dungeon-map plugins. Indexing is not a claim that every line received an individual manual review. No AO plugin was executed and no game input was sent.

## Ranked shortlist

| Priority | Feature | Useful result | Neocron implementation position |
| --- | --- | --- | --- |
| 1 | Route recording, editing and named destinations | Record a real walk, save destinations, edit/reverse/split routes and reuse patrol loops | Recording/editor can use existing position/sector data. Reliable replay needs a waypoint executor and testing. Arbitrary click-to-walk still needs a navigation mesh. |
| 2 | Macros that react to game state | Go somewhere, wait for a verified condition, branch, retry or stop; show the exact current step | Runner/UI can be built now. Each action must declare its mapped data and input requirements. |
| 3 | Watchlists and a live event timeline | Alert on a named NPC/player appearing in client range, a radius crossing, an observed death or published gear change | Existing entity snapshots support most of this now; unload is not proof of leaving a zone or dying. |
| 4 | Persistent NPC/service atlas | Remember observed locations, ranks, HP maxima, loot references, vendors and exits across sessions | Observation recording is ready to design around current data. Static spawn placement and merchant joins still need validation. |
| 5 | Construction/recycling/item workbench | Select an item, see recipe references, parts, possible loot sources and known locations | Local data already contains 448 enabled plans and 228 recycle recipes. Start offline; later connect own inventory. |
| 6 | Full local navigation and floor-aware maps | Choose a saved shop, entrance or objective and travel around obstacles through known zone links | Geometry extraction exists. Walkability, clearance, doors/stairs/water and transition handling remain substantial new work. |
| 7 | Your own inventory/equipment/bank manager | Search stored items, inspect exact equipped items, compare loadouts, track consumables and condition | High utility, but own inventory/containers/item instances need new native mapping. Nearby players' appearance data is insufficient. |
| 8 | Combat and hunting-session analytics | Damage/heal/hit breakdowns, kills, loot observations and run comparisons | Session boundaries/basic observations can start now. Accurate damage attribution requires a verified combat-event source. |
| 9 | Follow/escort with separation recovery | Follow a selected player at a chosen distance and stop/replan when they disappear or change floors | Positions are available; movement requires validated paths rather than aiming straight at a moving marker. |
| 10 | Buff/consumable/support assistant | Display real effect timers and resource thresholds, then support conditional actions | Requires local HP/STA/PSI, active effects, cooldowns, quickbelt bindings and action acknowledgement mapping. |
| 11 | Mission assistant and repeatable routines | Track active objectives, guide to NPCs/locations and wait for actual step completion | Definitions exist; live mission state, dialogue, interaction and completion events need new mapping. |
| 12 | Encounter/hunting profiles | Combine roaming, NPC priorities, navigation, fighting and actual corpse-loot handling | A later integration of the preceding capabilities, not an immediate port of AO profession or boss scripts. |
| 13 | Coordinated characters | Shared waypoints, ready checks, leader movement and explicit assistance roles | AO has IPC examples. Neocron currently requires exactly one matching client; per-process selection and data isolation come first. |

## 1. Route recording and destination travel

AO's Roamba editor explicitly supports adding/removing points, reversing and splitting a path, picking up/placing points, loops, locks, testing and saving/exporting paths. [Roamba path editor](<aosp-bots-master/aosp-bots-master/Automatons/Automaton.Roamba/UI/Views/PathEditorMainView.cs:34>) [Route persistence](<aosp-bots-master/aosp-bots-master/Automatons/Automaton.Roamba/Config/PathEditorConfig.cs:25>)

For Neocron: a Record walk button captures sector, XYZ, heading and time as the user walks. Save names such as a shop, genrep entrance or sewer access. Display the recorded corridor on the native map, allow editing, and show segment length, height changes and recent traversal results. Join paths at actual observed transitions, not merely nearby map pixels. Reversing a route is an edit operation; a successful outbound traversal does not establish that a ledge, door or one-way transition is traversable backwards.

The first movement increment should replay an explicitly recorded and tested single-sector corridor, stopping on lost focus, invalid telemetry, lack of progress or unexpected height changes. This extends the existing measured saved-spot controller instead of replacing it with timed W-key sequences.

AO's global navigator separately finds playfield-link routes and verifies the resulting zone after teleport completion. Neocron should use the same separation between local movement and sector transitions. [Global navigator](<aosharp-master/aosharp-master/AOSharp.Navigator/AONavigator.cs:108>)

## 2. A macro runner with visible execution state

NewBots provides MoveTo, Wait, WaitForZoneChange and composable behavior trees. The tree viewer colors Ready, Running, Succeeded and Failed nodes and displays the active node. Roamba supplies another reference through explicit finite states and triggers. [Reusable behavior steps](<aosharp.newbots-master/aosharp.newbots-master/BTBotBase/Behaviors/BaseBehaviors.cs:19>) [Live task-tree viewer](<aosharp.newbots-master/aosharp.newbots-master/BTBotBase/BTViewer/BTStatusInfo.cs:66>) [Roamba state-machine base](<aosp-bots-master/aosp-bots-master/Automatons/Automaton.Roamba/StateMachine/FSM.cs:29>)

Build named steps with preconditions, timeout, success evidence, retry limits and cancellation. A first routine could be: follow a saved corridor -> wait until the named service NPC is loaded and near -> pause for manual trade -> follow the return corridor. Later, a mapped trade action can replace the manual step. Show why the runner is waiting rather than silently doing nothing.

Useful conditions already supported by current data include sector equals X, within distance of a saved point, named NPC/player loaded, NPC HP below a threshold, and observed dead flag. Player HP, LOS, hostility, current target and own consumables cannot yet be valid conditions. Unknown/stale must be a separate state, never interpreted as false, healthy or safe.

The AO DungeonRunner composes readiness checks, navigation, combat, floor changes and objective completion. Reuse the composition pattern; its AO-specific interactions are new bindings in Neocron. [Dungeon task composition](<aosharp.newbots-master/aosharp.newbots-master/DungeonRunner/Behaviors/DungeonRunnerBehavior.cs:30>)

## 3. Watchlists, observations and history

AO's core queues spawn notifications and separates characters, players, NPCs, corpses and terminals. Roamba has explicit player-proximity and resource gates, plus priority and ignored-name lists. MonsterTracker writes per-playfield monster metadata and waypoint-oriented records. [World/entity notifications](<aosharp-master/aosharp-master/AOSharp.Core/Dynel/DynelManager.cs:12>) [Nearby-player gate](<aosp-bots-master/aosp-bots-master/Automatons/Automaton.Roamba/StateMachine/RoamStateMachine.cs:81>) [Target selection rules](<aosp-bots-master/aosp-bots-master/Automatons/Automaton.Roamba/MobTargeting.cs:147>) [Monster metadata tracking](<aosp-bots-master/aosp-bots-master/Utilities/MonsterTracker/MonsterTracker.cs:331>)

Neocron can use current snapshot comparisons to emit appeared-in-client, disappeared-from-client, entered-radius, left-radius, observed-alive-to-dead and published-equipment-changed events. Add user watchlists by name, NPC template, faction, clan code and rank, with an event timeline and optional sound. Use debounce/hysteresis to avoid repeated notifications at a radius boundary. Record when data became stale.

An NPC leaving the loaded registry is not a confirmed kill or server despawn. Confirmed observation history can later support approximate return/respawn windows, with sample counts and uncertainty. Several NPCs sharing a name/template must remain separate instances. Persistent player observations by name must be labelled last-seen observations; a cross-session stable character identity has not been mapped.

## 4. An atlas that grows as you visit areas

Persist sector, template/observed name, position, time, rank, maximum client HP, base armor-profile ID, possible loot and provenance. Cluster repeated NPC observations into locations while retaining patrol trails and vertical differences. Link known shops, transitions and recipe/loot searches. Show current-live, previously-observed and authored-reference locations differently.

The supplied Boss Logger is a manual Add/Remove catalog of the selected target's name and maximum HP, grouped by playfield. It is evidence for a persistent bestiary, not an implemented automatic spawn/respawn monitor. It also deduplicates by name, which should not be copied for Neocron variants. [Manual boss catalog](<aosp-bots-master/aosp-bots-master/Utilities/Boss Logger/BossLogger.cs:102>)

A floor-aware view is another worthwhile upgrade: Mali's map factory groups room meshes and doors by floor; DungeonSolver tracks visited rooms and lifts. Neocron has 3D BSP geometry but does not yet expose AO's room/floor graph. Height filtering is a useful interim step, not a full floor model. [Floor/door map construction](<malis-dungeon-map-2.0-master/malis-dungeon-map-2.0-master/DungeonMapFactory.cs:32>) [Dungeon exploration state](<aosharp.newbots-master/aosharp.newbots-master/DungeonSolver/DungeonSolver.cs:55>)

## 5. The item and crafting workbench

AO provides item/container queries, combine/split operations and stateful tradeskill-and-sell workflows. The portable idea is a materials/workflow model, not AO's recipe IDs or profession research selector. [Inventory and slot API](<aosharp-master/aosharp-master/AOSharp.Core/Inventory/Inventory.cs:97>) [Tradeskill workflow](<aosp-bots-master/aosp-bots-master/Utilities/Tradeskill and Sell/Tradeskill and Sell.cs:141>)

Fresh inspection of this Neocron install found:

| Local table | Enabled rows | Potential use |
| --- | ---: | --- |
| pak_itemplans.csv | 448 | Construction plan targets and raw build-time field |
| pak_itemplanitems.csv | 1,616 | Plan component/qualifier references |
| pak_recycle.csv | 228 | Recycle result and input-item lists |
| pak_traders.csv | 314 | Trader configurations, including placeholder/default definitions |
| pak_traderitems.csv | 1,875 | Trader direct/group stock rules and raw price values |
| pak_missionbases.csv | 1,519 | Mission/reward/script references |
| pak_missiontargets.csv | 3,415 | Objective references |
| pak_npcgroupspawns.csv | 563 | Group-spawn configurations |
| pak_npcgroupspawnchildren.csv | 1,608 | NPC/script/chance references |
| pak_implants.csv | 272 | Implant base definitions |
| pak_implantmodifiers.csv | 1,007 | Implant modifier references |
| pak_npcarmors.csv | 5,720 | Base NPC armor entries by profile and damage-type code |

These are row counts, not live availability or independently verified formulas. Child tables repeat parent IDs. Recipe qualifier meanings, price multipliers, build-time units, spawn triggers and NPC damage-type meanings need validation before presenting derived quantities, prices, schedules or effective protection.

An offline workbench can first show raw recipe inputs and output names, then link existing loot candidates and observed NPC/vendor locations. Later, own-inventory mapping enables missing-material counts, shopping lists, batch requirements and loadout comparisons. Do not infer exact live NPC inventory, trader stock, final crafting quality or server rules solely from these files.

## 6. Complete navigation as a dedicated project

The largest capability jump is a walkable navigation mesh with connected sectors. AOSharp.Recast extracts real geometry, and its pathfinder projects endpoints onto the mesh and queries/straightens polygon corridors. [Geometry-to-navmesh generation](<aosharp-master/aosharp-master/AOSharp.Recast/NavmeshGenerator.cs:20>) [Navmesh path queries](<aosharp-master/aosharp-master/NavmeshMovementController/Pathfinder.cs:15>)

Neocron currently extracts geometry for 787/791 world definitions (391 unique BSP source paths). That is a useful starting point, not completed navigation. The 158 authored ground-point records are too sparse to substitute for a thorough walkable graph. Repeated world variants can duplicate geometry and transition records.

Next requirements: measure the player's collision dimensions/step and slope limits; identify walkable surfaces, ledges and water; preserve moving-door obstacles; create floor/vertical links; bake/cache by game asset version; reject unreachable endpoints; validate a real route around a wall and through stairs/doors; then add multi-sector transition actions. AO agent dimensions must not be copied into NC units.

Important code-quality finding: the base AO movement controller detects lack of progress but its OnStuck method is empty. Borrowing this file does not supply robust recovery. Stop, explain the obstruction and use a bounded replan/retry strategy; do not add endless movement/jump loops. [Empty base stuck handler](<aosharp-master/aosharp-master/AOSharp.Core/Movement/MovementController.cs:183>)

## 7. Your own equipment and storage

AO's Inventory API distinguishes inventory, armor, weapons, implants, social equipment, containers and bank entries; InventoryPrinter demonstrates exposing name, slot, ID and unique identity. [Inventory and slot API](<aosharp-master/aosharp-master/AOSharp.Core/Inventory/Inventory.cs:97>) [Bank API](<aosharp-master/aosharp-master/AOSharp.Core/Inventory/Bank.cs:13>) [InventoryPrinter](<aosp-bots-master/aosp-bots-master/Utilities/InventoryPrinter/InventoryPrinter.cs:16>)

This is the correct next data-mapping target for exact gear inspection. Map the local character's actual item instances, slots, condition, mods and container contents. A read-only searchable inventory/bank/loadout viewer is already useful before adding movement or item actions. Snapshot bank contents when accessible and label them cached after closing/unloading.

The current remote-player inspector only sees published weapon/model appearances. More AOSharp code cannot cause Neocron to transmit another player's hidden inventory. Avoid spending the next phase promising exact remote implants or armor stats from appearance IDs.

## 8. Combat and hunting analytics

Mali's damage meter consumes attack, special-attack, health-damage/heal, reflect, shield, absorb and missed-attack messages, registers damage sources and tracks timing/character totals. Its data processing and display model are portable after replacing AO event bindings. [Damage/heal message processing](<malis-damage-meter-main/malis-damage-meter-main/N3MessageCallbacks.cs:24>) [Damage registers](<malis-damage-meter-main/malis-damage-meter-main/HitRegisters.cs:10>)

For NC, first identify a reliable combat-event or log source. Then show outgoing/incoming damage, healing, hit outcomes, damage types, encounter duration and session comparisons. NPC HP changes alone cannot attribute damage to a particular attacker, distinguish every heal/regeneration update or reveal missed attacks. Do not relabel net HP loss as an exact personal DPS meter.

A loot-run journal can start with area/time/observed death data, but confirmed kill credit and observed loot item counts require their own events. Measured per-kill drop rates require both a valid denominator and observed corpse loot; the current possible-loot catalog supplies neither.

## 9–13. Bigger integrations once the data exists

* Follow/escort: distance settings, leader updates and IPC in Manager.Follow are useful patterns. Use validated paths or recorded trails, maintain a gap, and stop on loss/floor mismatch. Straight-line pursuit through walls is not a finished follow mode. [Follow manager](<aosp-bots-master/aosp-bots-master/Managers/Manager.Follow/ManagerFollow.cs:57>)
* Buff/support assistant: show verified effect durations and resource thresholds first, then conditional healing/rebuffing. AO Buff uses actual engine timers, while CombatHandler orders rules and avoids duplicate pending actions. NC needs its own effect/cooldown and resource mappings. [Real buff durations](<aosharp-master/aosharp-master/AOSharp.Core/DummyItem/Buff.cs:19>) [Prioritized combat actions](<aosharp-master/aosharp-master/AOSharp.Core/Combat/CombatHandler.cs:56>)
* Missions: AO exposes objective actions and dialogue answer-list events; NC definitions could seed a reference browser before mapping active mission progress and interactions. [Mission objectives](<aosharp-master/aosharp-master/AOSharp.Core/Mission.cs:28>) [Dialogue actions/events](<aosharp-master/aosharp-master/AOSharp.Core/NpcDialog.cs:34>)
* Hunting/encounters: combine route -> choose a verified NPC -> approach -> fight -> confirm death -> open corpse -> apply item rules -> return/recover. Roamba's target ordering and Manager.Loot's state machine are strong references. NC still needs target/attack/LOS/own resource/corpse/item-action bindings. [Target selection rules](<aosp-bots-master/aosp-bots-master/Automatons/Automaton.Roamba/MobTargeting.cs:147>) [Loot workflow states](<aosp-bots-master/aosp-bots-master/Managers/Manager.Loot/ManagerLoot.cs:331>)
* Loot rules: exact/partial item names, quantity caps, one-each and destination containers are concrete examples. Begin with a rule preview/journal; automatic pickup or sorting requires actual item/container mapping. The AO manager also contains deletion paths; those are not merely sorting behavior. [Loot rule fields](<aosp-bots-master/aosp-bots-master/Managers/Manager.Loot/Rules.cs:3>)
* Coordinated own characters: IPC plus leader/roster and ready/target polls can support shared waypoints and explicit roles. Start with process selection and per-client isolation; the current reader deliberately refuses multiple matching clients. [IPC channels](<aosharp-master/aosharp-master/AOSharp.Core/IPC/IPCChannel.cs:5>) [Leader/roster handling](<aosharp.newbots-master/aosharp.newbots-master/BTBotBase/BTBotBase.cs:135>) [Action synchronization](<aosp-bots-master/aosp-bots-master/Managers/Manager.Sync/Sender.cs:83>)

## Framework work that makes these additions reusable

Keep a shared NC world-state service, event stream, route service and action/task scheduler beneath the UI. Each capability should report Available, Unavailable or Stale along with source and capture time. Plugins/rules can consume typed events and definitions without reimplementing memory reads in every feature. AO's core APIs and plugin separation demonstrate why this scales beyond a growing collection of windows.

Expose a preview of what a macro intends to do and an execution trace of what actually happened. Parameterize routines with destination, NPC template/name and repeat count. Keep movement actions separate from observation so an inspector, recorder or analytics panel cannot accidentally start controlling the character.

Some attractive consumer code is not self-contained. SPath, SMovementController and DungeonNavMeshFactory have no class definitions in the reviewed C# trees; plugins reference the AOSharpSDK/AOSharpSDK.SharpNav packages. The local plugin and root source versions differ, and the supplied projects include net48/x86 game bindings. This limits direct copy-and-build reuse, not the value of the design patterns. [Referenced pathfinding SDK](<aosp-bots-master/aosp-bots-master/Automatons/Automaton.Roamba/Automaton.Roamba.csproj:97>)

## Recommended implementation order

1. Record/edit/save sector-scoped routes and named destinations; add route preview and single-sector replay with measured progress and cancellation.
2. Add the task runner and live step/status display; wire only verified conditions/actions. Add nearby watchlists and observation events on the same snapshot stream.
3. Persist the NPC/service atlas; build the offline construction/recycling workbench and connect loot/reference searches.
4. Bake and validate local navigation meshes, vertical/door handling and explicit cross-sector actions; then add destination travel and follow.
5. Map own inventory, buffs, target/aggro and combat events; unlock accurate gear, resource, damage and loot-session tools.
6. Compose encounter/mission/crafting routines from validated primitives; add multi-client coordination only after per-process isolation.

A good first demonstration is a saved Plaza vendor circuit that displays its route, walks measured waypoints, pauses at the correct service NPC, returns to its start and reports why any step stopped. It should complete reproducibly before promising arbitrary seamless travel or full combat/loot automation.
