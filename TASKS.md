# Neocron Macro Suite — active request tracker

Updated 2026-10-27. Source: this chat. User additions extend the same task.

## Implementation and fixes

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
