# NeocronSharp — active request tracker

Updated 2026-10-27. Source: this chat. User additions extend the same task.

## Implementation and fixes

### Nav-Ray look-ahead and sharper corners — 28 October 2026

- [x] Trace the dashed line far ahead (dash by dash past the straight chain, small far marks included) and find the first corner in it. Checked on the 02-29-32 video: the far turns at 22–25 s and the right turn at the end of the City Admin corridor (36–38 s) are traced.
- [x] At a close corner, steer for the way beyond it and pivot sharply (stop forward motion above 0.10, full correction); a line running across the view close by is a turn onto its far end. On the video, 38.2 s now steers +0.24 where the old run walked on into the wall.
- [x] Ride out a dropout of up to 0.4 s on a straight stretch; after a pivot, look at the whole view when the old line's tube shows nothing. Not yet checked live.

### NeocronSharp merge — 28 October 2026

- [x] Merge the C# NeocronSharp app (tracker/sector map, coordinate recorder, point navigation, loot, environment, quests, plugins) into `NeocronSharp/`, unchanged in features; open it from a new Tracker & Map tab, Open NPC Tracker.cmd or Open Coordinate Recorder.cmd.
- [x] Fix its game-client lookup for the merged folder; build the example plugins from the solution. 100 C# tests, 318 Python tests and the UI smoke check pass.
- [x] Rename the project, docs and GitHub repository to NeocronSharp (https://github.com/sheepnotlost/NeocronSharp).
- [x] Show NeocronSharp's Tracker, Quests and Plugins pages inside the suite as its own tabs (replacing Tracker & Map): one `--embedded` process re-parented into the selected tab, following its size; the suite's tab follows NeocronSharp's own page changes (NPC quests); the window grows to fit; recorder, point navigation and Build sit in the Tracker tab's bar. Verified live with screenshots of all three pages (52 NPCs read in Plaza 1).
- [x] Loot library is its own page and suite tab, next to Quests (loads the game's loot definitions the first time it opens); the tracker's Loot library button opens that tab on the tracked NPC. Not yet checked live.

### Research text wrapping and resizable activity log — 27 October 2026

- [x] Fix the unweighted paragraph grid that collapsed Research sequence settings to one character per line, including after maximization/skin changes.
- [x] Add a visible drag handle/divider to enlarge or shrink the bottom Activity log, with a vertical scrollbar; retain Start and tabs in the upper pane.
- [x] Verify actual Tk geometry across all 10 skins at 960×800, 1040×840 and 2560×1390, divider resizing across all four tabs, read-only log scrolling and Start visibility. All 184 suite tests pass; extracted portable OCR/dependency/UI startup checks pass. No game input was sent. Final checklist-only repack preserves the verified application/runtime.

### Tech Counter integration — 27 October 2026

- [x] Embed the standalone counter as a Tech Counter tab using the suite's skins.
- [x] Retain cabinet/inventory selection, all-items/techs-only filters, scroll/hover counting, stack quantities and rare-set completion (86 entries).
- [x] Retain lists, scan editing/manual entries, undo, locations and clipboard/CSV/TXT/JSON exports.
- [x] Share Start in 3 seconds, one worker, focus/identity/size guards and optional stop tone. No additional hotkeys or Stop button.
- [x] Copy existing lists/names/config without changing standalone files or overwriting suite state; provide folder import and exclude user data from Git/downloads.
- [x] Include Tesseract, English model and Python OCR dependencies in the local runtime.
- [x] Pass all 181 suite/integration tests and 51 imported pure-logic counter tests. These use fake input/data and do not establish live game behavior.
- [x] Complete extracted portable dependency/OCR/UI checks with external Python/Tesseract paths unavailable. The 92.9 MiB portable passes a real OCR probe and UI startup; no game input was sent. Imported JSON copies match the standalone originals byte for byte. Final documentation-only repack preserves the verified code/runtime.

### Previously delivered

- [x] Rename the app/folder/portable bundle to Neocron Macro Suite.
- [x] Research and Construction tabs; preserve T/E/A/L and item-to-blueprint research.
- [x] No macro hotkeys or Stop button; Start in 3 seconds, stop on game focus loss.
- [x] Re-detect Processor, Start, quantity dialog, Inventory, and source cells; no calibration.
- [x] Construction transfers one verified blueprint, verifies quantity 1, then clicks freshly detected Start. Ingredients remain game-managed.
- [x] Scroll down through Inventory when the selected blueprint is absent.
- [x] Faster search: use first verified matching stack; stop hovering over unrelated stacks.
- [x] Native-resolution filtering for finished Holy Heal icons; normalize tooltip text and read names locally with OCR.
- [x] Support user-saved construction recipes and shorthand/aliases without Codex.
- [x] Optional 0–5 slot counter; distinguish unread from zero; reset per batch.
- [x] Stop at a chosen minimum slot count, before another blueprint is transferred.
- [x] Recycling tab: 201 sourced entries, source status/links, preparation instructions and one prepared run. Published incomplete recipes are identified separately.
- [x] 10 selectable skins in the actual application, including its existing Basic style.
- [x] Optional sound when a batch/program stops for completion, focus loss, errors, or closure.
- [x] Final integrated regression (128 tests), UI and portable relocation checks; rebuilt downloadable bundle with all dependencies, data, skins and docs.

## Styling, examples, documentation, and ideas

- [x] Research Neocron crafting/research/recycling to inform feature suggestions.
- [x] Provide additional feature ideas in the chat.
- [x] Create 10 skin designs including Basic in styling/skin-gallery.html; render/select all ten and verify desktop/mobile layout.
- [x] Produce and show the detection-preview photo concept; correct the Start callout; save in styling/detection-preview-concept.png.
- [x] Provide the thorough consolidated SPEC-SHEET.md, retaining SPEC.md as earlier notes.
- [x] Save sourced FEATURE-IDEAS.md and distinguish implemented features from proposed ones.

## Skin refinement requested after initial delivery

- [x] Preserve Dead Sector Terminal, the user's favorite, and retain Basic as the original light style.
- [x] Give the eight other skins distinct native panel/button/field/tab artwork, typography and header badges.
- [x] Change Pepper Park Signal to a burgundy/magenta styling direction.
- [x] Reuse the actual native chrome artwork in the offline gallery and refresh all ten previews.
- [x] Pass skin-switching/state-preservation checks, including restoring Dead Sector's original layouts/fonts.
- [x] Rebuild and relocation-check the portable bundle containing the revised skins.

## Construction catalog and Favorites requested after skin refinement

- [x] Add a broad searchable construction catalog with 1,263 sourced item entries and clear build-method status; avoid claiming every item has a verified blueprint recipe.
- [x] Keep the running macro's recognition set limited to saved/selected recipes, avoiding a slower scan across the whole browse catalog.
- [x] Add a Favorites tab for saved construction and recycling recipe shortcuts, with persistent add/remove and one-click loading.
- [x] Update docs/spec and verify catalog selection, favorites persistence, and the rebuilt portable bundle.
- [x] Brainstorm broader Neocron companion-suite features beyond tradeskills; record proposals in FEATURE-IDEAS.md.
- Note (26 Oct 2026): Favorites and the Drag button / Drag modifier selectors were later removed at the user's request. Profiles with an old "favorites" key load and drop it; drags are always plain left drags. See "UI trim and quick debug — 26 Oct".

## Inventory sweep and Job recipe removal — 20:13 recording

- [x] Review supplied recording and replace icon-filtered construction search with every-cell hovering.
- [x] Visit visible cells rapidly in row order, show row/page progress, scroll downward after a full unsuccessful page, and re-detect moved Inventory/Processor.
- [x] Clear/re-hover a matching blueprint before transferring one; unreadable names never authorize a transfer.
- [x] Add Remove recipe to Job, persist custom deletion/built-in hiding, remove related Favorites, and support re-adding/empty Job lists.
- [x] Complete integrated regression (142 tests) and rebuild/extract-check portable download.

## Scrolling and search speed — 21:02 recording

- [x] Review video/log showing roughly 19-second initial sweep and an unconsumed wheel event.
- [x] Retain pointer inside Inventory through wheel handling; retry once and verify advancement.
- [x] Add tiny detected-thumb drag fallback for ignored wheel input, with bounded attempts/focus release.
- [x] Reduce per-hover capture area, retain full-size focus guards/full-capture relocation, and shorten scan waits/resets.
- [x] Run integrated regression (147 tests) and rebuild/extract-check updated portable package.

## Overlapping rows and rapid search — 21:20 recording

- [x] Review recording/log: repeated overlapping-row scans and a fresh scan before the next build.
- [x] Track content-proven scroll displacement; reuse checked overlap and scan new/changed/unresolved cells.
- [x] Verify the last source cell first on following builds using newly detected Inventory and fresh tooltip checks.
- [x] Reject unrelated tooltip panels on one read, reduce empty-cell retries and redundant per-page quantity searches.
- [x] Complete integrated regression (153 tests), final focused replay checks, and portable extraction checks for this update.

## Fast visual search and Claude handoff — 21:55 recording

- [x] Review latest recording/log showing incomplete overlap reuse and a pending Processor input.
- [x] Make Fast datacube proposals the default; hover possible cubes, verify names and scroll without the 48-cell sweep.
- [x] Keep Thorough every-cell search as an explicit saved fallback; preserve fresh-location/name/quantity guards.
- [x] Preflight pending/busy Processor state before wasting a search; retain used cubes/previous results.
- [x] Finish regression (159 tests) and portable package checks for the new default.
- [x] Save CLAUDE-HANDOFF.md and CLAUDE-PROMPT.txt, include them in the bundle, and supply the handoff prompt.

## First live Fast measurements and follow-up speedups — 2026-10-26 evening

- [x] Run Fast live (headless harness using the app's ConstructionRunner/WindowsBackend, one profile copy, 1–2 builds of Weaponpart 7). First live Fast evidence: macro.log through 21:57 shows all earlier recordings used the old every-cell sweep.
- [x] Measured: cold search from the top of Inventory 5.3–5.9 s over 3 views (earlier every-cell runs 17–35 s); second build's previous-stack check 1.2–1.4 s; transfer + dialog + Start about 2.4 s; game build about 10 s.
- [x] Reuse the last known Inventory position (cheap header check, full relocation on failure) between pages, scrolls and builds.
- [x] Sample the quantity-dialog search every 4th build poll and always before accepting completion (about 150 ms per call).
- [x] Reaching the true bottom reports the normal bottom message instead of "scrollbar moved unexpectedly upward".
- [ ] Not done: Fast hovers false proposals (a 2-cell picture item) about 0.4 s each with no tooltip; transfer phase still re-detects the quantity dialog several times; search starts at the current scroll position and does not wrap (scroll to the top first).

## Weaponpart 9 live miss — 26 Oct evening

- [x] Diagnose from one captured frame: the tooltip reader's 4 px right-edge trim clipped the final "9", so OCR read "Weaponpart" and the exact-number rule rejected it. Fast and Thorough both missed the stack (Thorough scan over 9 pages found nothing); it was not an icon-filter problem.
- [x] Retry with shorter trims (3, 2 px) only when the words match a numbered recipe but no digit was read; wrong/extra digits ("91") still fail. Regression tests use the captured 2560x1440 frame (tests/fixtures/live_wp9_tooltip_2560.png, replay only).
- [x] Live: the Fast search found WP9 in about 5 s and the transfer reached Start. The first attempt stopped safely because the split dialog showed 551 (Ctrl+A did not replace the default 55).
- [x] Clear the quantity field with Backspace/Delete before typing 1; live run then verified quantity 1, clicked Start and followed the build. That run ended on a focus loss while building, and the user lacked ingredients, so a completed WP9 build is not verified.
- [x] 161 automated tests pass.

## UI trim and quick debug — 26 Oct

- [x] Remove the Drag button / Drag modifier selectors from Research Sequence settings and Construction Transfer controls; Start always saves a plain left drag (left/none).
- [x] Remove Favorites (tab, Favorite buttons, favorites.py, recipe-removal hook, build manifest entry); old profile "favorites" keys are dropped on load. Only the construction Catalog page now disables Start.
- [x] Reduce Construction "Prepare in Neocron" to minimal bullets (Inventory scrolled to top; search runs downward; ingredients untouched; stop by switching away).
- [x] Quick debug: 4 review lenses, each finding attacked by 3 independent skeptics; 7 of 9 survived (2 were the stale ZIP). Fixed:
  - High: the WP7/WP9 pixel template could accept a different part number (a "3" scored .97 against WP9). It now verifies the final digit alone (recorded 7/9 ≥ .92; other digits ≤ .63; threshold .80). A clearly read conflicting OCR number never authorizes.
  - Medium: a custom "Weaponpart N" was vetoed by the WP9 template; now accepted when OCR reads its exact number.
  - Medium: "Add / update recipe" typed as a shorthand renamed the recipe to that shorthand; the full item name is now kept and the shorthand merged into aliases.
  - Low: a 1–3 px window drift after anchor reuse could make the thumb fallback report a false bottom; it re-baselines on the fresh anchor.
  - Low: an old saved right-button/modifier drag stayed in profile.json until Start; it is normalized on load.
- [x] 168 automated tests pass (replay/simulation, not live). The scroll-drift test fails on the pre-fix runner.

## Cut-off text/layout — 27 Oct

- [x] Replace fixed paragraph widths with wrapping based on each label's allocated width, across Job/instructions, Research, catalog/recycling details and status text.
- [x] Make construction columns/recipe/alias/search fields flexible; wrap the slot-stop explanation inside its row.
- [x] Verify 30 hidden-Tk geometry combinations (ten skins × three widths), 20 existing targeted checks and the UI smoke check. No game input sent; no gameplay logic changed.
- [x] Rebuild and extraction-check the portable download; extracted dependency/UI checks pass with conflicting external Python/Tcl settings and a minimal PATH. Final checklist-only repack preserves tested app/data.

## GitHub source repository — 27 Oct

- [x] Initialize local Git and create private repository https://github.com/sheepnotlost/neocron-macro-suite with main as the source branch.
- [x] Exclude personal profiles, logs, diagnostics, recordings, runtime, portable ZIP and local shortcuts; check source files for common credential patterns.
- [x] Document how to run a source checkout using the portable runtime. Repository publication is tracked by the main branch/remote commit, not the older portable ZIP.

## Any resolution, windowed play — 27 Oct

- [x] Diagnose the windowed 1920x1080 failure from diagnostics/latest.png: the UI rendered at layout ~.80 (Processor) / ~.78 (Inventory) with title fonts at ~.91, between the reference scales (.75/1.0). Every detector failed, then retried silently for ~45 s ("does nothing").
- [x] Detect the Processor at any scale (.6x–2.2x) with a dense half-resolution title scan; resolve its layout scale separately from the Start button when title and layout differ.
- [x] Detect the Inventory at any scale; fit its origin and scale from the 8x6 cell grid (titles/labels only propose). Hot-path re-checks of such windows use the grid.
- [x] Scale-independent cube classification (gray used cube / red / green) when icon bitmaps do not match; tooltip text scale adapts when fonts are not proportional.
- [x] Status line now says what is being searched for and the game-view size when the Processor is not found.
- [x] 190 tests incl. the cropped windowed frame and intermediate scales .8–1.8 (replay, not live).
- [x] Windowed test 27 Oct 03:47: Fast hovered the two cube cells but never read the Weaponpart 9 tooltip. Cause: tooltip text sits at layout scale (.80) where the shipped BLUEPRINT prefix correlates only .60 (< .74 gate), so it was rejected as an unrelated item. Fixed: fine text-scale scan when a tooltip panel is present, provisional accept (>= .52) only if the OCR line reads as BLUEPRINT; scale remembered. Regression test uses the user's real capture.
- [x] Windowed retest 27 Oct 04:05: the macro hovered the right cube but read no tooltip. A hover-only live capture showed the tooltip on screen; cause: once Processor detection set the heading ratio, the text-scale search chose a finer scale whose black-box test fails, so the tooltip returned None. Panel presence is now tested at several normalizations; the real hover capture reads Weaponpart 9 and is a regression fixture.
- [x] Windowed retest 04:17: found and dragged the stack, then stopped: the quantity dialog was on screen (already 1) but undetected. The dialog is its own window at its own scale (.77 vs Processor .80). Added a dense dialog search used when a dialog is expected; the scale is remembered. Regression test uses the real capture.
- [ ] Not verified live at the windowed size: tooltip reading, quantity dialog and a full build. Scales below ~.7 and above ~2.1 are unreliable.

## Release prep — 27 Oct

- [x] Scrub personal Windows paths (user folder, recordings folder) from tracked docs; commit identity is the GitHub noreply address.
- [x] Add five media-player inspired skins with original code-drawn art: Graphite LCD, Spectrum Bars, Chrome Equalizer, Neon Visualizer, Shade Mode. 194 tests pass.
- [x] Commit and push to GitHub on a branch.

## More Materials in GoGo — 27 Oct

- [x] Optional Construction checkbox (saved as construction.gogo_refill, default off). Built-in recipes only (material labels known: WP7 TRS/MET/ARI/SOL; WP9 GAM/MET/SOL/STS/TIB).
- [x] Trigger: with the option on, a Start that never turns busy for 5 s while the blueprint stays loaded counts as refused (missing materials). The macro then refills and presses Start again, at most twice per build.
- [x] GoGuardian is located from its "Take All / Sort / Stack" strip by local OCR at any scale; stacks are read by their 3-letter label. Up to 15 of each needed ingredient are dragged into Inventory (onto the same stack when present, else the first empty cell). The quantity dialog reopens at the last quantity entered (not the full stack), so 15 is always typed and read back before Ok; a smaller number shown means the game clamped it to a smaller stack.
- [x] The GoGuardian window must be open beside Inventory and Processor. 202 tests incl. two real captures.
- [ ] Not verified live: the GoGuardian drags, quantity entry above 1, and the refused-start trigger. Stack counts (xN) on the live capture could not be read by OCR.

- [x] Fullscreen 2560x1440 at UI scale ~1.02 (27 Oct 05:49): the macro hovered the blueprint but never proceeded. The cheap Inventory re-check used template correlation that fails between reference scales, so every hover looked like a moved window and the page restarted. Grid-fitted windows now keep their grid-based re-check at any scale. Regression test uses the real capture.

- [x] Removed the "Blueprints in stack" field. Build = 0 now runs until no blueprint can be found (the batch then ends as "Out of ... blueprints", not an error, once at least one build finished). Internally the stack is saved as 10000 = unknown; a lone-item stack that transfers without a dialog is accepted when the blueprint is visibly loaded.

- [x] Interface trimmed (27 Oct): removed the "Prepare in Neocron" panel, the Research detection/sequence/start-and-stop explainer panels, recipe ingredient and catalog paragraphs, the recycling explainer and the source/retrieval boilerplate. Remaining static labels are one short line each; a test guards against wordy labels returning.

## Recipe materials from the web — 27 Oct

- [x] Per-recipe Materials row (Name=LABEL), saved in the profile, used by GoGuardian refills; Holy Heal added to the built-in table.
- [x] `tools/fetch_recipes.py` written; item pages expose "Parts:"; tested on 12 items.
- [x] Default labels guessed from catalog parts (`gogo.default_code`).
- [x] Full fetch done: 478/1,263 items list Parts; WP7, WP9 and Holy Heal match the built-ins; tests updated; Catalog shows parts; Materials row prefills from them; data committed.
- [ ] Not verified live: GoGuardian refills for any recipe beyond Weaponpart 9; Holy Heal labels W5/W4/W1 are inferred.

- [x] GoGuardian labels no longer depend on the window's contents (27 Oct): when an expected label is not among the stacks read, the macro hovers the most likely stacks (labels that abbreviate the missing name), reads the tooltip name, and saves name->label in the profile and Materials row. Failure messages list the labels seen. 223 tests incl. synthetic tooltips.
- [ ] Not verified live: the GoGuardian tooltip's real appearance (assumed a black, light-bordered panel containing the item name). If it differs, hovering finds no name and the run stops with the labels seen.

## Nav-Ray auto-walk — 27 Oct

- [x] New Nav-Ray tab: `Category > Destination` (e.g. Faction HQs > Black Dragon). The macro finds the open Nav-Ray window (any scale), picks the category and destination (scrolling the lists), presses Start, waits for the dashed path, presses Tab for mouse-look and walks: holds W and steers with relative mouse motion toward the dashes.
- [x] Stops with a reason: no path found, path ended (reported as arrived/lost), not moving, health dropped, loading screen, longer than 10 minutes, game focus lost. Keys are always released.
- [x] Design spec and plan in docs/superpowers/. 244 tests pass (path detection on the user's real stairs/hall frames; Nav-Ray window and list reading on three real captures at two UI scales; walk loop with a fake backend).
- [x] Destination lists: Category and Destination dropdowns filled from data/navray_destinations.json (23 categories, 239 destinations), compiled by hand from the user's screenshots on 27 Oct. The game cuts long names short, so repeated labels are numbered ("... #2") and picked by position. Unverified counts: Pepper Park Apartments (Complex 1 = 6, Complex 2 = 9, estimated) and Outzone Dungeons (may miss 1-2 rows). "Read lists from Nav-Ray" (tools/scan_navray.py does the same from the command line) refreshes them from the game; list rows are read with Tesseract (exact on a real 2560x1440 frame). Live scans were interrupted three times (misread name; user pause; focus lost), so a full live scan has not completed. 252 tests pass.
- [x] Nav-Ray lists now scroll by dragging their own scroll thumb (the wheel jumped too far in the small window and skipped rows): the thumb is found by pixels, drag distance = rows x thumb length / visible rows, the distance actually moved is measured from the thumb, pages overlap by two rows. Thumb detection checked on four real captures at two scales; the drag itself is unverified live.
- [ ] Not verified live: Start, Tab returning to mouse-look, steering direction/gain, arrival, stuck and health detection, speed. Tuning constants are at the top of navray_runner.py. Doors, subway, loading screens and combat are out of scope (the walk stops).

- [x] Route library (27 Oct): every finished Nav-Ray walk records its start area (HUD Location, read by OCR), end area, time and legs in routes.json (user data, git-ignored); the best walk of a route is kept, a known route is reported and its first turn sets which way the first sweep looks. tools/route_map.py lists the areas reached from each area. The game's own pak_worldroute.dat decompresses (zlib after a 16-byte header, 478 entries, mixed record types) but is not decoded. 281 tests pass.
- [ ] Not verified live: Location reading during a real walk, saving the library, the sweep hint.

- [x] Dash colour (27 Oct): the Nav-Ray dashes take the HUD colour scheme (`/set gfx_hudcolor <x>`, schemes in the game's ini/rposcolor.ini; the user switched to a red scheme and the dashes turned red). pathvision now finds green or red dashes and the macro locks onto whichever colour shows a path; red is far easier to tell from green walls and signs. Red detection is verified only on real green frames recoloured red (no real red frame is saved), so the red thresholds are untuned.

- [x] Every Nav-Ray run records itself (27 Oct): each status line is saved with the game frame at that moment and the macro's state (diagnostics/last_run/, replaced by the next run, git-ignored). tools/review_run.py summarises it (legs by outcome, colour, calibration) and builds failures.png of the scenes where the walk got stuck or lost the dashes. Purpose: turn every failed run, including the user's own from the app, into test cases and tuning data instead of discarding it. Nothing in the macro adapts by itself yet.

- [x] First live success (27 Oct 22:10, video + log, default green skin): Trader Directory > Weapons walked from Plaza start into the Archer & Wesson shop in about 35 s, the HUD colour read as hue 70, three legs (one 10 s tether leg), then a full sweep found no more dashes and it reported arrival. This is ONE run. The fixes that preceded it, each found from videos of earlier failed runs: dash colour read from the HUD (not learned from signs), text/label rows rejected, stuck detection across legs, dashes no longer discarded after every turn, far dash rows accepted. Still to confirm: that it repeats, other destinations, the red skin after the latest changes, and arrival detection (it sweeps all round for ~6 s before stopping).

## Nav-Ray pale-tile turn loss — 27 Oct, 22:24 recording

- [x] Review `2026-10-27 22-24-13.mp4` against macro.log and diagnostics/last_run. The walk reached the tiled bend, repeatedly lost visible dashes after turning, and stopped at 22:25:19 with "turning does not line the dashes up". This run did not reach the destination.
- [x] Exact video frames at 52.7s and 63.9s: near-centre floor dashes were removed by the character exclusion box and the saturation cutoff (measured saturation 43-58 on pale tiles). Keep clear elongated dashes in that box; allow faint floor dashes only with measured contrast of at least 16, retaining hue/chain/clutter checks.
- [x] Add both real frames as regression fixtures, checked at 1280/1920/2560 widths, plus the runner's standing evaluation of the aligned post-turn frame. Existing wall/sign/gear rejection fixtures remain covered.
- [x] All 70 focused tests pass: `runtime\python.exe -m unittest tests.test_pathvision tests.test_navray tests.test_navray_runner tests.test_routes`. OCR checks needed access outside the sandbox; no Tk windows or game input. Full suite and portable ZIP were not run.
- [ ] The revised detector has not been tested in a new live walk. Arrival remains ambiguous; zone changes/doors remain unsupported.

## Nav-Ray obstacle and door recovery — 27 Oct, 23:07 and 23:11 recordings

- [x] Matched the two recordings to macro.log. The Pepper Park walk ran against an obstacle for about 30 seconds; the Viarosso walk repeatedly swept for the path and then ran against a closed TECH DOOR. Both were stopped by focus loss, not successful arrivals.
- [x] Detect lack of progress from background scenes over several seconds, aligning modest camera movement and ignoring the player and floor overlays. Do not count an intentional in-place turn as walking. Keep the existing short-term stillness check and bounded back-off recovery.
- [x] When blocked, identify a targeted door using the real TECH DOOR label or OCR of a DOOR label, then send a guarded right-click in mouse-look, release it even on interruption, and look for the route again. A retry cooldown avoids immediately toggling a door. If no door is identified, use the existing back-off recovery.
- [x] Add real recorded moving and blocked frames from both runs, and tests for recovery, door recognition at multiple scales, right-click, focus-loss release, and cooldown.
- [x] All 80 focused tests pass: `runtime\python.exe -m unittest tests.test_pathvision tests.test_navray tests.test_navray_runner tests.test_routes`. No Tk windows or game input; full suite and ZIP were not run.
- [ ] Live verification is still needed for obstacle recovery, right-click interaction, other door labels/colours and following the path through an opened door. Unlabeled doors and sector transitions are not established.

## Validation truth

Saved game frames, OCR, simulated backend sequences, and UI/config tests have been used. No assistant-driven live game run is verified for these new changes. The Windows Computer Use helper currently returns `Transport closed`, including after reset/retry. Do not describe replayed tests or concept images as live game verification.

Live note (26 Oct evening): Fast was exercised live through a headless harness at 2560x1440 (3 builds total); timings are in the section above. Other features were not re-run live. 159 automated tests still pass after the speedups.

128 automated Python tests passed after the integrated feature changes. The separate concept-gallery render/selection checks pass for ten skins and desktop/mobile viewports. The extracted portable bundle passes dependency and UI checks with conflicting Python/Tcl environment variables and a minimal Windows-only PATH. The final doc-only repack updates this completed checklist without changing the tested application files.

Latest skin refinement: 12 focused suite/UI checks pass, including exact layout/font restoration for Dead Sector. The refreshed ten-skin gallery passes desktop/mobile rendering and selection checks. The revised portable bundle passes extracted dependency/UI verification; the final checklist-only repack preserves the tested application contents.

Latest catalog/Favorites update: all 135 automated Python tests pass, including selected-recipe-only catalog loading, unsupported-method blocking, longer-name matching, persistent shortcuts and unchanged batch counts. The rebuilt portable bundle passes extracted dependency/UI checks with conflicting external Python/Tcl settings and a minimal PATH. No game input was sent. A final checklist-only repack preserves the tested application/data contents.

Latest inventory sweep/removal update: all 142 automated tests pass. These include full cell coverage on the latest recorded Inventory, row-major visitation before scrolling, delayed-tooltip retries, stale-name rejection, moved-header localization and persisted removal/restoration of Job entries. The extracted portable bundle passes dependency/UI checks with conflicting external settings and a minimal PATH. No game input was sent; this is offline verification. The final checklist-only repack preserves the tested code and data.

Latest scroll/speed update: all 147 automated tests pass. Delayed wheel consumption, ignored-wheel thumb fallback, focus-loss release, regional capture guards and full recapture are covered without live desktop calls. Hover capture area averages 24.3% of full client pixels for the recorded layout; that is a pixel-area measurement, not a measured in-game speedup. The updated extracted portable passes dependency/UI checks with conflicting external settings and a minimal PATH. The Windows Computer Use helper again returned Transport closed, including reset; no new live game verification is claimed. Final checklist-only repack preserves tested code/data.

Latest overlap/rapid-search update: 153 automated tests pass, followed by the six focused tracking/replay tests after final relocation-state guards. Recorded Inventory comparisons establish actual downward row shifts; tests cover 32-cell overlap reuse for two new rows, changed/unresolved cells, ambiguous/upward fallback, a blueprint unread in a previous bottom row, previous-stack-first re-verification and moved-stack fallback. Production replay mixes recorded views/tooltips with generated unrelated panels; it is not a live speed measurement. The updated extracted portable includes inventory_tracking.py and passes dependency/UI checks. No new game input was sent. The final checklist-only repack preserves tested application/data contents.

Latest Fast default/handoff update: all 159 automated tests pass. Fast proposals are checked against the 21:55 views at multiple scales, including neutral cube shape proposals; repeated builds, preflight and the saved Thorough fallback pass. The production-detector Fast replay checks at most 12 distinct candidate cells over four recorded views rather than the exhaustive 48-cell initial page. This is offline evidence, not a measured live speedup. The extracted ZIP passes dependency/UI checks and includes both Claude handoff files. Final checklist-only repack preserves tested application/data/brief contents.
