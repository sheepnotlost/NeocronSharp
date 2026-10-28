# NeocronSharp

The current consolidated specification is **SPEC-SHEET.md**. This file retains earlier detailed implementation notes; where behavior changed, use the consolidated sheet and TASKS.md.

## Objective

Support two research operations: identify user-selected quantities of T/E/A/L parts in order, or research a prepared item repeatedly into blueprints. User requires automatic control detection with no coordinate calibration because the Processor periodically moves to random locations. The demonstrated green UI is the visual reference.

Current setup supplied by user: 2560 x 1440, borderless fullscreen, UI scale 1.7.

## Confirmed workflow

- Keep the research tool in the first Processor slot.
- Detect Processor, Inventory, and the requested visible stack afresh before each cycle.
- Inventory uses opaque caption text plus independently verified Max Load and Free Load; it does not depend on translucent trim or accept the navigation label alone.
- Transfer one unidentified tech part into input slot 2.
- Find the quantity dialog wherever it appears and confirm one unit. A single-item stack may transfer without that dialog.
- Match opaque quantity title text and the Half control; visually verify that the field contains exactly 1 before clicking OK. Do not retype a correctly displayed 1.
- Find the Processor again and activate its current Start control.
- Follow the Processor visually while waiting for its input to clear.
- Research is monitor-only: no per-part duration, fixed research wait, minimum research duration, or research time limit. Remove old timing settings from saved profiles automatically.
- A new research Start automatically returns the previous result to Inventory. Never click the result area between cycles.
- Leave the final result in the Processor; do not trigger an extra run to collect it.

## Tech stack and commands

Python 3, Tkinter, ctypes Windows APIs, NumPy, and OpenCV. Requirements are pinned in `requirements.txt`; the optional installer targets the workspace's `.deps` directory. Bundled Python/NumPy and the locally installed OpenCV are used on this computer.

- Launch: `python app.py`, or `Launch.cmd`.
- Validate saved counts/settings without game input: `python app.py --check`.
- UI smoke check without input: `python app.py --smoke-ui`.
- Tests: `python -m unittest discover -s tests -v`.
- Compile: `python -m compileall -q app.py macro_core.py windows_backend.py vision.py vision_runner.py`.

## Project structure

- `app.py`: counts, settings, status, automatic binding, and a single three-second Start control.
- `vision.py`: shipped-artwork matching, translated/scaled controls, stack labels, and item appearance.
- `vision_runner.py`: visually located research workflow.
- `macro_core.py`: settings, input primitives, interruption, and retained legacy simulation engine.
- `windows_backend.py`: native screenshot capture, input, and focus checks. No global hotkeys are registered.
- `assets/`: UI artwork extracted from the supplied recording.
- `tests/`: real UI crops, translated/scaled scenes, and simulated research state.
- `profile.json`: saved counts/settings; the app ignores old coordinate calibration.
- `README.md`, `WORKFLOW.md`, `AUTO-DETECTION.md`: operation, source observations, and behavior/limits.

## Code style

Use descriptive control names and explicit timing units. Separate screen recognition from input delivery. Match opaque Processor title lettering and independently verify Start before accepting a candidate; do not depend on translucent title trim or infer controls from a single pixel.

```python
frame = self.frame()
processor = self.detector.processor(frame, checkpoint=self.guard)
start_point = processor.point(421, 174)
```

Offsets are relative to the current detected Processor artwork and its rendered scale; the frame's absolute Processor position is never persisted as a fallback.

## Testing strategy

- Simulate T/E/A/L, automatic previous-result return, single-item transfer, stop/pause/focus loss, and arbitrarily different research durations.
- Regress the user's actual missed-dialog screenshot at its rendered scale, including detecting 1 and rejecting 11.
- Verify Inventory and T/E/A positions on the actual current-rendering crop, after relocation and trim changes; reject missing headers and duplicate Inventory windows. Save bounded local failure diagnostics without recapturing other apps.
- Simulate Processor relocation between every completed run and independent quantity-dialog movement.
- Verify shipped templates on actual recording crops, including the two Processor positions.
- Compose recorded UI at random locations on 2560 x 1440 frames and test rendered scale variants including 1.7.
- Test missing/ambiguous Processor, hidden Start, occupied input, duplicate source stacks, and synthetic L recognition.
- Smoke-check the panel and compile all production modules.

## Boundaries

- Always: capture and recognize the current UI before input; stop on focus loss or ambiguity; bound research counts and waits; release held input on interruption.
- Never: use old control positions after a failed search, treat a missing window as an empty input, retry an uncertain transfer, or start an extra run to collect the final result.
- Require visible Processor/Inventory controls and one visible source stack per requested type. Item success/failure messages, actual stack counts, fluid supply, free inventory space, and tool condition are not automatically read.

## Success criteria

- All four stack types are configurable, with zero skipping a type.
- Start in 3 seconds is the only action button; no hotkeys or visible Stop control.
- Focus loss stops the batch without automatic resume; closing cancels pending work.
- The enhanced transparent research-tool image supplies the app and launcher icons.
- No manual coordinate or empty-reference capture is needed.
- Moving Processor between runs causes detection of its new position.
- Moving the quantity dialog does not require saved dialog coordinates.
- Every Start uses a current Processor match with a recognized control.
- Missing, obscured, clipped, or ambiguous controls stop with no stale-coordinate input.
- The last result remains in the Processor, and normal count/stop behavior is preserved.

## Live verification

The user confirmed successful live operation before the controls were simplified. Automated checks cover focus loss before input and during monitor-only research, as well as visual detection and relocation.

## Item-to-blueprint option

- Select Item → blueprint and a per-batch copy count. Zero means repeat until focus loss or app closure. The saved finite count remains the batch size for the next launch; status reports copies remaining in the current batch.
- User prepares the research tool, item, and empty datacubes in game, following the Weaponpart 9 recording. No Inventory detection, dragging, quantity entry, or output collection is performed in this mode.
- Locate and verify the current Processor and Start on every observation. Verify the current idle state once before the first click, and adopt an already processing run without clicking Start again. After completion, re-verify the current location once without repeating the idle-confirmation loop.
- Click Start once, then require observed research progress followed by three consecutive idle observations and a visible blueprint datacube recognized by shape independently of its color. A pre-existing result alone never completes a new attempt.
- Read the percentage indicator and filled progress bar; never use elapsed research time or input-slot clearing to decide blueprint completion.
- Missing result after observed processing stops the batch. An ignored Start stays in monitoring without repeated clicks. Missing/ambiguous controls or focus loss stop without stale coordinates.
- Preserve the original T/E/A/L workflow and single three-second Start button. Profiles without the new operation field default to tech parts.
- Verify real ready/busy/complete frames from 2026-10-24 03-07-56.mp4 after translation and scaling, plus simulated relocation during research, varied durations, finite/continuous batches, ignored Start, existing processing, absent results, hidden controls, and focus loss.

Processor recognition regression: the apartment failure frame scored 0.8563 on the old whole title plate (threshold 0.86). Matching opaque lettering scores 0.9158 and verifies Start at the same detected location. Reject standalone captions, recover from an outdated scale hint, and preserve all existing relative control geometry.

Processor move/overlap regression: compare exact text and antialias-normalized text with ±1px template dimensions; verify Start independently and return its matched center in the current frame. Preserve stable plate-relative coordinates for input/progress checks. Reject duplicate windows even when they render differently. Cover actual overlapping busy/completed frames, fractional-pixel render shifts, and repeated blueprint cycles with the real detector while the window moves every capture.

Different-item/performance update: use color-independent grayscale gradient matching of the blueprint datacube shape rather than a red-pixel test. Different researchable items may produce different blueprint colors. Propose Processor captions on a half-resolution whole-client image, then refine the caption at native resolution and independently match Start. Preserve the thorough matcher as a fallback. Priority scale is the last verified scale, or an initial viewport-based guess. Poll blueprint progress every 50ms plus recognition time; three idle observations and a result still confirm completion. Keep the three-second focus countdown and all focus/ambiguity protections.

Portable packaging: ship runtime/ with Python 3.12.14 x64, standard library, native extension/VC runtime DLLs, Tcl/Tk, NumPy 2.3.5 and its native libraries, and OpenCV 5.0.0.93. Retain upstream license files. The runtime path file confines imports to the bundle. Launch.ps1 always selects local runtime/python.exe and verifies imports/assets before opening the UI; it must not silently select an installed Python or Codex cache. Check-Dependencies.cmd and the legacy Install-Dependencies.cmd verify without downloads or game input. Launch.cmd is the portable entry point; absolute local .lnk is not shipped in the portable ZIP. Verify extracted-folder relocation with conflicting Python environment variables and paths before delivery.

## Macro Suite construction extension

Rename the application, primary folder, local shortcut, and portable ZIP/root to Neocron Macro Suite. Provide Research and Construction tabs with one shared Start in 3 seconds control, no hotkeys, and stop on focus loss. Preserve research configuration and all portable dependencies.

Construction supports Tangent Weaponparts 7/9 and Crahn Holy Heal. The user supplies matching blueprints and ingredients. Locate candidate cube stacks from the current Inventory, hover to verify BLUEPRINT plus the selected recipe in its tooltip (never select used empty datacubes), drag one into a freshly found free Processor input, confirm exactly one in the movable quantity dialog, and re-find Start before clicking. The game handles all ingredients and returns previous products/used cubes on the next Start. Do not drag ingredients or collect the result manually. Permit leftover empty cubes, reject other pending inputs, and observe progress then stable idle plus the expected output before counting a build. Blueprint availability is entered manually; count zero builds the available stack. Do not retry uncertain transfers.

Use both supplied construction videos as visual fixtures; test source identity, one-unit confirmation, retained used cubes, relocation at each stage, variable durations, WP7/WP9/HH configuration, failure/focus handling, tab switching/persistence, and the renamed portable extraction.

Construction blueprint search scans current Inventory rows, then scrolls downward one wheel notch when no verified match exists. Read the opaque scrollbar thumb in window-relative coordinates to verify movement independently of item colors or the changing scene. Clear tooltips before reading the thumb, reacquire Inventory before scrolling, and reacquire source/destination after scrolling. Stop when the thumb no longer advances, on a hidden scrollbar, on focus loss, or after 128 scrolls. No ingredient clicks/drags or unverified transfers. Start at the current scroll position; do not silently wrap or reset the user's Inventory.

Regression from 2026-10-26 15-06-38.mp4: accept +/-1px width as well as height variants when matching recipe tooltip text. Keep the original confidence and separation margin between Weaponparts 7/9. Propose only compact connected colored icon bodies; exclude the two-cell finished Holy Heal halves from blueprint candidates. Retry an unknown recipe during hover and stop specifically on an unreadable BLUEPRINT tooltip if no match exists, before scrolling past it. Preserve real Inventory crops and replay the actual WP7/Holy Heal hover frames through the production detector and construction search at scales 1, 4/3, and 1.7, with no native game inputs.

## Later change (26 Oct 2026)

Favorites (tab, buttons, shortcuts, profile field) and the Drag button / Drag modifier selectors were removed at the user's request. Profiles with an old "favorites" key load and drop it; drags are always plain left drags. Current behavior is in SPEC-SHEET.md.
