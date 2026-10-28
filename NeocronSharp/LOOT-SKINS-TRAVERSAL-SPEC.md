# Loot library, period skins and environment mapping

Keep basic layout as skin 1, now soft matte cream. Add ten selectable, persisted
Winamp-era styles based on documented popular period references: Classic 2.x,
MMD3, Bento, Sputnik, Leather Box, XP Metallic, Pioneer OEL, Matrix Xtream,
iBDE HiFi and WinAqua. These are original adaptations for this tool, not a .wsz
player or a claim of importing the original authors' packages. Add purposeful
metal/LCD chrome, themed controls and readable data surfaces, keeping all
existing functionality and a simple way back to basic.

Build a searchable local loot library for all enabled NPC templates possible.
Join NPC ItemContainerId -> item-container child rows -> direct item IDs or
negative loot-group references -> named item candidates. Preserve original rule
chance/quality values; do not label them as per-kill percentages. Container zero
is not evidence that a service NPC drops the table-zero fallback contents. Label
client reference data separately from actual corpse contents and server rules.
Provide selected-NPC lookup, offline NPC/item search, coverage counts and export.

Investigate AOSharp's terrain/room mesh, Recast generation, local corridor paths
and inter-playfield links. Investigate the Neocron GBSP world data, retaining
geometry, authored path points, doors and world transitions for as many areas as
possible. Expose a useful environment-data inventory and map overlay. Route
previews or movement must not silently use visual-map pixels or unverified
nearest-neighbor edges as walkable space. Document what is extracted and what
still requires collision/navmesh and traversal validation before macros can
claim seamless travel. Preserve the existing navigation behavior during this work.
