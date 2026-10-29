# Useful features found in the installed Neocron client

Research date: 2026-10-27. Installation examined: `Neocron Evolution 2.5`.

## Best next feature: an item acquisition and quest assistant

The strongest immediately useful discovery is that NPC dialogue, quest requirements, reward items, and crafting ingredients can be connected. A player could select a desired item, see its supported acquisition steps, pin the required ingredients, and have the existing tracker highlight relevant nearby NPCs or mobs.

This is a proposed feature, not a change already made to NeocronSharp. Its first version can work from local reference data and the existing entity tracker. Automatic inventory counts, quest completion detection, and route execution require additional work and must not be implied by a static guide.

### A verified end-to-end example: Swamp Shaman Trophy

The English YAML defines Sorcha Nox as NPC template **10677**, with a source comment placing her in **Swamp Sector F03, world 2103**. It specifies killing one Kri'nakh Shaman, NPC type **1514**. The next stage requires:

- 5 Kri'nakh Poisonglands
- 1 Immunosuppressive Toxins
- 10 Plant Fibers
- 1 Fucoxanthin
- 1 Gibberllin

The quest awards **Swamp Shaman Remains**, item **13112**. The recycling table then links those remains to **Swamp Shaman Trophy**, item **13113**, using the remains plus **2 Wood, 3 Metalplate, and 1 Wire Junk**. Item names and repeated ingredient counts were resolved from the actual item table.

Sources: [quest source NPC and target](<neocron-decoded/scripts/yaml/trophymissions/pak_shamantrophy.yaml:25>), [collection objectives](<neocron-decoded/scripts/yaml/trophymissions/pak_shamantrophy.yaml:57>), [reward](<neocron-decoded/scripts/yaml/trophymissions/pak_shamantrophy.yaml:117>), [recycling recipe](<neocron-decoded/definitions/pak_recycle.csv:229>), [item names](<neocron-decoded/definitions/pak_items.csv:4453>).

The NPC definition uses the same YAML dialogue key, `shamantrophy.dialogue.sorcha.startnode`, so this can be attached to an identified NPC instead of relying only on matching a displayed name. [NPC definition](<neocron-decoded/definitions/pak_npcs.csv:2624>).

The practical in-game result would be: pin “Swamp Shaman Trophy”; see the quest contact, requirements, and final recipe together; highlight a relevant loaded target; keep a checklist of ingredients to save instead of discarding them. The source gives a sector, not Sorcha's exact XYZ position. Exact map pins need authored coordinates or an observed live entity.

## Other concrete opportunities

| Feature | Evidence found | Useful first version | Important remaining work |
| --- | --- | --- | --- |
| Contextual NPC quest guide | 1,028 Lua files and 85 YAML files in `scripts`; NPC definitions contain dialogue keys; mission tables contain objectives and rewards | Select an NPC and show known quests, prerequisites, required items, rewards, and dialogue steps | Index conditional branches correctly; distinguish legacy/demo/localized files; map live quest state separately |
| Reverse crafting and loot search | 228 enabled recycling recipes, 448 construction-plan rows, 1,616 component rows, 4,459 item definitions; existing app already has a loot catalog | Search an item and show known recipes and locally defined drop sources; pin a shopping/loot checklist | Resolve qualifier rules; preserve repeated ingredients; avoid presenting raw container weights as drop percentages |
| Equipment and implant planner | 272 implant definitions and 1,007 modifier rows; 392 armor definitions and 2,197 armor modifier rows; 951 item restriction rows | Compare selected equipment, show documented bonuses/penalties and requirements, build a manual loadout | Decode every stat target and stacking rule; quality scaling and live equipped inventory need separate validation |
| Service and destination finder | 23 NavRay menus, 223 submenu rows, 83 respawn-definition rows | Search for supported services and show known destination categories alongside the sector map | Resolve category IDs to actual world objects; verify coordinate systems; route definitions are not a traversable navmesh |
| NPC combat reference | NPC armor IDs plus 5,720 NPC armor rows; weapon, ammunition, instant damage, and damage-over-time definitions | Expand the inspector with reference armor/damage information and compare profiles | Verify numeric damage-type mapping, sentinel values, mitigation formulas, and script-driven attacks before recommending an optimal damage type |
| Shop catalog and supplier search | 314 trader definitions, 1,875 trader-item rows, item trader-group IDs, and scripted `TRADE()` calls | Search locally defined merchandise and inspect supported shop groups | Negative trader-item IDs require group expansion; individual NPC-to-trader links and actual prices/stock are not yet established |

These are definition counts, not counts of distinct quests, currently spawned NPCs, or active shops. The script set contains older versions, demo scripts, and localized material. File presence alone does not establish that a server enables that content.

## More examples from actual quest code

### Wisdom of Ceres power armor

The script checks `GetWOCSkill()` for a value of at least one, branches by character class, lists acceptable standard armor IDs including C-30 alternatives, and sets a **2,500,000-credit** donation. This supports a useful “what do I need to bring?” view instead of discovering missing requirements after traveling to the NPC.

Sources: [required armor IDs](<neocron-decoded/scripts/lua/woc/pak_woc_powerarmor.lua:43>), [donation and WoC check](<neocron-decoded/scripts/lua/woc/pak_woc_powerarmor.lua:81>), [class-specific choices](<neocron-decoded/scripts/lua/woc/pak_woc_powerarmor.lua:106>).

### The Big Bad Gun

The installed script identifies mission IDs **5369–5371**, Commander Harris as the contact, and the MIRL-600 Warhammer Rocket Launcher as a reward constant. The entry branch explicitly checks a **base rank of at least 55**. Later dialogue sends the player to the Juggernaut Facility in I-09. A guide could expose the rank gate, required components, and mission locations in one place.

Sources: [mission/location/item constants](<neocron-decoded/scripts/lua/woc/pak_woc_bigbadgun.lua:15>), [rank gate](<neocron-decoded/scripts/lua/woc/pak_woc_bigbadgun.lua:63>), [first assignment](<neocron-decoded/scripts/lua/woc/pak_woc_bigbadgun.lua:121>). Comments can be stale; executable branch conditions are stronger evidence than comments, and live availability still needs checking.

### Built-in destination categories

The client explicitly defines Primary Apartment, Gene Replicator, GoGuardian, CityCom Station, and Neocron Subway as NavRay submenu entries. Reusing this destination vocabulary would make the map more useful. It does not establish that all station positions are already decoded or that a character can automatically walk between them.

Source: [destination definitions](<neocron-decoded/definitions/pak_routesubmenus.csv:2>).

## How this should connect to the existing program

1. Build a local reference index keyed by NPC template, dialogue key, item ID, and mission ID, keeping source file/line provenance.
2. Add an NPC “Quests / Requirements / Rewards” view and an item acquisition search.
3. Let a player pin an acquisition goal. Highlight relevant entities only when the existing tracker actually sees them; retain known sector-level locations separately.
4. Start with manual checklist state. Add inventory and mission-state integration after those live fields are verified.
5. Add route execution only after the navigation layer is reliable. The reference assistant is useful independently of that work.

A general regex cannot safely turn all Lua dialogue into a linear walkthrough: branches query faction, class, rank, mission flags, and inventory; some calls consume items or start missions. Treat Lua as source to analyze, not code to execute in the app. The YAML is a better first structured source for quests, with selected Lua quests added using validated adapters.

## Coverage and research artifacts

The installation contains compiled native binaries, not the full engine's C++ source. This investigation inventoried 76 definition CSV tables and decoded 1,201 Lua/YAML/DEF/English-text files without modifying the originals. It inspected representative quest branches and joined a complete trophy acquisition example across three kinds of data. It did not manually verify every script or establish every server-side rule.

Compressed files checked during decoding use a 12-byte signature, a 4-byte little-endian uncompressed size, and a zlib payload beginning at offset 16. Readable copies retain the original relative path under `Research/neocron-decoded`; the linked files above are those decoded copies. An additional 23 definition tables were decoded there for this investigation.

- [All definition schemas, enabled counts, and samples](<neocron-all-definitions.json>)
- [Decoded source mapping and Lua call index](<neocron-script-index.json>)
- [Earlier AOSharp research](<AOSharp-next-features.md>)

The immediate recommendation is the acquisition/quest assistant, followed by the manual equipment planner. NPC resistance analysis is promising, but labeling guessed damage IDs or treating missing armor rows as zero resistance would produce misleading combat advice.
