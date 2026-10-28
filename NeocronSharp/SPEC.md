# NeocronSharp movement proof of concept

## Planned expansion selected by the user (2026-10-28)

1. **Plugin framework:** load separate C# modules, enable or disable each one,
   and provide lifecycle methods, per-module settings, and logging. See
   `PLUGINS-SPEC.md` for the current implementation and operating limits.
2. **Control panels:** provide external windows for plugin settings, diagnostics,
   and status. Embedded AO windows cannot be reused without investigating a
   separate Neocron UI integration.
3. **Follow another character:** use a verified nearby player's identity and
   position with steering. Plan stop behavior for loss of target, zoning,
   focus loss, collision, stuck movement, and cancellation before live use.
4. **Network packet features:** investigate Neocron's own protocol and message
   handling separately; AO packet formats do not apply to Neocron.
5. **Lightweight client:** explore a separate AOLite-style implementation of
   login, networking, and client state after the Neocron protocol is understood.

Only item 1 is authorized for implementation now. The remaining items are
future investigation, not existing capabilities or commitments to feasibility.

## In-game NPC counter

The user requested the original status panel be replaced by a small NPC count
under the compass. Implement it as a separately enabled plugin using an external,
click-through, non-activating overlay window and verified read-only tracker snapshots.
Display the loaded NPC count. Hide on focus loss, missing or
stale telemetry, zoning, or minimization. The plugin does not inject code,
change client files, send input, or modify game memory. Windowed/borderless
compatibility must be checked on the running client; exclusive fullscreen is
not guaranteed to display normal desktop windows.

## Objective and accepted scope
Use the Neocron Evolution installation in `../Neocron Evolution 2.5` as the
reference build. The launcher may run its original installation; accept that
process only if its executable fingerprint exactly matches the reference.
The user requested a short straight line directly ahead, traversed as
A -> B -> A -> B -> A (two round trips), ending at A.

## Navigation extension
The user selected character navigation as the next feature. Add a plain
"Save this spot" / "Walk to saved spot" workflow without requiring coordinates.
Read the player's orientation from the native transform getter as well as its
position. Steer using ordinary relative mouse movement; never write game memory.
Only confirm an arrival after key release and a measured stationary sample.
Validate the native forward-vector convention against measured forward movement
before allowing destination travel; refuse navigation if it does not match.
Support one user-saved destination in the same area/session, with a
bounded distance and an explicit warning that collision avoidance is not yet
implemented. Retain the original two-round-trip test as a separate operation.

## Fixes from user run logs
- Accept destinations around 418, 445 and 709 units away; replace the prototype's
  400-unit limit with a 10,000-unit outer check and validate before countdown.
- Treat small longitudinal overshoots separately from sideways corridor exits.
- Spread mouse corrections over multiple input frames and record observed turn
  angles, since the client samples and recentres its mouse every frame.
- Keep run failures visible in red and attempt to restore the control window.

## Implementation plan
1. Inspect this client's executable for a verifiable source of player position.
2. Build an external x64 diagnostic reader and a four-leg movement controller.
3. Read position during movement so endpoint arrival is measured rather than
   inferred from equal forward/backward durations. Stop on missing telemetry,
   focus loss, cancellation, zoning, lack of progress, or leaving the line.
4. Build and exercise simulated movement and interruption tests, then perform
   the live test once the user is logged in and the client can be observed.

## Structure and commands
`src/` contains the C# implementation; `tests/` contains deterministic tests;
`tools/` contains executable inspection tools; `README.md` records operation,
client fingerprint, calibration evidence, and outstanding limitations.

Build: `dotnet build NeocronSharp.sln -c Release`
Test: `dotnet run --project tests/NeocronSharp.Tests -c Release`

## Code style and testing
Use descriptive PascalCase public names, explicit units, and small interfaces
between telemetry, movement decisions, and Windows input. For example:
`MovementDecision Decide(PlayerSample sample, TimeSpan elapsed)`.
Use a dependency-free deterministic test harness for endpoint ordering,
overshoot, reverse speed differences, and stop/error cleanup.

## Boundaries and completion criteria
- Preserve the original AOSharp sources and the user's game configuration.
- Read game memory only; movement uses ordinary game controls.
- Never claim world-coordinate support from an unvalidated address or claim
  arrival based solely on a timer. Record live results separately from tests.
- Release movement inputs on every exit. Provide an immediate stop control.
- Live completion requires observing four measured legs and a return to A.
- Authentication, if required, is completed by the user.
