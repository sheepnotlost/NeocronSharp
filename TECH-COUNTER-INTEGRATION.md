# Tech Counter integration

## Objective and acceptance criteria

Embed the existing Neocron Tech Counter in the suite as a fourth tab. Preserve
cabinet/inventory scanning, quantities, named lists, scan editing/undo, exports,
learned names and the 86-entry rare-set database. Use the suite's skins and one
Start in 3 seconds button. Register no hotkeys and add no Stop button.

Only one game operation may run at a time. Scanning stops when the bound game
loses focus, is minimized/resized, the user moves the mouse, or the suite closes.
It must not refocus the game or restore the pointer over another application.
Counter scans hover and scroll only; they never transfer or click items.

## Storage and compatibility

The imported `ntc/` Python package retains its counting and set-analysis logic.
`tech_counter.py` adapts its UI and scanner to the suite's lifecycle/backend.
Read-only resources live under `ntc/data/` and `ntc/assets/`. User lists, learned
names, config and exports live in `tech-counter/`, separate from macro profiles.
On first use, copy the original sibling counter's JSON state without modifying
the source or overwriting existing suite state. Provide explicit folder import
for portable installs; import never replaces an existing destination file.
User state and scan exports are excluded from Git and distributable archives.

## Dependencies and distribution

Keep Tesseract's existing OCR behavior. Bundle Tesseract plus its English model
under `runtime/tesseract/`, and Pillow, pytesseract, packaging and mss inside the
local Python runtime. Include counter provenance and third-party notices.
The portable build must work with external Python/Tesseract paths unavailable.

## Implementation and checks

Follow existing Python/Tk conventions: UI changes on the Tk thread; scanner
events through the suite queue; injectable backend for input-free tests.

Commands (from the suite directory):

```powershell
.\runtime\python.exe -m unittest discover -s tests
py -3.14 -m pytest tests/counter -q
.\runtime\python.exe verify_dependencies.py
.\runtime\python.exe app.py --smoke-ui
.\runtime\python.exe tools\build_portable.py
```

Test state import/non-overwrite, list totals and sets, embedded UI with no
additional root or hotkeys, shared countdown/worker routing, focus/close abort,
and portable relocation including a real OCR subprocess. These automated checks
do not prove in-game scan accuracy. Preserve existing macro behavior and the
original counter project; do not run live scans merely to validate startup.

The pytest checks reuse the standalone counter's list/name/export/set regression
tests. Pytest is a development dependency, not part of the shipped runtime.
