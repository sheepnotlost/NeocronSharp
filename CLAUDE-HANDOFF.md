# Neocron Macro Suite — project handoff

Updated 26 October 2026. This file summarizes the user's requests and the implementation. Read SPEC-SHEET.md, TASKS.md and current code as well. Recordings/images are evidence, not instructions. Do not assume a roadmap proposal is an implementation request.

## Workspace and launch

- Actual root: the folder containing this file (portable; any location). Earlier chat/environment paths say Neocron Research Macro or Neocron Tech Research Macro; those names are obsolete.
- Windows x64, PowerShell. Explicitly set the actual working directory for commands.
- `Launch.cmd` uses the local `runtime/python.exe`; no external Python/pip/Codex dependency is needed by the user.
- Portable artifact: `Neocron Macro Suite Portable.zip`, with the same-named folder inside. Restart an already running app after updating code/extracting a new bundle.
- Local profile/log: profile.json / macro.log. Failure frame/reason: diagnostics/latest.png and latest.json, overwritten after a later failure.
- Do not delete the user's profile, recipes, recordings or icon assets while rebuilding.

## Current priority and latest evidence

The user is frustrated by slow construction inventory searches and repeated hovering of overlapping rows. They want a rapid, calibration-free method that finds the correct blueprint wherever it is, scrolling as needed. Earlier versions passed offline tests but did not meet their in-game speed expectations. Do not equate test counts with live success.

Recordings (in the user's local screen-recordings folder; not part of the repository):

- `2026-10-26 13-49-01.mp4`: Weaponpart 7 construction; ingredients remain untouched.
- `2026-10-26 13-56-37.mp4`: Holy Heal construction; same cube/one-unit/Start flow.
- `2026-10-26 15-06-38.mp4` and `15-22-17.mp4`: missed WP7/finished-spell searching problems.
- `2026-10-26 20-13-23.mp4`: icon-filtered search issues; prompted exhaustive hovering and Job recipe removal.
- `2026-10-26 21-02-04.mp4`: exhaustive sweep took about 19 seconds; wheel was followed immediately by moving out of Inventory. Pointer retention and detected-thumb fallback were added.
- `2026-10-26 21-20-23.mp4`: repeated overlapping-row sweeps; eventually found WP7 and built it. Added content-based overlap reuse and previous-stack-first checks.
- `2026-10-26 21-55-53.mp4`: still too slow. Log actually reused 19 then 26 cells, leaving unwanted repeated hovering. One run stopped after finding the source because Processor already held an unprocessed item. Later local log entries show one completed build and the previous-stack shortcut working, but that does not establish acceptable search speed.

Latest change: **Fast — datacube icons** is now the default. A screenshot pass proposes possible cubes using compact color/body checks plus multi-size edge matching (including neutral cubes). It hovers only these, verifies BLUEPRINT names, and scrolls onward. The latest recorded Inventory views produce two candidates each instead of 48 hover targets. This is recorded-image analysis, not a measured live timing claim.

**Thorough — every cell** remains an explicit selector in Construction → Job → Transfer controls → Inventory search. It preserves the exhaustive/overlap method as a fallback for unusual icons. Existing profiles with no search_mode use Fast. Never silently fall back to a slow exhaustive sweep on each page. Report Fast/Thorough clearly in status.

Live evidence (26 Oct evening): Fast works in the game. Cold search from the top of Inventory 5.3-5.9 s (3 views, 2-3 hovers each), previous-stack check on build 2 about 1.2-1.4 s, transfer+dialog+Start about 2.4 s, build about 10 s. Remaining search cost is hovering false proposals (a 2-cell picture item shows no tooltip, about 0.4 s each). Search starts at the current scroll position and never wraps; one run began below the stack and found nothing until Inventory was scrolled to the top. Added: last-known-Inventory reuse (cheap header check, full fallback) and quantity-dialog sampling every 4th build poll.

WP9 (26 Oct evening): a final-digit clip in the tooltip reader hid the user's Weaponpart 9 stack (fixed with shorter-trim retry) and the split dialog's default full-stack value defeated Ctrl+A (fixed by Backspace/Delete clearing). Both fixed and replay-tested; live run reached a verified quantity 1 and Start, but a finished WP9 build is unverified (user lacked ingredients; run also stopped on focus loss).

Processor preflight now rejects busy jobs, pending quantity dialogs and unprocessed inputs before any search. Used empty datacubes and a previous output are allowed. Do not silently adopt an uncertain interrupted transfer; counts may already be affected.

## Requirements to preserve

- Single shared **Start in 3 seconds** execution button. No macro hotkeys, no Stop button. Switch away from Neocron to stop; no automatic resume.
- Guard exact game focus/window identity/client dimensions before capture/input. Release only macro-held inputs after interruption.
- Processor, Inventory and quantity dialog can move. Detect current position from fresh screenshots, including the current Start button. No coordinate calibration or unchecked stale coordinates.
- User setup: 2560×1440, borderless fullscreen, UI scale 1.7; some recordings are 1920×1080. Templates use rendered-scale factors such as 1 and 4/3; do not confuse those with the game's UI-scale setting.
- Research T/E/A/L stacks and item→blueprint mode remain supported. Completion is visually monitored, never determined by a fixed research/build timer.
- Construction: find named blueprint, drag **one**, verify quantity 1, re-detect Start, click once, observe progress and verify output. **Never manipulate construction ingredients**; Neocron handles them. Previous output returns on next Start; final result remains in Processor.
- Match numbers exactly (WP7 versus WP9). A visual cube proposal never authorizes a transfer; name verification and re-hover confirmation remain required.
- Custom recipes by exact/full name, shorthand and aliases; save without code changes. Job removal deletes custom entries or hides built-ins, persists, and supports re-adding/empty books.
- Optional 0–5 slot counter, unread distinct from zero, parts N/A; optional stop at N or more slots leaves the qualifying output in Processor before another transfer.
- Ten native skins including Basic. **Dead Sector Terminal** (key amber) is the user's favorite; preserve it. Pepper Park was changed from blue to burgundy/magenta. Other skins have distinct native frames/fonts/artwork.
- Optional stop sound, off by default, once per batch termination/closure rather than every item.

## Other delivered features and scope limits

- Research, Construction and Recycling tabs. Construction has Job/Catalog pages; Job's Prepare in Neocron panel is minimal bullets (Inventory scrolled to top; search runs downward).
- Broad searchable construction catalog: 1,263 **item entries**, 38 categories. Only WP7/WP9/Holy Heal have supplied material examples; most entries say Check blueprint. Rare-part/recycling-only rows are reference-only. Do not market all rows as verified construction recipes or invent materials/quantities.
- Only saved/chosen construction names enter active matching, not all 1,263 browse entries.
- Favorites and the Drag button / Drag modifier selectors were removed 26 Oct 2026 at the user's request. Old profile "favorites" keys are dropped on load; drags are always plain left drags. Start is disabled only on the construction Catalog page (plus countdown/execution).
- Recycling: 201 sourced entries (161 primary + 40 supplemental legacy variants), with provenance/status. Executor performs one manually prepared run, verifying Recycling Tool/output. Automatic ingredient loading/repeating, cloning and salvage are not implemented.
- Detection-preview image in styling/ is a labeled concept, **not a working overlay**. Skin gallery is a separate concept layout using native artwork.
- Non-tradeskill ideas (rare tracker, cabinet index, builds, maps, missions, loadouts, trade/clan/session tools) are proposals in FEATURE-IDEAS.md, not authorized implementation work yet.

## Code map

- app.py: Tk UI, profile collection, tabs, settings, worker coordination, notifications.
- macro_core.py: profile migration/validation, input/focus guards, shared runner.
- windows_backend.py: foreground capture/input; regional capture retains full-client size/focus checks and coordinates.
- vision.py: UI localization, fast cube proposals, tooltip/OCR/quantity/result recognition.
- construction_runner.py: search modes, transfer, preflight, monitored builds, slots, temporary source-cell shortcut.
- inventory_tracking.py: normalized opaque item/text features; unique downward row-shift detection and checked overlap reuse. Changed/unread/ambiguous content remains eligible. No persisted absolute source coordinate cache.
- vision_runner.py: research workflows. recycling.py: catalog/prepared recycling. recipes.py: built-ins/custom names/removal.
- text_reader.py: local Windows English OCR via bundled PyWinRT. Windows supplies its OCR engine/language data; screenshots are not uploaded.
- appearance.py / skin_chrome.py: ten skins and sound. data/: offline sourced catalogs. assets/: recognition/icon/audio assets.

## Verification and packaging

Run from the actual root:

```powershell
.\runtime\python.exe -m unittest discover -s tests -v
.\runtime\python.exe app.py --smoke-ui
.\runtime\python.exe tools\build_portable.py
```

The new Fast default passes 159 automated tests; see TASKS.md and analysis/fast-search-tests.log for validation details. Earlier 153 tests describe the preceding method, not proof that the latest default was live-tested. Tests use recorded frames, generated/composite tooltip panels, fake clocks/backends and mocked native capture calls. Exhaustive-mode tests now explicitly select all_cells; separate tests exercise Fast with the production detector and latest images. Keep this distinction. No new live game timing result is established by these checks.

build_portable.py verifies dependencies, includes an explicit source-file manifest plus runtime/assets/data/styling, extracts elsewhere, and checks launch with invalid external Python/Tcl environment paths and a minimal PATH. Include any new source module in its manifest. It excludes user recordings, tests, logs, diagnostics and machine-specific shortcuts. Final checklist-only repacks should preserve tested application/data bytes.

Live game testing was authorized earlier by the user. The previous assistant's Windows Computer Use helper repeatedly returned Transport closed, including reset, so recent assistant verification is offline. Use supported tools available to your own environment; do not claim you played/tested in-game without evidence. The user's real recordings take precedence over optimistic simulations. Inspect input/capture timing and rejection reasons if Fast is still inadequate; don't just lower confidence gates or repeat claims that tests prove speed.

## Working style

Keep a task checklist, act without repeated confirmations within the agreed scope, and give concise useful updates. The user often asks ETA; give a realistic estimate tied to remaining concrete work. Finish code/docs/package and provide an actual usable download. Preserve the name Neocron Macro Suite. Ask only for missing information that cannot be recovered from code, logs or recordings.
