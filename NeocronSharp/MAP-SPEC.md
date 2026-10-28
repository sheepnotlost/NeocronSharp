# Native sector map and milky gray theme

Replace the abstract radar with Neocron's local sector-map art and accurately
project the player and loaded NPCs using the game's coordinate mapping. Match
the user's requested milky gray appearance across tracker and navigation.

## Behavior
- Read the current world ID and map orientation from verified native fields.
- Join pak_maps.csv with pak_worldinfo.csv and the map bitmap resources in
  gfx/pak_gfx.ini; read the original grayscale BMP from gfx.pak without changing
  the game installation or distributing its map assets.
- Match the game map's reference point, scale and rotation, preserving aspect
  ratio through resizing. Do not estimate alignment from a screenshot.
- Show all filtered, in-bounds NPC positions, the player's heading arrow and a
  selected marker. Clicking selects the same live actor as the table.
- Provide fit, player/selected centering, wheel/button zoom, drag pan, optional
  labels, and an explicit height ±48 filter. Hollow markers indicate height
  differences; colors do not mean hostility or line of sight.
- Sector changes reset the view. Missing assets/orientation or unavailable
  telemetry must not reuse another sector's map or stale markers. No client map
  is invented for a sector that lacks one. Existing NPC stats remain usable.
- Use a resizable table/map split. Put scrollable NPC detail under the list so
  the map has enough space. Apply consistent milky gray surfaces, charcoal text,
  subdued selection and bordered controls to both windows.

## Native evidence
- WORLDCLIENT complete object +0x258 is the world ID. Its +0x30 dispatch
  subobject handles message 0x2779 at RVA 0x548157, reading subobject+0x228.
- WORLDCLIENT+0x80 -> RPOSCONSOLE (vtable RVA 0x587398), +0x30 -> BASERPOS
  (0x587418), +0x148 -> RPOSCOMPASS (0x5917b8), +0x1bc -> map rotation.
  Live Plaza-1 value: 270 degrees. RPOSMAPWINDOW constructor stores that compass
  at +0xd0; its drawing code reads this rotation at RVA 0x134bfd.
- RPOSMAP setup RVA 0x132272 copies BitmapRefX/Y, WorldRefX/Z and Scale into
  helper fields +0x274/+0x278/+0x27c/+0x280/+0x284. Live values independently
  match Plaza-1's CSV: (195,204), (-3248,-2767), 0.028.
- Projection RVA 0x134c0c..0x134cc3 uses theta=(rotation−90)*pi/180:
  u=BitmapRefX+Scale*(cos(theta)*dx−sin(theta)*dz),
  v=BitmapRefY+Scale*(sin(theta)*dx+cos(theta)*dz), where dx=X−WorldRefX and
  dz=Z−WorldRefZ. Height Y is not part of this ground-plan projection.
- Resource 2001 resolves to gfx/maps/plaza_p1_sm.bmp. The map art matches the
  supplied screenshot, including the numbered exits and A/B landmarks.
- PAK: magic 0x3d458cde, uint32 entry count, variable index records consisting
  of record size, data offset, compressed size, uncompressed size, name length,
  null-terminated name. Entry payloads use zlib. Header/index/range/expansion
  bounds are checked; only the requested map entry is decompressed.

## Validation
61 tests total, including projection anchors/orientation, the known COPBOT point,
height independence, invalid coordinates, aspect ratio, pan/picking, zoom anchors
and limits, catalog namespaces, unsupported maps and malformed archives. The
live window verifies the native map, player projection, marker hit testing and
clearing disconnected data in addition to the existing NPC checks. Sector ID
changes invalidate tracking even when native roots/addresses are reused. Plaza SEC-1
has been live-verified; other sector assets/configurations are supported through
the same catalog but have not all been visited. Read-only; no game input sent.

All 161 catalog map references have also been resolved and their BMP headers /
compressed lengths checked independently. Eight terrain map images are local
compressed pak_ overrides, including L_08, which is absent from gfx.pak itself.
The runtime honors those local overrides before consulting the archive.
Neutral text contrast was checked numerically: main ink 10.2–14:1 and muted
text 4.98–6.81:1 across the committed backgrounds and selection surface.
