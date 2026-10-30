# NeocronSharp — feature ideas

Requested alongside implementation on 26 October 2026. This list is a roadmap, not a claim that every idea exists.

## Delivered in this update

- User-saved construction names and aliases; no per-recipe code or image template required.
- Faster first-verified-blueprint search and arbitrary source-cell detection.
- Optional per-batch slot counter and stop at a chosen minimum slot count.
- Recycling catalog/prepared single run, 10 native skins, optional stop sound, and thorough spec/checklist.
- Detection-preview image concept and an interactive skin concept board.
- Broad searchable construction item catalog with build-method status. (Recipe Favorites were also delivered, then removed 26 Oct 2026 at the user's request.)

## Best next features

1. **Real detection preview.** Highlight the current source, free destination, quantity confirmation and Start before any input. Show decoded name and why a candidate was rejected. The existing photo is only a mockup.
2. **Batch ledger.** Save completed quantities, failures, elapsed time, slot histogram and user-entered costs by recipe/character/date. Export CSV; keep unread values distinct.
3. **Build queues.** Construct missing weapon parts, then use them for Holy Heal or another spell. The user's Holy Heal chain includes Weaponparts 9/7/6/5/4/1. Verify every phase rather than assuming tools/inputs carry over. (Delivered 29 Oct 2026 as the Construction queue: jobs run in order; chaining a built part into the next recipe is up to the order you give.)
4. **Supply preflight.** Read tool condition, grease/fluid availability and free inventory capacity before a batch and explain the limiting resource. Requires actual game fixtures for each indicator.
5. **Materials calculator.** Store user-confirmed ingredient quantities and stock, estimate build capacity and produce a shopping list. Do not invent missing source quantities.
6. **Recipe import/export.** Share a plain JSON recipe book with names, aliases, notes and presets. Validate it as data; no scripts or remote actions.
7. **Slot history.** Compare distributions across sessions/recipes and character setups. Report sample sizes; do not infer a slot-chance formula from small batches.
8. **Result gallery.** Save a tooltip crop and metadata for noteworthy builds, especially 4/5-slot results, with optional local-only retention limits.
9. **Full job and character presets.** Save named sets of recipes, counts and preferences while still detecting all positions afresh.
10. **Reusable skins.** Load validated color/font token files and let the user adjust contrast/density without editing Python. The delivered skins are predefined, not a .wsz importer.
11. **Session reports.** End with built/requested, supplies remaining when verified, slot totals, stop reason and the last confirmed action.
12. **Diagnose-last-stop button.** Present the saved game frame and decoded tooltip together with a concise failure explanation.

## Further game-specific directions

- **Rare-part collection tracker:** read identified part names and group hull/frame/core/component/tech/add-tech sets, showing missing pieces. Start with a tracker rather than automatically consuming rare sets. [Tech-part reference](https://wiki.techhaven.org/Tech_Part)
- **Recycling material loading and queues:** extend the prepared-run mode after recording actual quantity and consumed-input behavior. Add explicit cloning/part-upgrade/salvage workflows rather than treating them as interchangeable. [Recycling reference](https://wiki.techhaven.org/Recycle)
- **Grease/fluid usage history:** measure verified consumption by item instead of assuming a fixed quantity; useful for planning and cost estimates.
- **Slot-target alerts:** distinct optional tones when a target is found, stock is exhausted or a batch ends. The current update has one stop tone.
- **Craft-order sheet:** record who requested an item, quantities/slot target and progress locally; no automatic messages or trades.
- **Database-assisted recipe updates:** show source date, additions and changed quantities for review before replacing a user's catalog.
- **Screen-read confidence dashboard:** show which elements were verified, current OCR name and pending state, so problems can be diagnosed without guesswork.

Construction slots, blueprints and grease make slot-oriented batch tools a natural fit. [Construction reference](https://wiki.techhaven.org/Construct) Published guides can be older than current gameplay; the user's recordings and verified UI behavior take priority when a procedure differs.

No movement/combat automation, automatic chat/trades, or background-client control is included in these proposals.

## Beyond tradeskills — companion-suite brainstorm

Requested in chat while the catalog/Favorites update was being packaged. These are proposals, not new implementation commitments.

- Character profiles: builds, equipment, goals and notes per character.
- Build planner: compare skill allocations using sourced formulas.
- Implant/buff planner: equipment requirements and loadout dependencies.
- Equipment loadout checklists for PvP, hunting, leveling and tradeskills.
- Rare-part tracker: owned sets, duplicates, missing pieces and exportable trade lists.
- Inventory/cabinet index: searchable saved records or scans by character/storage location.
- World map: personal markers, vendors, hunting spots, meeting points and route notes.
- Mission journal: multi-step progress and reminders across characters.
- Session tracker: loot, expenses, duration and progress comparisons.
- Combat experiment notebook: measured damage observations with equipment/setup notes; separate observations from assumptions.
- Clan dashboard: projects, supply requests, events and equipment needs; manual sharing first.
- Trade assistant: wanted/sale lists, price notes and copyable messages for the user to post.
- Searchable screenshot notebook linked to items, builds, locations or bugs.
- Game configuration profiles: backup/restore supported settings files.
- Personal command deck: favorite characters, recipes, maps, notes and tools in one landing page.

Suggested first companion modules: rare-part tracker, cabinet index, build planner and world map. None requires automatic combat or messaging.
