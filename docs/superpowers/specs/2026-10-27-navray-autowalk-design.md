# Nav-Ray auto-walk — design

Date: 2026-10-27. Status: approved in chat, spec awaiting review. Nothing implemented yet.

## Goal

A new **Nav-Ray** tab. The user names a destination; the macro opens the in-game Nav-Ray window,
selects it, presses Start so the game draws its dotted path, then walks the character along that
path until arrival or until something blocks it. First version: walking inside one area only.

## Facts from the user's screenshots (27 Oct)

- Nav-Ray window (menu NAV-RAY, F9): "Select" list of nested categories (UTILITIES, PLAZA
  APARTMENTS ... PLAZA DUNGEONS, ...; scrolls), "Destination" pane with **Start** / **Stop**,
  and Small Map / Sector Map / World Map buttons.
- The path is a thin green dashed line on the floor with small downward arrows, third-person
  camera, follows stairs and bends. A reticle sits at the centre of the 3D view.
- Controls: W walks; the mouse always turns the camera; **Tab** toggles the interactive UI
  (free cursor) for windows like Nav-Ray.

## Out of scope (v1)

Sector doors, subway, loading screens (detected and reported, not crossed), outdoor wasteland
travel, combat (health loss stops the walk), world-map travel.

## Approach: steer by what the screen shows

No memory reading, no calibration. Each step: capture, find path dashes/arrows in the 3D view
(outside HUD windows), choose the stretch just ahead, turn the camera towards it with relative
mouse motion proportional to its horizontal offset from the view centre, hold W.
If no dashes are ahead, turn in place until some are seen (bounded). Rejected: reading the
minimap (shows neither path nor heading); record/replay of walks (not requested).

## Components

- `navray.py`: locate the Nav-Ray window by its title/Start/Stop strip with the local OCR (any
  scale); read the Select list; click entries by name; click Start/Stop. Destination is given as
  a path of names ("Faction HQs > ..."); matching is by OCR text with scrolling.
- `pathvision.py`: path-colour mask restricted to the 3D view, dash/arrow segmentation, choice
  of the target point ahead, steering error. Pure functions, tested on saved frames.
- `navray_runner.py`: sequence (Tab to cursor, open window, select, Start, Tab back, walk),
  stop reasons, shared guards (focus/identity/size) and key release on any exit.
- `windows_backend.py`: add relative mouse movement (SendInput MOUSEEVENTF_MOVE); the game holds
  the cursor in mouse-look, so absolute moves are not enough. Keys already support hold/release.
- `app.py`: terse Nav-Ray tab (destination box + shared Start in 3 seconds). No new hotkeys,
  no Stop button; switching away from the game stops, as everywhere else.

## Stop conditions (each reported in the status line)

Arrived (no path for ~4 s after it was seen and Nav-Ray reports/ends), path never found, not
moving (frame unchanged while W held ~3 s), health bar dropped, loading screen, focus lost,
maximum duration. All held keys are released on every exit; Tab state is restored to mouse-look
only if the macro changed it.

## Testing and honesty

Offline: dash detection on the two supplied path screenshots (and variants), Nav-Ray window
and list reading on the supplied captures, steering maths and stop logic with a fake backend.
Not establishable offline: real steering, arrival, stuck/health detection. Report these as
unverified until a live run shows them in macro.log.

## Open items needing the user

- Screenshots after clicking a category and after selecting a destination (what the Destination
  pane shows, whether lists nest further, how Start behaves).
- Whether Stop (Nav-Ray) should be pressed by the macro on arrival.
