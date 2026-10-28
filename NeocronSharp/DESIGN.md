# NeocronSharp design

## Theme
Skin 1 uses soft matte cream surfaces with charcoal text, modest borders and
a subdued sage selection. Ten optional period skins use original Winamp-inspired
metal/LCD, leather, amber, blue OEL, CRT and Aqua materials. Preserve the native
game-map geometry while toning its grayscale art to the selected palette.
Use color plus shape to distinguish the player, NPCs and the selected NPC.

## Palette
Basic sRGB: window #E5DFD2, panels #EBE6DA, inputs #F0EBDF, border #B7AE9B,
ink #343129, secondary #625B4E, selection #D2D7C6, accent #405A4B.
All eleven palette definitions live in SkinCatalog.cs and are applied by AppTheme.
NPC dots use a dark warm accent against the map, player uses slate blue, and
selected NPCs use a conspicuous outline; none of these imply hostility.

## Typography and layout
Segoe UI, 10 pt body; 20 pt main heading; compact 9 pt supporting text.
Consistent 8/12/20 px spacing, standard focus states and flat bordered buttons.
Give the sector map substantial space rather than squeezing it into the old
radar footprint. Support fit-to-map, zoom, pan and selecting NPC markers.
Use a resizable pane so the user can trade table space for map space.
Keep numeric client HP and named weapon at the front of the table. Additional
attributes remain in the scrollable selection details. Update cells in place and
only change sector-title text when the sector name changes. Avoid blinking chrome.

## Expansion surfaces — Operate
Loot library: search creatures or desired item/rule names, compare template-specific
candidate rules and export. Keep special-generation and unverified-odds notes visible.
Environment mapper: inspect real geometry/points/exits, show authored points on the
current map, export navigation inputs and inspect explicit sector links. Clearly
state that collision-aware local paths and seamless movement are still pending.
The skin selector always retains an easy return to basic #1 and persists locally.

## Player inspection
Names are bold in the first column. Player rows participate in the same default
search and nearest-first list, with a Players toggle enabled by default and Type
near the front. Blue diamond map markers distinguish players from NPC circles.
Double-click or Inspect player opens a live gear/appearance view; unload clears
old values. Label visual appearance separately from exact item stats/inventory.
