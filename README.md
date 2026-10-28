# NeocronSharp

One program, two engines, started from **Launch.cmd**:

- **Screen automation (Python, this folder):** Research, Construction, Recycling, Nav-Ray auto-walk and Tech Counter
  tabs. Reads the game from screenshots and OCR, sends ordinary mouse/keyboard input.
- **Tracker, Quests, Loot library and Plugins (C#, `NeocronSharp/`):** the NPC/player tracker on the native sector map,
  environment/BSP export, quest browser, loot library and plugins, shown inside the suite's **Tracker**, **Quests**, **Loot library** and **Plugins**
  tabs (one embedded NeocronSharp process; the window grows to fit it). The coordinate recorder and point navigation open
  in their own windows from the Tracker tab's bar, or with **Open NPC Tracker.cmd** / **Open Coordinate Recorder.cmd**.
  Reads the game client's memory read-only (only the fingerprinted build). It needs the .NET 9 Desktop Runtime; **Build** in the Tracker tab
  (or `dotnet build NeocronSharp\NeocronSharp.sln -c Release`) rebuilds it with the .NET 9 SDK. Its own docs:
  [NeocronSharp/README.md](NeocronSharp/README.md), [NeocronSharp/SPEC.md](NeocronSharp/SPEC.md),
  [NeocronSharp/PLUGINS.md](NeocronSharp/PLUGINS.md).

Tests: `runtime\python.exe -m unittest discover -s tests` (Python) and
`dotnet run --project NeocronSharp\tests\NeocronSharp.Tests -c Release` (C#).

## Screen automation

**Research**, **Construction**, **Recycling** and **Tech Counter** tabs. Browse a searchable construction catalog, build with the supplied **Weaponpart 7 / Weaponpart 9 / Holy Heal** examples, or add your own recipe names and shorthand. Count cabinet/inventory items and track rare sets with saved lists and exports. Optional slot counting, stop-at-slot rules, 15 skins including Basic, and a stop sound are included. **No coordinate calibration is required.** Processor/Start, Inventory and quantity dialogs are found from current screenshots, including after windows move.

The complete current specification is [SPEC-SHEET.md](SPEC-SHEET.md). [TASKS.md](TASKS.md) tracks the requests from this chat. [FEATURE-IDEAS.md](FEATURE-IDEAS.md) separates delivered features from future ideas.

Project transfer: [Claude project brief](CLAUDE-HANDOFF.md) and [copyable handoff prompt](CLAUDE-PROMPT.txt).

The imported counter's 51 pure-logic regression checks live in `tests/counter/`.
Run `python -m pytest tests/counter -q` with the optional `requirements-dev.txt`
installed in your development environment. Pytest is not required by the app.

## Repository checkout

The Git repository contains everything needed to run: source, the bundled `runtime/` (Python, libraries, Tesseract), recognition artwork, recipe catalogs, styling and regression fixtures. **Code > Download ZIP**, extract the whole folder, run **Launch.cmd**. The portable ZIP, personal profile, logs, diagnostics and recordings are excluded. The requirements file records the Python package versions; Windows supplies the local English OCR engine. Developer checks use `runtime/python.exe -m unittest discover -s tests -v`; `runtime/python.exe tools/build_portable.py` builds and extraction-checks a portable ZIP locally.

## Nav-Ray

In game press Tab and open Nav-Ray (F9). In the Nav-Ray tab pick a Category and Destination from the lists (all 23 categories and 239 destinations are included, compiled from the in-game window) and press Start in 3 seconds. The macro picks the destination, presses Start in Nav-Ray, then walks the dashed path (W plus mouse steering). Switch away from the game to stop. If blocked by a recognized door, it tries a right-click; this door handling has not yet been verified live. It stops when the path ends, it cannot move after recovery attempts, health drops or a loading screen appears. One route has been completed in a recorded live run; other routes and sector transitions remain unverified.

## Construction

Open **Construction → Catalog** to search **1,263 item entries** by name (including WP shorthand), filter by category, and view source links, listed level and build-method status. Select **Use blueprint recipe** to save that name and open the Job form. Only saved recipes participate in game recognition; browsing the catalog does not make the inventory search scan all 1,263 names. Start is disabled while the Catalog page is shown.

The three supplied construction examples include known material names. Most catalog entries come from item listings that do not publish construction materials or prove blueprint availability; they are marked **Check blueprint**. You must own the matching in-game blueprint and supplies. Rare-part and recycling-only entries are reference-only and cannot be loaded into the blueprint workflow. This catalog is not a claim of 1,263 verified build recipes. Source snapshot: [Tech Haven Items DB](https://db.techhaven.org/en/), 26 October 2026; details are in data/README.md.

1. Open **Construction** and choose a saved recipe or type the blueprint item's name. Add optional comma-separated aliases and click **Add / update recipe**. You can also type a new name and start; it saves automatically. **WP7**, **WP9**, and **HH** select built-ins; a name like **WP13** can be added without code changes. Use a full name when shorthand is ambiguous.
2. Open Inventory and Processor in Neocron. Put the construction tool in the first Processor slot. Use one source stack of the selected blueprint and keep the required ingredients in Inventory. Leave unprocessed blueprints out of the Processor before starting; used empty datacubes from a completed build may remain. Scroll Inventory to the top: the search runs downward from the current position.
3. Enter the number to **Build this batch**, or **0** to keep going until your blueprints run out. There is no stack size to enter.
4. Click the shared **Start in 3 seconds** button and focus Neocron. Switching away stops the batch.

**Inventory search defaults to Fast — datacube icons**, under Construction → Job → Transfer controls. A screenshot pass finds possible datacubes using color/body and edge-shape proposals. The macro hovers those candidates only, verifies their BLUEPRINT names, and scrolls onward when no match is found. It avoids hovering every ingredient and empty square. The 21:55 recording's views produce two candidates each, rather than 48 hover targets. This count is recorded-image analysis, not a measured live speedup.

If an unusual icon is missed, choose **Thorough — every cell** in the same selector. This retains the earlier exhaustive method, with overlap reuse and short reads. The choice saves with the construction settings; profiles without a choice use Fast. Both modes clear and re-hover a matching blueprint before dragging. Local Windows OCR reads recipe names; shipped references also verify the three built-ins. Item numbers remain exact; a visual candidate alone never authorizes a transfer.

**Scrolling no longer restarts a full six-row scan.** The macro compares opaque item/text patterns before and after scrolling, finds the overlap, and reuses cells already checked in those rows. Newly revealed, changed and unresolved cells are searched. If overlap is ambiguous, it checks the view again rather than guessing. An occupied cell whose tooltip was never read remains unresolved and cannot be silently removed from later scans.

**Measured live (26 Oct, 2560x1440):** Fast found Weaponpart 7 from the top of Inventory in about 5-6 s over three views; the second build's previous-stack check took about 1.3 s. Speed varies with Inventory contents.

**Following builds check the last verified stack first.** The macro re-detects Inventory, derives that cell's current position, and checks its blueprint name again. A moved/replaced stack causes a normal search; stored coordinates never authorize a drag. This shortcut lasts only for the current batch.

Before searching, the macro checks Processor for an active job, pending quantity dialog or unprocessed input from an interrupted run. Finish/clear that state first. Used empty cubes and a previous output remain allowed. This preflight avoids spending time searching when Processor cannot accept another blueprint.

If the blueprint is absent from the visible rows, the pointer stays inside Inventory while the macro sends a wheel notch and checks for movement. It retries once if needed. If the game ignores the wheel, the macro makes tiny drags on the freshly detected scrollbar thumb and stops dragging as soon as movement is verified. It then searches the new rows. Search starts at the current scroll position and continues downward; scroll to the top first to search the whole Inventory. Keep Inventory's right scrollbar uncovered. A scrollbar that stops moving ends the search without transferring anything; there is also a 128-scroll search limit. Both windows and the source cell are detected afresh after scrolling.

Hover checks capture the Inventory/header and nearby tooltip region rather than the whole game client, reducing screenshot work per cell. A missing/moved header triggers a full capture and relocation. Final Processor/quantity checks still use fresh full captures. Shorter hover waits and fewer unnecessary pointer resets speed up the sweep; actual speed depends on game rendering and screen capture.

Use **Remove recipe** on the Job page to remove the selected saved/custom recipe or hide a supplied example from the Job list. This does not remove the source Catalog entry or alter batch counts. You can restore it by adding its name/shorthand or choosing it from Catalog. An empty Job list is supported; choose/add a recipe before construction can start.

It drags **one blueprint** into a free input, verifies quantity **1**, re-finds the Processor and its current Start button, and watches progress until the expected result appears. **Ingredients are never dragged or clicked. Neocron supplies them automatically.** There is no fixed construction timer. The game returns the previous result and handles the used datacube on the next Start; the final result remains in the Processor.

A pending/unverified dialog, unknown occupied input, missing tool/source/product, or focus loss stops the batch. An uncertain transfer is never retried automatically. Custom recipe completion is verified by the result tooltip name. Check the Processor and counts before restarting after any interruption. Available blueprints decrease only after confirmed completion.

## Activity log

The bottom **Activity log** is resizable: drag its divider/handle up to enlarge it
or down to shrink it. Its scrollbar lets you review earlier messages while Start
and the job tabs remain above the divider. The divider works with every skin.

## Tech Counter

The **Tech Counter** tab integrates the standalone counter. It scans open cabinets
and/or Inventory, reads item names and stack quantities, scrolls through unseen
rows, and totals the active named list. Choose **Scan: all / cabinet / inventory**
and **Log: all items / techs only**, then use the suite's **Start in 3 seconds**
button and focus Neocron. Switch away or move the mouse to stop; there are no
counter hotkeys or separate Stop button. Scanning hovers and scrolls only.

Use named lists, undo the last scan, rename/edit/delete scan entries, add manual
entries, and export to clipboard, CSV (including by cabinet), TXT or JSON.
Double-click a total to see its locations, or a scan to correct quantities/names.
Corrections teach the counter's name dictionary. **Sets…** shows complete and
nearly complete rare sets from the included 86-item database, with part locations,
search, filters and exports. Uncertain reads and partial scans are marked; review
them before relying on totals. Scanning the same cabinet twice adds it twice;
undo/delete its previous scan when replacing it.

Counter state is stored in **tech-counter/** and is independent of crafting
settings. On first launch beside the original **Neocron Tech Counter** folder,
existing lists, learned names and settings are copied without modifying the
originals. **Import standalone counter folder…** supports other locations; it
never overwrites an existing suite counter file. Existing standalone exports stay
in their original folder. Suite exports default to **tech-counter/exports/**.
Counter user data is excluded from Git and the portable download; keep a backup
of your own tech-counter folder when moving installations.

Tesseract and its English model are bundled in **runtime/tesseract/**. The counter
uses its existing Tesseract recognition; crafting retains Windows OCR. Both run
locally. See [integration specification](TECH-COUNTER-INTEGRATION.md) and
[counter notices](ntc/NOTICE.md).

## More Materials in GoGo

Tick **More Materials in GoGo** on the Construction Job page and keep a GoGuardian window open next to Inventory and Processor. If a build is refused because materials ran out, the macro moves up to 15 of each needed ingredient from GoGuardian into Inventory, then presses Start again. It works for the built-in Weaponpart 7 and 9 recipes. GoGuardian transfers have not been tested live yet; send macro.log and diagnostics/latest.png if it stops.

## Slot counter and chosen-slot stop

Enable **Count slots on constructed weapons / spells** to track 0–5 slot totals for the current batch. Unread values are separate from zero; weapon parts are N/A. The option adds a result-tooltip inspection after completion.

Enable **Stop at N or more slots** and choose 0–5 to stop as soon as a verified qualifying result is built. Slot inspection is enabled for this rule. The macro leaves that result in Processor and does not transfer another blueprint or click Start again. Unread slots cannot meet the threshold. Totals reset for a new batch.

## Recycling

The **Recycling** tab includes **201 discovered recipe entries**, searchable by result/ingredient and filterable by category. They include 161 Tech Haven Items DB records plus 40 supplemental legacy/community entries, explicitly labeled. See ingredient quantities, listed tech level, source and retrieval date in the details panel. Some legacy names/variants overlap; the catalog is not a claim that all entries are current/live verified. The incomplete published Swamp Shaman Trophy recipe is documented separately in the spec/data notes.

For execution, select a recipe and **prepare Recycling Tool in Processor slot 1 and the exact inputs yourself**. Start in 3 seconds verifies the tool name, clicks the freshly detected Start once, observes processing, verifies the output name and stops. It does not automatically transfer recycling materials or repeat consumed inputs. Cloning/salvage are described in the spec; this prepared-run executor does not guess those workflows.

Sources: [Tech Haven Items DB](https://db.techhaven.org/en/item-lists/recyclable), [supplemental community recipes](https://neocron.fandom.com/wiki/Recycling_Recipes), [mechanics](https://wiki.techhaven.org/Recycle). Snapshot retrieved 26 October 2026; all recipe data is included offline.

## Skins and stop sound

The bottom **Skin** selector offers Basic, RPOS Classic, CronAMP 97, Dead Sector Terminal, BioLab Workstation, Fallen Circuit, Tangent Forge, Pepper Park Signal, PSI Resonance and Dome Control. It saves your choice. These are native control skins; the separate [interactive concept gallery](styling/skin-gallery.html) explores richer Winamp-inspired styling.

Dead Sector Terminal and Basic retain their original looks. The eight other skins now have their own native frame, button, field and tab artwork, caption fonts and header badges. CronAMP uses brushed metal, Fallen Circuit has circuit traces, Tangent Forge has rivets, PSI has geometric frames, and Pepper Park now uses burgundy/magenta neon. The gallery reuses the app's actual border artwork while keeping a separate concept layout.

**Sound when stopped** is optional and off by default. A bundled tone plays once for completion, chosen-slot stopping, handled errors, focus loss or closure. Ordinary per-item completion does not beep while a batch continues.

[Detection-preview photo example](styling/detection-preview-concept.png) is a labeled **concept**, not a live overlay. The actual preview mode remains an idea.

All third-party Python libraries, including the new WinRT bindings, are inside runtime/. Windows supplies its local English OCR engine/language data. Screenshots are never uploaded for recognition.

| Recipe | Ingredients handled by Neocron |
| --- | --- |
| Tangent Weaponpart 7 | Trisol, Metal D, Arillium, Solantium |
| Tangent Weaponpart 9 | Gamonin, Metal D, Solantium, Strastin, Tiberal |
| Crahn Holy Heal | Tangent Weaponparts 9, 7, 6, 5, 4, 1 |

## Research: start with tech parts

1. Double-click **Launch.cmd**, then choose the **Research** tab. The local **NeocronSharp.lnk** shortcut also works on this computer; use Launch.cmd when copying or extracting the portable folder elsewhere.
2. In Neocron, open Inventory and Processor. Cancel any quantity dialog left by a previous interrupted transfer, then check the stack counts. Put the research tool in the first Processor slot and leave the remaining inputs empty. Keep one visible source stack per requested type. A previous result can remain in the result area.
3. Enter each stack's actual **Available** size and how many to **Research**. Set Research to zero to skip a type. Counts are entered manually; screen coordinates are detected automatically.
4. Click **Start in 3 seconds**, then switch to Neocron before the countdown finishes. The game is bound automatically each time you start.

The app starts idle. Tech-part mode requires a positive count for at least one stack. Settings are saved automatically on Start. The Start button is disabled during the countdown and batch. Close the app to cancel the countdown.

The suite finds Processor and Inventory at any game resolution, fullscreen or windowed, at any UI scale (about .6x to 2.2x of the reference). If the Processor is not found the status line says so. If a size misbehaves, send diagnostics/latest.png and macro.log.

The current target setup supplied by the user is **2560 x 1440, borderless fullscreen, UI scale 1.7**. The artwork comes from the user's green-UI recording. Detection searches the full client area at multiple rendered scales; positions are never scaled from old fixed screen coordinates.

## Item → blueprint

Select **Item → blueprint** under Research type. Set **Copies per batch** to the number of blueprints you want, or **0** to repeat until you switch away from Neocron. Prepare the research tool, item (such as Weaponpart 9), and empty datacubes in the game as shown in your recording, then click **Start in 3 seconds** and focus Neocron. Inventory detection and tech-stack counts are not used in this mode.

The macro only clicks the current Processor Start button. It finds the Processor again as it moves, watches the percentage/progress bar, and confirms a blueprint datacube by its shape before beginning another copy. Result color is unrestricted; the different item shown with a green blueprint is supported. It must observe processing before counting completion, so a previous result cannot cause repeated clicks. Research already in progress is monitored without another Start click. There is no fixed research duration or time limit.

Processor detection first scans a smaller whole-client image, then verifies the title and Start button at native resolution. It does not depend on the previous window position. The next copy uses a fresh location check without an extra idle-wait loop. The three-second focus countdown remains.

The previous result returns automatically on the next Start; the final result stays in the Processor. A missing result, hidden/ambiguous controls, or focus loss stops the batch. If Start is ignored, the macro keeps monitoring without clicking again. The copy count is a saved per-batch target; status shows completed/remaining copies. Preparing inputs and supplies remains manual.

Choose **Tech parts (T / E / A / L)** to return to the existing stack workflow.

## Controls

**Start in 3 seconds** is the only action button. There are no registered hotkeys. Switch away from Neocron (for example, Alt+Tab or click another window) to stop. Closing the macro also stops it and releases its held inputs.

The Processor and quantity dialog can move between runs. Keep their controls visible. If a window is hidden, clipped, covered, or ambiguous, the macro briefly searches again and stops if it cannot establish a position. **It never falls back to old coordinates.** Multiple visible T/E/A/L stacks of a requested type stop tech-part research; construction uses its first verified matching blueprint stack.

Inventory detection matches the opaque INVENTORY caption and verifies both Max Load and Free Load underneath it. This avoids depending on the translucent window trim and excludes the Inventory label in the game's top navigation bar. Inventory can be relocated, and its scale is searched independently when a previous scale hint fails.

Switching away from the game stops the batch with no automatic resume. Check the current item and counts before starting again. A stopped batch releases mouse buttons and keys held by the macro.

## Tech-part research behavior

Each cycle detects the UI, drags one part to input slot 2, handles the one-unit dialog, finds the Processor again, and clicks its current Start button. The quantity dialog is recognized by its opaque title text and Half control, so the background behind it can change. The macro verifies that the numeric field contains exactly **1** before clicking OK. An existing 1 is left alone; an unverified value is never confirmed. Transfers are always plain left drags; there are no drag button/modifier options.

Available must match the real stack size. The last unit of a stack may transfer without the quantity dialog. A larger stack must show a recognized dialog before the macro types or confirms anything.

The game automatically returns the preceding result to Inventory when a new research run starts. **The last result stays in the Processor.** The macro does not click the result area or start an extra run just to collect it.

Research completion is **monitor-only**. The macro follows the detected Processor and waits for three consecutive observations of an empty input. There are no per-stack duration settings, fixed research waits, minimum research duration, or research time limit. T/E/A/L can each take as long as the game needs. Old saved research timing settings are removed automatically. Short input pacing and bounded UI-recognition retries remain internal; they never decide that research is finished. A disappeared Processor never counts as an empty input.

A cleared input indicates a processed attempt. Research success/failure text, fluid quantity, free inventory space, and tool condition are not read automatically. An unexpected UI state stops without retrying. If research remains stuck with its input occupied, the macro keeps monitoring until the game loses focus or you close the macro.

Completed cycles update and save Available and Research counts. After an interrupted transfer, inspect the current item and correct the counts before restarting; the part may already have left its stack. Settings live in `profile.json`, and status/errors in `macro.log`. The updated app ignores old saved calibration points.

If a run stops, the last successfully captured game frame is saved to `diagnostics/latest.png` with the reason in `diagnostics/latest.json`. These two files are overwritten on the next failure. The capture is reused from the bound game client; focus loss does not trigger a fresh desktop screenshot. Status messages identify whether the macro is finding the Processor, finding Inventory, or transferring a part.

## Requirements

The folder now includes a self-contained 64-bit Windows runtime: **Python 3.12.14**, **NumPy 2.3.5**, **OpenCV 5.0.0.93**, and **Tcl/Tk 8.6**. No Python installation, pip command, Codex installation, or dependency download is needed to run the program.

For another computer, extract **NeocronSharp Portable.zip**, keep its complete folder together, and double-click **Launch.cmd** inside it. The runtime folder must remain next to app.py and assets. Launch.cmd uses only that local runtime and verifies its libraries/artwork before opening the app. The ZIP includes the app, artwork, runtime, license files, launchers, and saved profile; it excludes recordings, failure screenshots, logs, developer tests, and the computer-specific shortcut.

**Check-Dependencies.cmd** verifies the bundled libraries without game input. The older Install-Dependencies.cmd now performs the same check for compatibility; it no longer downloads anything. The current local shortcut uses the same updated launcher.

```powershell
.\runtime\python.exe app.py
.\runtime\python.exe app.py --check
.\runtime\python.exe app.py --smoke-ui
.\runtime\python.exe -m unittest discover -s tests -v
.\runtime\python.exe -m compileall -q app.py macro_core.py windows_backend.py vision.py vision_runner.py
```

`--check` validates the saved counts/settings without game input. `--smoke-ui` creates and closes the panel without sending input. Tests include actual recording crops, random Processor positions on 2560 x 1440 frames, rendered scale variants, a synthetic L stack, and simulated relocation between every run.

The detector supports the demonstrated green game HUD. Different **in-game** HUD artwork may require updated templates. The suite's own 15 skins do not alter game detection. A resolution change during a batch stops it; start again at the new size.

The user has confirmed successful live tech-part operation. Blueprint mode was checked against all 37 one-second observations in the supplied Weaponpart 9 recording, with translated/scaled ready/busy/completed fixtures and simulated moving-window batches. It has not been tested live by the assistant. Automated tests cover visual recognition, varied research durations, interruption, and focus loss.

## Program icon

`assets/research-tool.png` is the enhanced transparent tool image with the curved green display (1254 × 1254). `assets/research-tool.ico` contains Windows icon sizes from 16 to 256 pixels. The app title bar/taskbar and `NeocronSharp.lnk` use this icon.
