# Handoff prompt for ChatGPT

You are taking over **NeocronSharp**, a Windows desktop helper for the MMO Neocron Evolution
(Tk app, Python, screen capture + OCR + simulated input). The C# tracker/map app lives in `NeocronSharp/` and
is embedded in the Tracker, Quests, Loot library and Plugins tabs (see README.md). Repository: `sheepnotlost/NeocronSharp`,
branch `main`. The local working copy is the folder this file is in.

## Read first
`CLAUDE-HANDOFF.md`, `TASKS.md` (newest sections near the bottom), `README.md`, `SPEC-SHEET.md`, and the
Nav-Ray design and plan in `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## How to run
- Use the bundled interpreter only: `runtime\python.exe` (it is committed; no system Python, no pip).
- App: `Launch.cmd`, or `runtime\python.exe app.py`. UI check: `runtime\python.exe app.py --smoke-ui`.
- Tests: `runtime\python.exe -m unittest discover -s tests` (about 300 tests, about 4 minutes). For Nav-Ray work:
  `runtime\python.exe -m unittest tests.test_pathvision tests.test_navray tests.test_navray_runner tests.test_routes`.

## Working rules (the user's)
- Be concise. Lead with the answer.
- After each change: run the relevant tests, commit, and `git push origin main`. Do not build the portable ZIP.
- Ask before running the full test suite or anything that opens Tk windows: they steal focus from the game,
  and if the user is playing, it breaks their run.
- Never claim something works in the game without evidence (the user's video, `macro.log`, or recorded frames).
  Offline tests on saved frames are not live proof; say which one you have.
- Never commit personal data: `profile.json`, `macro.log`, `diagnostics/`, `routes.json`, `tech-counter/`,
  videos (`*.mp4`). These are git-ignored; keep it that way.
- Keep the UI terse (one short line per label; a test enforces it). No macro hotkeys, no Stop button: switching
  away from the game stops any run. Keep the focus/window guards.

## Current focus: Nav-Ray auto-walk
The user picks Category > Destination in the app's Nav-Ray tab. The macro opens the in-game Nav-Ray window,
selects the destination, presses Start, then walks the character along the dashed route the game draws on
the floor.

Files:
- `navray.py`: Nav-Ray window finding (OCR of the Small/Sector/World Map buttons), list row reading
  (Tesseract, rows read in parallel and cached), scroll-thumb finding, destination catalog loading.
- `navray_runner.py`: the run. Opens the window from the top menu if needed. Tells the interactive-UI mode
  (Tab) apart by OCR of the top menu bar. Selects via scroll-thumb drags (wheel fallback), presses Start, leaves UI
  mode. Then the walk: turn calibration (measures px of view slide per mouse count), "legs" of reading dashes
  and steering, a continuous tether while lined up, a full 360° sweep when no dashes are in view, cross-leg
  stuck detection, health/loading-screen stops, and per-run recording. Tuning constants are at the top.
- `pathvision.py`: finds the dashes in a frame. Dash colour = the HUD colour scheme, read from the top-left
  Location panel (`hud_hue`). Candidates are filtered by size, shape, saturation, hue spread and contrast; the
  best straight chain is ranked by dash mass with a bonus for starting at the character; there is a fallback
  for paths that bend round corners (`_curved`). It rejects text rows, signs, posters and green walls; each
  rejection rule has a regression test made from a real frame in `tests/fixtures/`.
- `routes.py`: route library (`routes.json`, user data): start/end area from the HUD, legs, best walk.
- `data/navray_destinations.json`: all 23 categories and 239 destinations (repeated cut-off names are numbered
  "#n" and picked by position).
- Tools: `tools/run_navray.py "TRADER DIRECTORY > WEAPONS"` (a live walk from the command line),
  `tools/review_run.py` (summary of the last run plus `failures.png`), `tools/route_map.py`,
  `tools/scan_navray.py`.

Status (27 Oct 2026):
- One verified live success, from video and log: Trader Directory > Weapons, from the Plaza start into the
  Archer & Wesson shop in about 35 s, default green HUD.
- The next run (Neocron City Sectors > Viarosso SEC-3) stopped early at a corner where the route bends into a
  doorway. A fix for bending paths (`_curved`) is pushed and tested on frames from that video, but it has not
  been verified to complete a route live.
- A newer video, `2026-10-27 22-24-13.mp4`, shows a walk reaching the tiled bend, then repeatedly losing
  visible dashes after turning; it stopped at 22:25:19 with "turning does not line the dashes up". Frames at
  52.7s and 63.9s show near-centre translucent dashes rejected by the character exclusion box and saturation
  cutoff. The detector now keeps clear dash shapes there and permits faint floor dashes with contrast >=16.
  Both frames are regression fixtures at 1280/1920/2560 widths; the revised detector still needs a live walk.
- Two later recordings at 23:07:58 and 23:11:35 show running in place against an obstacle and a closed
  TECH DOOR. The walk now compares background scenes over time to detect lack of progress despite animation,
  and on a recognized door attempts a guarded right-click before the usual back-off. Tests use real frames;
  opening doors and following through them are not yet verified live. Other labels and unlabeled doors remain uncertain.
- Known weak spots:
  - "Arrived" is only a guess (no dashes after a full sweep), so any lost path ends the walk as "arrived".
  - Turning is jerky and can overshoot.
  - Zone changes, the subway and combat are not handled. Labeled-door right-click recovery needs a live test.
  - The red HUD skin has not been tested since the latest changes.
  - The route library does not steer anything yet.
  - The game's own route data (`worlds\pak_worldroute.dat` in the game folder; zlib after a 16-byte header) is
    only partly decoded.

## How the debugging loop works (this is what made progress)
The user runs a walk and records the screen. The video lands in the project folder, named by its start time,
e.g. `2026-10-27 22-17-11.mp4`. You then:
1. Read the end of `macro.log` for that run. Each run also records `diagnostics/last_run/events.jsonl` plus a
   JPEG per decision; run `tools/review_run.py`.
2. Extract frames from the video with OpenCV (one per second; ignore anything after the time the user gives).
   Line them up with the log: video time = log time minus the video's start time. Look at the moments where
   things go wrong.
3. Run `pathvision.find_path(frame, color=hue)` on those exact frames to see what the detector saw.
4. Fix the cause, add the real frame to `tests/fixtures/` as a regression test, run the tests, push.

Every fix in this project came from a real frame, not from guessing. Read the frames before changing
thresholds.

## Other features (stable; avoid breaking them)
Research and Construction automation (Processor windows, blueprint search, GoGuardian refills), Recycling,
the Tech Counter tab, 15 skins. See `CLAUDE-HANDOFF.md` and `TASKS.md`.
