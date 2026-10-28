# AOSharp capability research

Research date: October 27, 2026. Scope: the three user-supplied source archives,
the original maintainer's public repository and branch metadata, AOSharp Plus,
and selected public community projects. This is a source and documentation
review; the AO plugins were not executed against Anarchy Online.

**Finding.** AOSharp provides extensive access to Anarchy Online's objects,
events and actions. Its plugins combine that access into combat assistants,
coordinated teams, inventory/loot workflows, navigation and encounter bots.
The Neocron program built in this chat is a movement proof of concept. Its
position and heading reader does not reproduce the game access that makes the
AOSharp ecosystem useful.

**Evidence levels.** A local implementation is stronger evidence of an intended
capability than a project name. A maintainer README documents intended behavior,
but does not establish that every feature currently works. A community plugin is
an extension, not a feature automatically included in the core SDK. Proposed
Neocron equivalents below are engineering conclusions, not implemented features.

**Size of the supplied source.** Excluding packages, bin and obj, the downloads
contain 73 C# projects, 1,235 C# files and 118,614 C# lines. These are inventory
counts, not a count of independent features or a promise of current compatibility.

| Download | Projects | C# files | C# lines |
| --- | ---: | ---: | ---: |
| aosharp-master | 9 | 626 | 46,431 |
| aosharp.newbots-master | 7 | 58 | 6,062 |
| aosp-bots-master | 57 | 551 | 66,121 |

The complete 73-project listing is in [project-inventory.md](</C:/Users/Kainen/Documents/Neocron AoSharp/Research/project-inventory.md>).

**The core framework has nine substantial parts.**

| Project | What the supplied implementation provides |
| --- | --- |
| AOSharp | Windows launcher, plugin/profile configuration, injection/ejection and AO-specific client tweaks. |
| AOSharp.Bootstrap | In-process startup, native hooks, managed plugin loading/unloading and dispatch of game/network/UI events. |
| AOSharp.Common | Identities, vectors, stats/enums, native engine imports and data structures, resource/database formats, protocol message definitions and serialization. |
| AOSharp.Core | Managed game-object API: character, entities, spells, perks, combat, inventory, teams, pets, dialogue, trade, market, missions, events and game UI. |
| AOSharp.Navigator | Inter-zone travel over configured playfield links; the inspected implementation selects routes with Dijkstra's algorithm. |
| AOSharp.Recast | Navigation-mesh generation from AO terrain, room surfaces and water geometry using CritterAI/Recast components. |
| NavmeshMovementController | Navigation-mesh queries, paths and movement-controller integration. |
| AOLite | Experimental alternative client runtime with login/network sessions, reconnect behavior, plugin hosting and reuse of AO engine/resources. It still expects game files. |
| TestPlugin | Developer examples and experiments, rather than a separate finished user feature. |

Primary upstream: [original AOSharp](https://gitlab.com/never-knows-best/aosharp).
The supplied projects target .NET Framework 4.8 and include x86 game-facing code.
The upstream API also exposes a `feat/net8` branch whose Core project targets
.NET 8. The README describes newer loader/build arrangements that are absent
from the inspected root trees. Branches, SDK packages and launcher versions
must therefore be matched deliberately; the README alone is insufficient.

**Game-state access is the central capability.** The supplied Core exposes local
and nearby characters, NPCs and other world objects; identity and position;
health and other stats; buffs and cooldowns; fighting targets and movement;
items, containers, backpacks and bank contents; teams and pets; missions and
NPC conversations. These objects support actions such as attacking, casting,
using an item on a target, combining items, transferring items, trading and
interacting with terminals. Availability varies by object and implementation.

This is why many AOSharp actions can be dispatched inside the client without
depending on a visible button's location or an OS keyboard macro. It does not
mean AO's internal functions, offsets, packet formats or action semantics exist
in Neocron. The Neocron movement prototype currently uses foreground keyboard
and mouse input, which is a materially narrower interface.

**Combat is a rule-driven action system.** `AOSharp.Core/Combat/CombatHandler.cs`
contains prioritized item, scaling-item, perk and spell processors. It checks
requirements, ranges and pending/executing state, queues actions, avoids
duplicate queued actions and applies action timeouts. Profession handlers add
the actual decisions about healing, offense, defense, buffs, debuffs, pets and
items, as appropriate to the profession.

The supplied AOSP project has 15 handler projects: Adventurer, Agent, Bureaucrat,
Doctor, Enforcer, Engineer, Fixer, Keeper, Martial Artist, Meta-Physicist,
Nano-Technician, Shade, Soldier, Trader, and Generic. The AO-specific abilities
and item lists need new Neocron rules. The reusable idea is conditional action
selection based on current game state, rather than a fixed sequence of keys.

**The 17 managers cover a much wider range of gameplay.**

| Manager | Verified purpose or implementation evidence |
| --- | --- |
| Assist | Configured players to assist and target/attack assistance. |
| Attack | Combat-target coordination and options for taunting, range and recovery kits. |
| Bag | Backpack/bag-management functionality. |
| Follow | Follow a selected/named character, maintain a configured distance and use the movement controller. |
| GMI | Market inventory/orders, cash deposits/withdrawals and buy-order modify/refresh logic. This is not evidence of a general profitable trading strategy. |
| Help | Recovery-kit thresholds and helper/travel/mount-related controls. |
| Inventory | Rules matching item names and quality levels, including automatic deletion of matching inventory items. It should not be described merely as a harmless sorter. |
| Loot | Pickup rules including name, quality range, quantity, exact match, one-each and destination bag. |
| Mail | Mail/attachment processing and configured credit sending. |
| OST | Specialized taunt/tanking support. |
| Pet | Synchronize pet attack, follow, heal, wait, guard and behind commands. |
| PetHunt | Pet-based hunting/range coordination. |
| POH | Encounter-specific actions and positioning, recovery thresholds and movement-message processing. |
| Raid | Raid/team coordination controls. |
| Research | AO progression research selection, including lowest-first/highest-first modes; this is not Neocron item research. |
| SocialPet | Social-pet management. |
| Sync | Multi-client movement, attack, targeting, use, dialogue and trade synchronization, plus team/formation-related commands. |

Source: the downloaded [AOSP Bots](https://gitlab.com/aosharp-plus/aosp-bots)
manager source directories. These are intended behaviors found in source, not a
claim that every manager was live-tested on the current AO service.

**Team coordination goes beyond following.** `Manager.Sync` contains messages
for movement, targets, attacks, use, NPC dialogue open/close and answers, NPC
trade, team formation and other activities. Other plugins use IPC channels to
share configuration and actions. NewBots adds roster/leader handling, ready and
target polls, shared targets, start/stop messages and explicit fighter/leecher
roles. A single leader can therefore coordinate several characters with
different jobs when the appropriate plugins and game bindings are present.

**Navigation has local and global layers.** Local movement operates on queued
paths/waypoints, turns toward the next waypoint and checks for lack of progress.
Navigation meshes describe walkable geometry. The global navigator connects
playfields through borders, teleporters and AO transport terminals, including
Grid/Fixer Grid links. The DungeonSolver tracks visited rooms, floors, lifts and
clear/blitz modes. These systems need geometry, transitions and interaction
semantics; a two-coordinate straight-line controller supplies only a small part.

**Roamba is a particularly useful reference for an actual task-oriented bot.**
Its supplied state machine contains Idle, Roam, PathToMob, Fight and Loot states.
Configuration includes:

- Priority and ignored target names, and a priority-only mode.
- Automatic/manual attack range, padding, taunt range and taunt-item usage.
- Whether to path to mobs or corpses, path range and wander limits.
- Fight and loot timeouts.
- Following configured character names.
- Conditions involving health, nano, being attacked and nearby players.
- A path editor and configuration editor.

The source shows how navigation, target selection, fighting and looting become
one reusable workflow. Their implementation would be impossible to reproduce
faithfully in Neocron while the program can see only position and heading.

**The encounter and mission bots combine these capabilities.** AOSP has eight
automaton projects: City, DB1, DB2, Inf, KH, Mitaar, Roamba and Vortexx. They
contain encounter-specific constants, state machines, coordination and recovery
behavior. NewBots adds AIMission, InfernoMission and S13 plugins, with shared
DungeonRunner, DungeonSolver, BTBotBase and a test plugin. AI mission code, for
example, handles readiness, obtaining a mission from a recruiter, entering it,
exploring the dungeon and boss behavior. These are specific scripted workflows,
not a universal agent that understands arbitrary quests.

**The utility projects provide concrete convenience automation.**

| Utility | Purpose |
| --- | --- |
| AOIA Bank Manager | Cycles inventory/bank bags and opens their contents; supports exposing those contents to item-assistant workflows. It is not itself a complete external searchable inventory service. |
| AutoItemLevel | Upgrades supported AO items when the character's requirements permit it. |
| Boss Logger | Boss/event logging. |
| Coffee / Cookies | Automation around those particular AO item workflows. |
| CombineNSplit | Batch item combine/split operations. |
| Crystal Filled by the Source | An AO-specific crystal workflow. |
| Defend the Grove | An AO-specific task helper. |
| ICE | Item-processing/recompiler-unit workflow. |
| InventoryPrinter | Inspect/print inventory information. |
| MonsterTracker | Find/track named entities, with a follow option. |
| Pearls / Plasma | AO item-processing workflows, including monster-part/plasma handling. |
| Relay | Multi-stage alien-relay construction and item movement. |
| SimpleAutoSeller | Automatic vendor selling. |
| TradeskillAndSell | Combine an item-processing workflow with selling its output. |

The 16 compiled utility projects include separate Coffee, Cookies, Pearls and
Plasma projects. `Shared` is the remaining AOSP project, containing common
configuration, UI, recovery/kit and supporting logic. An additional loose
AOSharp Ingame Panel directory is not an additional compiled project in this count.

**Community extensions add capabilities beyond the supplied archives.**

- [RubiKit / NotumHUD](https://github.com/thehillbeyondthisone/RubiKit) documents
  a local HTTP API and live event stream for character/group data, plus a
  customizable statistics dashboard showing resources, modifiers and armor.
  This demonstrates a useful external interface built on rich game access.
- [AOSharp DevTools](https://github.com/Just1uke/AOSharp-DevTools) documents
  inspection of constants/UI resources, native module function invocation and
  event/packet monitoring for plugin development.
- [PacketLogger](https://github.com/Vitecval/PacketLogger) is a community debug
  plugin for inbound/outbound packets and decoded N3 messages.
- [TeamInvite](https://github.com/ZoeFken/AOSharp-TeamInvite) documents character
  name resolution and invitations outside local vicinity, subject to normal
  server constraints. This is an AO-specific protocol capability.
- A public [automation fork](https://github.com/VladC92/aosharp-automation)
  contains Radar visualization using world-space debug spheres/lines and a
  MultiboxHelper that synchronizes selected actions. These are additional
  source references, not a guarantee of a currently maintained release.

**Repository status matters.** The public
[AOSharp Plus group](https://gitlab.com/aosharp-plus) explicitly identifies itself
as a community collection rather than the official SDK. Its API currently marks
the older Utilities, CombatHandlers-Managers and Buddy System repositories
archived, while AOSP Bots and Knows AOSharp mods are unarchived. Do not count
older and newer copies of the same feature as independent capabilities. Two
older repositories linked by the original maintainer, `aosharp.bots` and
`aosharp-automation`, redirected to sign-in during this review; their current
contents were not assumed. Public forks were identified as forks, not originals.

**What this means for Neocron.** The useful adaptation target is a set of
complete gameplay tools that share reliable knowledge of the game. The following
are proposed equivalents, not features already implemented:

| Useful Neocron feature | AOSharp reference | Required Neocron access |
| --- | --- | --- |
| Named mob/NPC tracker and follow | MonsterTracker, Follow, entity API | Nearby objects, stable identities, positions, names and targetability. |
| Conditional healing/buff/consumable assistant | CombatHandler and profession handlers | Current/max resources, effects/timers, quickbelt contents, availability and use actions. |
| Loot filter and inventory cleanup | Loot, Inventory, Bag | Corpse contents, item IDs/counts/properties, ownership and verified transfers. |
| Research/construction/recycling batches | CombineNSplit, TradeskillAndSell, Relay patterns | Processor state, ingredients, recipes, inventory movement and observed completion. |
| Vendor/restock/deposit workflow | AutoSeller, bank/GMI/trade APIs | NPC interaction, prices/quantities, storage and transaction outcomes. |
| Multi-character support | Sync, Assist, Follow and shared IPC | Per-client state and actions, team identities and reliable entity references. |
| Route-based patrol or dungeon task | Roamba, Navigator, DungeonSolver | Full routes/geometry, steering, obstacles, interactions and zone transitions. |
| Complete hunting loop | Roamba and combat/loot/resource managers | Search target -> approach -> fight -> recover -> loot -> continue/return. |
| Useful live dashboard/API | RubiKit pattern | Verified resources, effects, inventory, team and entity data worth displaying. |

AO-specific perks, nanos, pet systems, transport networks, profession rules,
item recipes, raid mechanics and packet definitions need Neocron equivalents.
In particular, AO research progression and Neocron item research are different
systems, and AO pets should not be treated as a ready-made Neocron drone API.

**Recommended change in direction.** Stop treating the saved-spot tool as an
AOSharp adaptation. Keep it as a tested movement component. The next substantive
work is to make the Neocron program understand nearby objects, character
resources/effects, inventory/quickbelt and interaction results. Attach each
verified interface to a useful feature immediately, such as a named-object
tracker, a resource assistant or a selective-loot tool. Then combine those
features with navigation into complete workflows. Installing a plugin loader or
adding another settings window alone does not supply that utility.

This recommendation follows from the inspected dependencies. It does not claim
that AOSharp plugins will run against Neocron, that all native fields have been
found, or that obstacle navigation and combat are already solved.
