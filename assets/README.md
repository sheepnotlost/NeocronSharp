# Visual references

Processor, Inventory, Start (enabled and busy), quantity-dialog, T/E/A label, and grayscale letter templates were extracted from the user's supplied Neocron recording. The L glyph comes from the same game's HULL label; no real L stack is visible in the recording.

These templates identify the demonstrated green UI. Runtime screenshot positions are never taken from the recording. The detector finds the title plate, verifies the Start control, and derives controls relative to the current detected title and rendered scale. Inventory stack labels and the quantity dialog are located separately.

Tests use real UI crops, translated compositions, and rendered scale variants. The synthetic L stack is explicitly marked as synthetic in its test.

Quantity recognition uses `quantity_title.png` and `quantity_half.png`, cropped from the recording, plus `quantity_one.png` for exact-one verification. Opaque title text avoids the old full-dialog template's dependence on the translucent background. The user's later failure screenshot is preserved as a cropped test fixture.

Inventory recognition uses `inventory_title.png`, `inventory_max_load.png`, and `inventory_free_load.png`. Text matching avoids background-sensitive trim, and both load headers distinguish the real Inventory window from the top navigation label. `inventory_current.png` in the test fixtures comes from the user's later 2560 x 1440 game screenshot.

`progress_percent.png` is the percentage glyph cropped from the user's Weaponpart 9 blueprint recording (2026-10-24 03-07-56.mp4). Blueprint mode combines this glyph and the filled progress bar with color-independent result datacube recognition, because its prepared inputs remain in the Processor after completion. The real ready/busy/done crops are preserved in tests/fixtures/blueprint_*.png.

`processor_title.png` isolates opaque PROCESSOR lettering from the original title reference (offset 18,3 within the old plate). The detector converts it back to plate-relative coordinates and independently verifies Start before accepting any candidate. This avoids background-sensitive title trim; standalone navigation captions cannot supply a valid Processor. The actual apartment failure is preserved in tests/fixtures/processor_apartment.png.

`processor_overlap_busy.png` and `processor_overlap_done.png` in tests/fixtures preserve the later failure after Processor moved over Inventory. Slight rasterization changes require antialias-normalized matching with ±1px dimensions for both title lettering and Start. No per-location reference or calibration is used.

`blueprint_cube.png` is the datacube crop from the original recorded red result. Runtime recognition compares grayscale gradient shape, so it also recognizes green, blue, cyan, and neutral-colored blueprints. `tests/fixtures/blueprint_green_done.png` preserves the actual different-item green-result failure screenshot, cropped to the Processor. Its original rendered scale is 4/3. The green-result replay replaces only the result region of the moving-window replay; its processing stage is simulated.


Construction references come from the supplied Weaponpart 7 and Holy Heal videos. `construction_tool.png` identifies the constructor icon even while it is dimmed during processing. `empty_datacube.png` and `loaded_blueprint_red/green.png` distinguish a used cube from a blueprint waiting to run. `constructed_weaponpart.png` and `constructed_holy_heal.png` verify products by their rendered shape. Tooltip prefix/name templates distinguish BLUEPRINT from used cubes and select Weaponparts 7/9 or Holy Heal. The Weaponpart 9 tooltip is from the earlier supplied blueprint research video. The game handles all ingredient quantities; none are inferred from the recipe screenshots.

Test fixtures preserve ready/busy/completed Processor crops, both Inventory/tooltip displays, a WP9 tooltip, and actual quantity dialogs including 1 and 27. Quantity fallback refines a half-resolution title proposal and excludes numeric-field borders before verifying the single digit 1 at multiple antialias thresholds.

`tests/fixtures/construction_scan_*.png` preserve Inventory at 8.5, 9, 9.5, and 26 seconds of `2026-10-26 15-06-38.mp4`. The first three show the same two blueprint stacks with no tooltip, the Weaponpart 7 tooltip, and the Holy Heal blueprint tooltip; the last shows the lower inventory rows with finished Holy Heals. These detect the fractional-scale WP7/WP9 ambiguity and exclude finished-spell halves from cube proposals. The hover replay composes these recorded crops with the earlier ready Processor reference and simulates cursor positions; it does not run a live build.
