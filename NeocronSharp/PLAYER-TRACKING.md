# Nearby player tracking and gear inspection

October 27, 2026. Targets the fingerprinted Evolution 2.5.902 x64 client.

The Name column is bold in all skins. Verified remote players are included by
default in the same searchable, nearest-first list as NPCs. A checked Players
filter controls their visibility. Type is near the front; player map markers
are blue diamonds. The local character remains the separate You marker.

Players appear as their client actor and appearance records become available.
The existing 500 ms snapshot refresh removes records that unload. Exact
(-32000,-32000,-32000) network placeholders are excluded. A missing record may
mean leaving the zone, disconnecting or leaving client update range; the tracker
does not claim to distinguish those causes or enumerate unseen zone occupants.
Changing sectors invalidates old selections even if object addresses are reused.

Double-click a player or use Inspect player. The window refreshes the selected
instance's published gear and clears it on unload/disconnect/sector change. It
does not silently attach to a returning address: select the player again.

Available player data: name, HUD rank pair, faction, Soul Light, clan ID/rank code,
alive/dead, position, distance, direction and height. Gear includes three visible
weapon references with local name, TL, base range, magazine and shots/burst; body,
torso and leg appearance models; texture selectors; and four appearance attachments.
Exports include all 19 available native scalar appearance values without assigning
speculative meanings to the remaining values.

This is published appearance data, not a full inventory inspection. Weapon
display slots do not establish which weapon is currently drawn. Visual power
armor can be identified by its model asset, but this does not establish its exact
item variant or effective protection. Helmet/vest/pants/boots inventory records,
implants, quickbelt contents, backpack, item condition/mod slots, remaining ammo,
resistances and player HP are not verified and are not invented.

## Read-only native evidence

LSTPLAYER physics vtable RVA 0x5bbbb8 shares position getter 0x248270 and dead
getter 0x19d420. Its dispatch thunk is 0x2e7178. Physics+0x608 points to
PLAYERAPPMGR, vtable 0x5c5d90. Getter slot 0x38 is 0x3dfa50; slot 0x40 is
0x3dfa20. No game functions are invoked; all getters are inspected statically
and their data read externally with query/read permissions.

Appearance manager: uint16 scalar count at +8, scalar-array pointer at +0x10;
uint16 blob count at +0x18, blob-array pointer at +0x20. Both arrays have 16-byte
entries. Scalar values are float32 at entry+0. Blob pointer is entry+0 and
uint16 byte length is entry+8. Limits: 64 scalars, 16 blobs, 192 name bytes.
Names are terminated Latin-1 text in blob 1, not the NPC std::string layout.

Target-description handler 0x1a221a–0x1a2344 reads rank fields 6/7, encoded Soul
Light 5 (HUD byte conversion corresponds to raw minus 128), faction 8, and clan
blob 3. Clan's high 28 bits are ID, low four bits rank code. The target display
also uses scalar 18; this remains unlabelled in exported appearance values.

Handler 0x19a0f1–0x19a1cd passes scalars 10–12 to 0x1a2fc0 as three weapon
display slots; that handler uses weapon-definition lookup 0xdb730. Value 65535
means none published. Scalars 13–16 feed model attachments through 0x1a2e10.
Blob 0 holds the body model at byte 0, texture selectors at 2/5/8, torso model
at 11 and leg model at 13; 0x19a065–0x19a0bd copies these fields. These must not
be interpreted as weapon IDs. Model resources resolve only within [PLAYER] in
models/pak_models.ini; [STATIC]/[ITEM]/[WEAPON] reuse the same numeric IDs.

Live examples read during discovery included Hobagi, Ryker Ekisrai, Angel Of Light
and Maxe. The client published STEINER FP 1.0 / Tangent Pulselaser Cannon references
and SpyArmor_Gold / MESH_SPYPOWERA_YELLOW appearance resources in those records.
Names and gear were obtained from memory and local definitions, not OCR.

## Validation

79 automated tests cover existing navigation/NPC/map behavior plus player name
decoding, no NPC-stat leakage, corrupt appearance bounds, snapshot mutation,
sentinel exclusion, default inclusion, unload/sector invalidation, no automatic
selection rebind and correct resource namespaces. Live UI evidence is generated
with --smoke-ui --ui-evidence --player-evidence. It checks default population,
search/filtering, bold names, selection, the gear window and clearing on unload.
No combat, targeting or game movement input is part of this update.

