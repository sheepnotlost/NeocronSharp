# AOSharp tracking patterns adapted to Neocron

This is an independent read-only Neocron backend, not AOSharp loaded into a
different game. AO vtables, identities, enums and protocol messages are not reused.

| AOSharp source / pattern | Neocron implementation |
| --- | --- |
| AOSharp.Core/Dynel/DynelManager.cs world-object enumeration | PlayerReader.ReadEntities + Evolution902Actors.Read |
| DynelManager.NPCs and character filtering | Verified SCRIPTEDPLAYER NPC mapping; LSTPLAYER remains unclassified |
| Dynel name/position access and find-by-name | WorldEntity snapshots + EntityQuery.Nearby, name substring and radius filters |
| Identity-aware validity | EntityIdentity combines world, registry, node, payload, key and mapped kind |
| Updated world snapshots / appearance tracking | EntityTracking compares identities, reports appearance/disappearance, invalidates missing selections |
| Utilities/MonsterTracker name-based watch/UI | TrackerForm search, nearest-first list, selection details, native sector map and JSON export |

Source copies are under `..` relative to this project:
`aosharp-master/aosharp-master/AOSharp.Core/Dynel/DynelManager.cs` and
`aosp-bots-master/aosp-bots-master/Utilities/MonsterTracker/MonsterTracker.cs`.
The new models are available to future Neocron plugins independently of WinForms.

## Exact supported build

Evolution 2.5.902 x64, SHA-256
`8fa50ebe20b5e15738cfac398bef19fef3c048f0f3e89a7a9bad7172b73d5d8c`.
PlayerReader checks both the reference executable and the running module's file,
then verifies live roots, vtables and position/orientation getter instructions.
All RVAs below are relative to the loaded executable base. No process writes,
remote calls or injection are used; access is OpenProcess query + read only.

| Structure | Verified layout |
| --- | --- |
| WORLDCLIENT | Root pointer RVA 0xd68330; vtable RVA 0x60c6e8 |
| WORLDMGR | Pointer at WORLDCLIENT+0x58; vtable RVA 0x584418 |
| Actor hash table | Pointer at WORLDMGR+0x68 |
| Hash header | Bucket-array pointer +0x00; signed 32-bit bucket count +0x08 (live 1024) |
| Buckets | Array of 64-bit HASHNODE pointers; null means empty |
| HASHNODE | Vtable RVA 0x5ade80; signed 32-bit key +0x08; actor physics pointer +0x10; next +0x18; previous +0x20 |
| SCRIPTEDPLAYER physics | Vtable RVA 0x5bfe48; also its complete object |
| LSTPLAYER physics | Vtable RVA 0x5bbbb8; complete object is physics−0x1c8 |
| NPC display name | SCRIPTEDPLAYER+0x750: MSVC std::string, inline buffer/pointer +0, length +0x10, capacity +0x18 |
| Actor position | Physics+0xd8, three float32 values, X/Z ground and Y height |
| Getter check | Physics vtable+0x98 points to RVA 0x248270, `lea rax,[rcx+0xd8]; ret` |

Static corroboration:

- Hash insertion function RVA 0x25aa00 divides the absolute signed key by the
  count at header+8, stores the key at node+8, payload at +0x10, and links +0x18.
- Hash removal RVA 0x25a620 compares the 32-bit key at +8 and traverses payload
  +0x10 / next +0x18. Upper bytes at node+0x0c are padding, not part of the ID.
- SCRIPTEDPLAYER constructors RVA 0x303ef0 / 0x304410 install its vtable and
  initialize the std::string at +0x750 with length 0 / capacity 15.
- Name access around RVA 0x310954 selects +0x750 and uses capacity at string+0x18
  to choose inline or heap text. Live short `COPBOT` and heap-allocated
  `NEMA Papergirl - Mia  Coleman` independently validate both layouts.
- MSVC RTTI identifies the actual actor types and complete-object offsets.
  `tools/discover_actors.py` reads this metadata from the PE; it is development
  tooling, not a runtime dependency.

## Client update of 28 Oct 2026

The supported build is now SHA-256 `60bbdb55031f4cabb916ed46341a6920e150dc4dd6abfaa8ef08a947de4b01c1`.
The tables above describe 2.5.902; the new build moves these (old -> new RVA):
vtables by RTTI name and complete-object offset WORLDCTRLPLAYER 0x58b6a8->0x58f6f8, its physics
subobject 0x58b750->0x58f7a0 (now at +0x528, was +0x498), WORLDCLIENT 0x60c6e8->0x610be8, WORLDMGR
0x584418->0x588418, RPOSCONSOLE 0x587398->0x58b3e8, BASERPOS 0x587418->0x58b468, RPOSCOMPASS
0x5917b8->0x595c98, HASHNODE 0x5ade80->0x5b23d0, SCRIPTEDPLAYER 0x5bfe48->0x5c4388, LSTPLAYER
0x5bbbb8->0x5c0108 (still +0x1c8), PLAYERAPPMGR 0x5c5d90->0x5ca2c0; getters read from the same vtable
slots with identical bytes: position 0x248270->0x24bc90, transform 0x335a30->0x339540, dead flag
0x19d420->0x1a10c0, LSTPLAYER thunk 0x2e7178->0x2eac88, NPC dispatch 0x30fcb0->0x3137c0, appearance
getters 0x3dfa50->0x3e35a0 / 0x3dfa20->0x3e3570; globals by unique RIP-relative signatures player
0x6d3db0->0x6d7db0 and world 0xd68330->0xd6c330. The sector ID moved from WORLDCLIENT+0x258 to +0x264
(message 0x2779 handler 0x54c057 reads subobject+0x234). SCRIPTEDPLAYER/LSTPLAYER field offsets
(+0x218, +0x608, +0x738..+0x948, +0xad8, +0x750) and the getter-cited code sites are byte-identical.

## Bounds and consistency

At most 4,096 buckets, 8,192 nodes, 128 nodes per chain and 192 bytes per NPC name.
Reject invalid pointers, wrong hash buckets, cycles, duplicate actor payloads,
invalid getter targets, nonfinite/unreasonable coordinates, corrupt strings and
short reads. Compare each node before/after reading, each name header before/after
decoding, and registry header/bucket heads before/after traversal. Recheck player,
world and manager roots before publishing. Unknown actor classes are skipped;
decorations are not guessed to be NPCs. This is a best-effort external snapshot,
not a game-engine lock or an atomic view of moving positions.

Numeric keys really do collide between native classes in the observed registry.
Selection uses multiple instance checks, invalidates after a missing/unavailable
sample or session change, and does not automatically rebind to a returning key.
There is no verified engine generation counter yet: identical address/key reuse
entirely between refreshes cannot be ruled out. A changed displayed name also
invalidates the selection rather than silently following a different actor.

## Validation and remaining work

The initial tracking phase passed 41 tests, including real string layouts, native key collisions,
distance/bearing, filtering, lost selection, zoning/reconnect, empty registry,
unknown classes, cyclic/corrupt/mutating tables, name/coordinate bounds and short
reads. The published executable's live entities diagnostic and UI smoke flow
read the real running client. No keyboard/mouse game actions are part of tracking.

Live coverage is one Plaza area with 60 scripted NPCs (including COPBOT and Small
Spider), not every NPC type or every zone. Reconnection is implemented and tested
with model fixtures; a deliberate live zoning/despawn test remains to be done.
LSTPLAYER names and human/NPC distinction, other NPC class layouts, engine spawn
generation, current target/hostility and line-of-sight are not mapped.
Loaded actors can be on different floors or behind walls. No database name lookup
or screen OCR is substituted for the native data, and no health/level values are
invented from the supplied screenshot.

## Expanded NPC attributes

Native SCRIPTEDPLAYER fields now read in addition to position/name:

| Offset | Meaning and corroboration |
| --- | --- |
| +0x218, byte | Client dead flag. Vtable+0x160 points to RVA 0x19d420 (`movzx eax,byte ptr [rcx+0x218]; ret`). Death path 0x30aca0 calls 0x19d4a0, setting +0x218 to 1 at 0x19d4d9; the reset path clears it at 0x19da61. |
| +0x73c, int32 | Faction ID, copied from NPC definition+0x10 at 0x309657. Observed COPBOT=1, traders=7, Small Spider=18. |
| +0x740, int32 | Armor profile ID, copied from definition+0x2c at 0x30972c. -1 denotes the definition's absent armor profile. |
| +0x790, uint16 | NPC definition/template ID, passed to the NPC-definition lookup RVA 0xdb5d0 at 0x309616. |
| +0x798, uint16 | Native flags, retained as raw flags without inventing hostile/friendly meanings. |
| +0x79c / +0x7a0, int32 pair | Raw current and maximum client health. Dispatch RVA 0x30fcb0, event 0x30, returns these at 0x3103b1; event 0x42 also returns the pair. Debug health reset at 0x30892f names the +0x79c field. |
| +0x810, float32 | Native NPC skill/combat rank. Populated from definition+0x14 at 0x3096be; target-info event 0x3f5 uses it at 0x310879, clamps to 255 and truncates to a byte. |
| +0x818 / +0x820, float32 | Damage modifier and damage frequency, copied from definition+0x24/+0x28 at 0x30973f. Current modifier can differ from template value (observed COPBOT 1.5 versus definition 3). Frequency units have not been established. |
| +0x948, uint16 | Weapon definition ID, copied from definition+0x20 at 0x309732. COPBOT=1651; this belongs to pak_weapons, not pak_items. |
| +0xad8, int32 | NPC function code, copied from definition+0xd4 at 0x309774. Exported numerically without guessing a complete role enum. |

RPOS health update RVA 0x1402e0 requests event 0x30 at 0x140360. At
0x140379–0x1403ba it bounds the maximum to at least 1 and the displayed current
to [0, maximum]. The tracker follows this display bound for valid positive
maximum values, preserves RawCurrent and WasClamped in JSON, and marks invalid
health unavailable instead of manufacturing a maximum of 1. Observed client
accumulators include 18,413/15,168 for a COPBOT and 3,386/140 for a trader.
These are not used to claim health above 100% or exact server health.

NpcDefinitions loads the running executable's adjacent `definitions` directory:
pak_npcs.csv, pak_factions.csv and pak_weapons.csv. Their 16-byte headers consist
of the checked 12-byte signature plus little-endian uncompressed size, followed
by zlib-compressed UTF-8 CSV. Reads/expansion/row and field lengths are bounded;
CSV quoting uses the framework parser. Missing/corrupt tables are optional and
do not prevent native HP/rank reads. Joins use native template/faction/weapon IDs;
the model stores reference values separately. Faction zero is left unspecified
because table row zero is Soul Light, not a verified NPC faction label.

The UI now exposes HP percentage, rank and faction columns; selected details
include current/max HP, alive/dead, weapon, armor/template IDs, AI/dialog,
damage modifier/frequency and base weapon TL/range. Exports retain all mapped
native stats and optional local reference fields. No hostile flag or equipment
effectiveness is guessed from NPC names, flags or faction.

Expanded-NPC phase validation: 50 total tests, clean Release build, live JSON and live window checks
of 69 scripted NPCs (29 COPBOTs in that snapshot). The selected COPBOT read
15,168/15,168 client HP, rank 120, faction 1 / City Administration, weapon 1651 /
NPC CopBot Plasma Rifle TL 128. Small Spider's rank 1, faction 18 and HP maximum
15 were inspected independently earlier. Native template 10208 COPBOTs also
resolve correctly. Injured HP ratios and dead/unknown fields have fixture coverage;
live combat/death transitions have not been deliberately exercised.

## Native sector map and theme
The radar is now replaced by a resizable native sector map with player/NPC
markers, selection, wheel/button zoom, pan, fit and centering, names and height
filter. The theme uses milky gray neutrals in both windows. MAP-SPEC.md records
the native sector getter, compass orientation, exact projection and PAK format.
The local catalog resolves 161 sector definitions. Live Plaza SEC-1 validation
shows 77 NPC markers using the exact in-game map. Total tests: 61. The smoke
flow checks projection, marker picking, zoom stability and stale-marker clearing.

## Nearby players
LSTPLAYER identity and appearance are now mapped separately from scripted NPCs.
See PLAYER-TRACKING.md for exact offsets, gear coverage, default inclusion and
unload behavior. NPC-specific health/template offsets are never applied to players.
