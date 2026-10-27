# Tasks

- [x] Implement configuration and sequence engine.
  - Verify: simulated T/E/A/L runs, single-item transfer, timeout, stop, pause, and focus-loss tests.
- [x] Implement Windows input, client capture, and visual detection.
  - Verify: input structure sizes and read-only native calls, with no game input.
- [x] Replace calibration UI with automatic detection preview; preserve launchers and profile validation.
  - Verify: withdrawn-window UI smoke test, configuration check, and compile check.
- [x] Document operation and remaining in-game verification.
  - Verify: instructions cover automatic detection, final result, failure recovery, and completion limits.

Result: 55 tests pass, including the user's actual current-rendering Inventory crop, background-independent Inventory headers, local failure diagnostics, missed-dialog screenshot, exact-one checks, monitor-only variable research lengths, random Processor locations on 2560 x 1440 frames, larger rendered UI scales, synthetic L labels, and simulated relocation between every cycle. UI smoke and compile checks pass. No coordinate calibration is required.

Live testing was authorized. The computer-use capture helper repeatedly timed out, including a requested retry. No live game input was sent; live verification remains pending capture availability or the macro's own in-game detection preview.
