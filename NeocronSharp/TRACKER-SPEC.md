# Neocron mob/NPC tracker migration

## Objective
Migrate the useful tracking pattern from AOSharp's DynelManager and
MonsterTracker into this Neocron client: enumerate live nearby actors, identify
NPCs separately from players where verified, and display names, positions and
distances with a text filter and refreshable tracking selection.

## Scope
Read-only native entity access for the same fingerprinted Evolution 2.5.902
client supported by PlayerReader. Do not reuse AO offsets, network schemas or
identity enums. Trace Neocron's actual actor registry and name/position access.
Do not infer hostility or invent health/level data. Unknown classifications must
remain unknown. Do not add attack or follow actions in this iteration.

## Implementation and validation
1. Trace actor container, identity, type, name and position getters in the local
   executable; independently inspect live records.
2. Add shared entity snapshots and filtering/tracking logic in Core; expose a
   bounded snapshot reader through the native backend.
3. Add a live tracker window, search/filter, nearest-first distances and a
   selected tracked entity. Preserve navigation controls.
4. Test filtering, identity replacement, invalid/stale reads, caps and empty
   snapshots. Build/publish and compare live snapshots with sensible NPC data.

Build/test commands are the same as README.md. Add a read-only --entities CLI
diagnostic. Treat unreadable/mutating registry data as unavailable and clear the
display rather than showing stale entities as current.

## First implementation completed
The default window is now a live tracker with a searchable, nearest-first NPC
list, radius filter, heading-relative radar, instance selection, coordinates,
appearance/disappearance counts, pause/topmost and JSON export. Navigation is
available from its own button. The exact supported native mapping, AOSharp
pattern correspondence, test evidence and remaining gaps are documented in
TRACKER-MIGRATION.md. Live verified: 60 named scripted NPCs, including the user's
COPBOT, plus 10 explicitly unclassified character records. Health was added in
the expansion below; targeting, follow and combat remain outside this iteration.

## Expanded per-NPC data
Add verified native current/max HP with HUD-equivalent bounds, rank, faction,
dead flag, template ID, weapon and armor IDs. Preserve raw HP in JSON because
client regeneration can exceed its local maximum. Read rank and stats from the
NPC, not guessed from its name or another game's enums. Resolve faction/weapon
names and AI/dialog script references from the running install's local compressed
definition files; label reference data separately from live readings and allow
missing definitions without losing native telemetry. Unmapped character types
must retain null stats. Add bounds, corrupt-stat/string, compressed-file and
definition-join coverage, verify real COPBOT/Small Spider values, then publish
and reopen the app. No game input or attacks are needed for this work.

Completed: native stats and optional definition enrichment, list/detail/export
updates, 50 passing tests, live JSON and window verification of a rank-120
City Administration COPBOT with 15,168/15,168 client HP and weapon 1651.
The displayed health follows the verified game HUD clamp; raw values remain
available in tooltips and JSON. Current server health and effective attack-rate
units are not claimed. See TRACKER-MIGRATION.md for the evidence and limitations.

## Native sector map completed
The initial radar is replaced by the game's sector images with verified native
world ID, map orientation and projection. Zoom/pan/fit/player/selection centering,
names and height filter are implemented. Map art is read from the local PAK;
no game files are changed. The milky gray theme is applied to tracker/navigation.
See MAP-SPEC.md for native evidence and map behavior. There are 61 passing tests;
live Plaza SEC-1 verification currently shows 77 NPC markers.
