# Neocron Macro Suite — specification sheet

Revision: 27 October 2026. Platform: Windows x64. This is the current consolidated specification. SPEC.md retains earlier implementation notes; TASKS.md is the delivery checklist. Proposed ideas are separated in FEATURE-IDEAS.md.

## Product

A portable, foreground desktop macro for Neocron Evolution / Neocron 2 research, construction, prepared recycling and cabinet/inventory counting. It uses screenshots, local visual/text recognition, and normal game input. Correct item, quantity and current position take precedence over speed. Processing duration varies by item; elapsed time never declares a job complete.

The application is named Neocron Macro Suite. The primary folder, local shortcut, portable ZIP and ZIP root use that name. The tool icon retains the screen-like green top requested earlier.

## Shared interface and controls

- Research, Construction, Recycling and Tech Counter tabs share one Start in 3 seconds execution button.
- Construction contains Job and Catalog pages. Outside countdown/execution, only the construction Catalog page disables Start; Use blueprint recipe never starts a job or overwrites batch counts.
- Construction Job's Prepare in Neocron panel is terse bullets: Inventory + Processor visible; slot 1 construction tool; Inventory scrolled to top (search runs downward); stack size = actual count; ingredients stay in Inventory; empty cubes/previous result may stay; stop by switching away, no auto-resume.
- No macro hotkeys, Stop button, coordinate calibration or automatic resume.
- Bind the exact foreground Neocron window/process/client size at countdown end.
- Stop on focus loss, minimization, game closure/identity change, changed client dimensions, app closure, or an unverified action/state.
- Lock job settings/tab switching during countdown and execution. Display status, detected Processor position, completed counts and a local log.
- Store each operation's settings independently. Skin and stop sound are global preferences.
- Paragraphs wrap to their allocated panel width on resize/skin changes; flexible recipe/alias/search fields stay within their columns. Narrow layouts keep content available through vertical scrolling.
- Paragraph grid spans must include an expanding column; ignore initial placeholder widths when calculating wrapping. Research sequence settings must remain readable at normal and maximized sizes.
- A visible horizontal divider/handle drags up/down to resize the bottom Activity log. Keep Start, settings and tabs in the upper pane; the read-only log has a vertical scrollbar and a minimum usable height. Divider resizing is independent of game execution and available in all skins.
- Counts/settings save on Start; added recipes and appearance/sound preferences can save immediately.

## Recognition and input invariants

1. Capture only the bound focused game client. Guard focus, identity and size before/after captures and before input.
2. Locate opaque PROCESSOR text and independently verify the current Start control. Use coarse proposals and native-resolution refinement, including small raster-size variants.
3. Verify Inventory using its title and independent Max Load / Free Load labels; the navigation label alone is insufficient.
4. Derive destination slots from the current Processor anchor; detect movable quantity dialogs independently by their title/Half control.
5. Reacquire positions after scrolling, dialogs and completion. Artwork/scale caches are allowed; unchecked old coordinates are not.
6. Hidden, clipped or ambiguous controls cannot count as a valid target or completion. Localization retries are bounded.
7. Drags are always plain left drags (no button/modifier options; collect() saves left/none). Release only inputs the macro pressed, including after interruptions.
8. UI settling/polling waits are permitted. Fixed research/build timers and repeated Start clicks on an ignored attempt are not.

## Tech Counter

The fourth tab embeds the counter imported from `sheepnotlost/neocron-tech-counter`
at revision 43c8402. Cabinet/Inventory selection and all-items/techs-only filtering
are saved independently. The shared Start in 3 seconds button begins a scan after
binding the foreground game. Scanning hovers, reads stack quantities and names,
scrolls to the top then through unseen rows, and aggregates named lists. It never
clicks/transfers items or brings the game back into focus. Mouse movement also
aborts a scan. Only one crafting/counting worker can run at a time.

Lists, scan editing/renaming/deletion, manual entries, undo, locations, exports
(clipboard/CSV/by-cabinet CSV/TXT/JSON) and the 86-item rare-set database are retained.
Partial and uncertain reads remain marked. Repeated scans add entries; they do
not automatically replace a prior cabinet scan. Native suite skins apply to the
embedded controls; standalone global hotkeys and custom topmost root are omitted.

State resides in `tech-counter/`. First-use migration copies lists/known names/
config from the original sibling folder, preserving source files and existing
destination files. An explicit folder-import button supports other locations.
Existing standalone exports remain in place; suite exports default under this
state folder. No personal counter state ships in Git or the portable archive.
Tesseract/English data and Python OCR libraries are bundled locally. Crafting
continues to use Windows OCR. See TECH-COUNTER-INTEGRATION.md for implementation
boundaries and checks. Automated checks do not establish live game accuracy.

## Research

### Tech parts

- Types T, E, A, L, in that order. User enters actual availability and requested counts; requested zero skips a type.
- Find current source/destination, drag one part, verify quantity 1, find current Start and click once.
- Observe input clearing to confirm a processed attempt; a missing Processor cannot count as a cleared input.
- Decrement remaining/available counts only after confirmation.
- Game returns the previous result on next Start; leave the final output in Processor.

### Item to blueprint

- User prepares research tool, item and empty cubes in Processor.
- Macro clicks Start only; it does not move Inventory items in this mode.
- Copy count zero repeats until stopped; positive count is finite.
- Require observed processing, three idle observations and a visible datacube result recognized independently of its color.
- Adopt an already processing attempt without clicking again. An ignored Start stays monitored, not spammed.

## Construction

### Recipes and matching

Built-ins: Tangent Weaponparts 7/9 and Crahn Holy Heal. User-defined recipes are saved names/aliases, not new code or icon captures. An editable Recipe field accepts a full name or shorthand; Add / update recipe saves it. A new typed recipe is also saved on Start. Aliases are comma-separated. WP7, WP9, HH are supplied; WP plus a number expands to Weaponpart plus that number. Unambiguous initials can match item words.

Remove recipe deletes the selected custom Job entry or hides a built-in. Preserve entered counts and the source Catalog. Re-add by name/shorthand or Catalog selection; built-ins restore their original recognition/templates. Persist removal. An empty Job book is valid while idle/using another operation; construction requires a selected recipe. Lock removal while starting/running.

Local Windows OCR reads tooltip names. Text is normalized to reference font size to avoid native-versus-recorded resolution differences. Built-in name templates provide additional verification. Spelling noise may be tolerated; item numbers must match exactly. Ambiguous names remain unverified; full names resolve ambiguous shorthand.

### Searchable construction catalog

Ship 1,263 item entries across 38 categories from sourced Tech Haven category listings and known part names, retrieved 26 October 2026. Search case-insensitive names/known material names and WP-number shorthand; filter by category. Display listed level, build method, source URL, notes and material names when published. Keep unavailable source categories recorded in the data.

Three supplied construction examples have known material names. Other item listings do not establish blueprint availability or publish construction materials; label them Check blueprint and leave ingredients null. Users must supply a matching in-game blueprint/materials. Rare-part and recycling-only references cannot enter the blueprint executor. Never describe the whole item catalog as verified build recipes.

Use blueprint recipe saves the selected name to the custom recipe book and opens Job; preserve existing aliases and batch counts. Keep the browse catalog outside the running detector's recognition set so its size does not slow every hover. When a longer OCR title includes a built-in prefix, retain the fully verified longer name; keep exact-number conflict checks.

### Inventory search

- Default Fast mode proposes possible datacubes from each screenshot using the existing compact color/body check plus multi-size edge-shape matching for neutral/unusual colors. Hover only proposals, verify their BLUEPRINT names, and scroll when absent. False proposals are acceptable; no proposal alone authorizes input.
- Explicit Thorough mode retains exhaustive hovering: visit all previously unchecked visible cells in row-major order. In this mode, do not exclude a new cell from its first hover based on icon color/shape, occupancy or a finished-item classifier.
- Store search_mode=fast/all_cells in construction settings; old/missing values default to fast. Expose Inventory search in Job/Transfer controls and lock it during countdown/execution. Fast not-found guidance points to the explicit Thorough fallback; it does not silently restart a slow full sweep on every page.
- Clear prior hover text, briefly hover each cell, and verify BLUEPRINT plus the selected name. Allow short delayed-tooltip retries. Unrelated/empty cells do not receive a long name-read timeout.
- On a candidate match, observe the blueprint tooltip disappearing outside Inventory and re-hover that exact cell to confirm its identity again before transfer. A stale tooltip cannot authorize a different cell.
- Verify current Inventory title and independent load labels in fresh local crops during the sweep; if those fail, fully relocate Inventory and restart the page. Local checks reduce whole-screen searches without trusting an unchecked position.
- Show row/page progress. Unreadable names do not authorize input or block the remaining search; include unreadable observations in the final not-found report when present.
- Before/after scrolling, compare normalized opaque item/text features to establish a unique downward row displacement. Reuse only checked cells with matching content in the overlapping rows. New, changed and unresolved cells remain in the scan. Repeated/blank/ambiguous evidence does not prove a displacement; fall back to scanning. Window relocation invalidates the overlap state. Clear hover text before recording the comparison view.
- A definite unrelated tooltip or confidently empty cell can be marked checked. An occupied cell with no tooltip, or an unknown blueprint name, remains unresolved and eligible after scrolling. A visible non-blueprint panel can be rejected without the second capture; empty cells receive one short read, occupied cells retain delayed-read attempts.
- Remember the last verified source's grid cell within the current batch. On the next build, re-detect Inventory and verify that cell's current tooltip first. Re-confirm it before transfer. A cache miss falls back to the remaining visible cells; no old absolute point is reused and cache state is not persisted across batches.
- Before the first search, verify Processor/tool/free input and reject active jobs, quantity dialogs and pending unprocessed inputs. Permit used empty cubes/previous output as before. An interrupted transfer is not silently adopted or retried.
- Search checks for pending quantity dialogs initially and immediately before authorizing transfer. Scrolling/hovering does not repeat the full dialog scan every page. A detected Inventory scale can narrow quantity title matching while exact title/Half/one-digit checks remain required.
- Between pages, scrolls and builds, reuse the last verified Inventory position through the title/load-label check (current_inventory); a failed check relocates fully. During build monitoring, search for a quantity dialog every fourth poll and always before accepting completion. Live (26 Oct): cold Fast search about 5.3-5.9 s, previous-stack check about 1.2-1.4 s.
- Use the first verified matching stack immediately. Do not hover all other stacks after a match. The user's availability applies to that selected stack.
- Source placement is arbitrary; find the current cell every run.
- If absent, move into freshly located Inventory, pause briefly, scroll one notch down, and retain the pointer there while the game consumes the wheel event. Verify the opaque scrollbar thumb advanced relative to the window before searching new rows. Retry the wheel once on no movement.
- If wheel input is ignored, use the freshly detected opaque thumb for bounded 1/2/3 native-pixel drag steps. Stop on the first verified advancement, preserve overlapping views, and never blindly jump to an unchecked position. Release a held button on focus loss/error. No wheel/drag response or a thumb at the bottom ends the search.
- During hovering, optionally capture only the union of Inventory/header and nearby tooltip pixels, padded into client coordinates. Guard the original full client dimensions before/after capture. Missing local headers trigger a full client recapture; final Processor/quantity checks remain full captures. Backends without regional capture retain the full-frame path.
- Start from current scroll position, continue downward, and do not wrap/reset silently. Starting at the top searches all rows.
- Stop on hidden scrollbar, no advancement, focus loss or 128 scrolls. Bound relocation retries separately.

### Name reading and quantity entry

- Tooltip names are read from a line trimmed 4 px from the border; if the words match a numbered recipe but no number was read, re-read with 3 then 2 px trims. The number must still match exactly.
- The shipped WP7/WP9 pixel templates may supply a name only after their final digit passes a separate digit-only match (≥ .80). If OCR clearly read a different number, neither source authorizes. A custom numbered name read exactly by OCR is not vetoed by a shipped template.
- To enter quantity 1, click the field, send Ctrl+A, clear with six Backspace and six Delete presses, then type 1. Confirm only when the dialog reads exactly 1.

### Transfer, Start and completion

1. Reacquire source/Processor. Verify construction tool and free destination. Permit used empty cubes; reject other pending/unknown inputs.
2. Drag the verified blueprint into that slot. Ingredients stay in Inventory and are handled by Neocron.
3. Detect dialog, enter 1 when needed, verify exactly one and click current OK. A single cube may transfer without a dialog.
4. Verify loaded blueprint, reacquire Start, click once.
5. Observe processing and three consecutive idle samples.
6. Built-ins require the expected output shape; custom recipes require the expected result tooltip name.
7. Count completion, decrement availability, update slots/stop rule and only then prepare another cube.

Construction count zero uses the entered available stack. Positive count cannot exceed availability. Do not retry uncertain transfers automatically. Prior results return on next Start; the final result stays in Processor.

## Slots

- Count slots is optional/off by default. For completed weapons/spells, read Free Slots and accumulate 0–5 totals.
- Unread values are separate from zero. Weapon parts without a slot field are N/A. Never invent a zero from missing text.
- Show totals/unread/N/A in Construction. Reset per batch; persist the option, not historical statistics.
- Optional Stop at N or more slots accepts N=0–5 and enables slot inspection.
- After a verified qualifying result, count only the consumed blueprint and return before loading another or pressing Start again. Leave the qualifying output in Processor.
- An unread slot value cannot meet a stopping threshold. Focus loss while inspecting still stops.

## Recycling

### Offline recipe catalog

Catalog snapshot: 201 discovered entries, including 161 primary Items DB recipes and 40 additional legacy/community entries. Some legacy names/ingredient variants overlap; the catalog labels their source status rather than claiming distinct current verified items.

Show searchable result/ingredient names, category, listed tech level, exact published ingredient quantities, source URL and retrieval date. Categories include chemicals, weapons, armor, implants, cubes, parts/upgrades, food, drugs, trophies and special items. Source retrieval date: 26 October 2026. This is not a claim of live verification or complete coverage of every event recipe.

An official Swamp Shaman Trophy note lacks exact published ingredient details. Document it separately as incomplete; do not fabricate quantities or include it as a complete executable recipe.

Sources:

- [Tech Haven recyclable items](https://db.techhaven.org/en/item-lists/recyclable)
- [Additional community recipes](https://neocron.fandom.com/wiki/Recycling_Recipes)
- [Recycling mechanics](https://wiki.techhaven.org/Recycle)
- [Official update notes](https://neocron-game.com/patch-notes)

### Prepared Processor execution

The initial executor performs one prepared run. User loads Recycling Tool in slot 1 and selected ingredients in Processor. Verify the tool's name; do not confuse a similarly drawn Salvage Device. Find current Start, click once or adopt active processing, observe progress/stable idle, verify selected output name and stop.

No automatic recycling ingredient transfers or repeated consumed inputs are implemented. Part upgrades list two lower-tier parts. Cloning is a general sample-plus-junk operation; salvage uses a different tool. General operations are documented, not falsely expanded into invented fixed recipes. Further automatic material-loading workflows require demonstrated game behavior.

## Favorites

Removed 26 Oct 2026 at the user's request (tab, buttons, favorites.py); an old profile "favorites" key is dropped on load.

## Appearance and sound

Ten selectable native skins: Basic, RPOS Classic, CronAMP 97, Dead Sector Terminal, BioLab Workstation, Fallen Circuit, Tangent Forge, Pepper Park Signal, PSI Resonance, Dome Control.

Basic preserves the light appearance. Dead Sector Terminal remains unchanged as the user's favorite. The eight other skins now use distinct code-drawn, nine-slice native panel/button/field/tab artwork, caption typography and header badges: angular RPOS, brushed CronAMP metal, BioLab enamel, Fallen Circuit traces, riveted Tangent Forge, burgundy/magenta Pepper Park neon, geometric PSI and segmented Dome controls. They preserve job data/guards and the basic control arrangement. They are not Winamp .wsz importers or Windows title-bar replacements. Selection persists. Switching back to Basic or Dead Sector restores their original widget layouts and fonts.

The interactive styling/skin-gallery.html is a separate concept board; richer concept treatments are not promises of identical native-widget rendering.

Optional stop sound is off by default. A bundled WAV plays asynchronously once for completion, chosen-slot stopping, handled failure, focus loss or application closure. Deduplicate worker termination and subsequent closure; reset on a new batch. Routine per-item completion inside an ongoing batch does not beep. Audio failure must not interfere with stopping. A hard kill/power loss cannot execute a notification.

## Detection-preview example

styling/detection-preview-concept.png is an Imagegen mockup based on the supplied screenshot. It labels the blueprint, one-unit destination and Start, and is marked CONCEPT / no actions sent. The image is not a live detector overlay or evidence of execution. A working interactive preview mode remains proposed unless separately delivered.

## Persistence and architecture

profile.json version 1 remains backward compatible. Validate ranges/types and save by temporary-file replacement. Treat profiles/catalogs as data, never executable code.

| Field | Meaning |
| --- | --- |
| operation | tech_parts / blueprints / construction / recycling |
| research_operation | Saved independent research mode |
| stacks | T/E/A/L available/requested integers |
| blueprints.count | Finite copies or zero continuous |
| construction | Recipe id, available, count, search_mode (fast/all_cells; missing=fast), count_slots, optional stop_at_slots |
| custom_recipes | Stable ids, names, alias arrays |
| hidden_recipes | Built-in recipe ids removed from Job; default empty; re-adding restores them |
| favorites | Removed; an old key is dropped on load and not written back |
| recycling.recipe | Catalog id or null until selected |
| preferences | Skin id and stop_sound boolean |
| settings | Visual positioning, bounded UI waits; drag_button/drag_modifier remain but are always saved as left/none |

Remove obsolete research-duration settings during migration. Count-zero semantics differ by mode as documented above.

Files: app.py (UI/persistence/notifications), macro_core.py (validation/input guards), vision.py (recognition), vision_runner.py (research), construction_runner.py (construction/slots), inventory_tracking.py (content-based scroll overlap), recycling.py (catalog/prepared run), construction_catalog.py (offline catalog search/validation), recipes.py (names/aliases), text_reader.py (local OCR), appearance.py and skin_chrome.py (skins/native artwork/audio), windows_backend.py (capture/input), data/recycling_recipes.json and data/construction_catalog.json (sourced facts), tools/build_portable.py (bundle checks).

## Portable runtime

Ship Python 3.12.14 x64, Tcl/Tk, NumPy 2.3.5, OpenCV 5.0.0.93, PyWinRT runtime/projections and licenses in runtime/. Windows provides the local English OCR engine/language data. No screenshots are uploaded. Destination Windows needs English OCR availability.

Launch.cmd/Launch.ps1 use only runtime/python.exe and relative local paths. No installed Python/Codex fallback. Dependency scripts verify offline. Include code, assets, data, profile, spec, checklist, ideas and styling artifacts. Exclude recordings, tests, diagnostics/logs/caches and absolute local shortcuts from the ZIP.

Extract and validate from another path with conflicting Python/Tcl environment variables and a minimal PATH. Verification must not send game input.

## Acceptance and verification

Required automated checks:

- Preserve all tech-part/item-blueprint research regressions and variable-duration/focus behavior.
- Detect real translated/scaled/overlapping Processor and movable dialog images.
- Distinguish exactly one from multi-digit quantities, reject pending inputs and avoid uncertain retries.
- Distinguish WP7/WP9; visit every cell without icon filtering and require the blueprint tooltip rather than finished-item appearance; read custom OCR names/aliases with exact-number protection.
- Use the first matching stack; find moved corner/interior source cells; bound scrolling, bottom/no-response and hidden-scrollbar cases.
- Count 0–5 slots, separate unread, stop at threshold before another transfer and retain output.
- Validate all catalog rows/quantities, search/category filters, selection persistence, correct recycling tool/result, one Start and focus loss.
- Select all ten skins without changing job data. Save/reload preferences. Test optional sound and exactly-once notifications without emitting test audio.
- Exercise UI editing/collection/custom recipes and tab independence without hardware input.
- Verify catalog statuses/source references, unsupported-method blocking, selected-name-only saving, exact/longer-name matching, no Favorites tab or drag selectors, old favorites keys dropped on load, and drags forced to plain left.
- Verify complete row-major cell coverage before scrolling, short tooltip-delay retries, stale-name rejection, current-header relocation and persistent removal/restoration of Job recipes, including an empty book.
- Verify delayed wheel consumption while the pointer stays inside Inventory, ignored-wheel scrollbar fallback, focus-loss release during thumb movement, regional capture coordinate/focus invariants and full recapture after missing headers. Native capture tests replace all desktop calls.
- Verify overlap reuse with two new rows (32 previously checked cells), changed/unresolved-cell invalidation, ambiguous/upward/blank fallback, actual 21:20 recorded row shifts, previous-stack-first re-verification, and fallback when that stack moves. Replays can combine recorded views with generated tooltip panels; they are not live game tests.
- Verify fast proposals on 21:55 views at different scales, neutral cube edge proposals, repeated builds with quantity/focus guards, explicit Thorough persistence and pending-input preflight before any inventory hover. Keep exhaustive tests explicitly in Thorough mode; separately test the Fast default with the production detector.
- Pass full regression and extracted-bundle dependency/UI checks.

Live acceptance requires the game: relocate blueprint/Processor, verify one-unit transfers and Start, try a custom recipe, compare slots/threshold against visible tooltips and prepare a recycling run. Recorded-frame replays/simulated inputs are not live tests. The current Windows Computer Use helper returned Transport closed after reset/retry; do not claim new live success without separate evidence.
