# Offline catalog provenance

## Construction

data/construction_catalog.json contains 1,263 item entries in 38 categories, retrieved 26 October 2026. Its sources array records the 23 available category listings from https://db.techhaven.org/en/; unavailable_categories lists pages that could not be retrieved. Known part names from the sourced recycling catalog supplement category coverage. The supplied WP7, WP9 and Holy Heal examples provide their construction material names.

These are item facts and source references, not copied guide prose or a claim of 1,263 verified construction recipes. Other category listings do not provide material lists or prove blueprint availability, so ingredients is null and method is check_blueprint. Users need an actual matching blueprint and supplies. No missing quantities/materials were invented. The 85 rare-part references and recycled-only entries cannot be loaded into the blueprint executor. Each record retains its source URL and status note.

The browse catalog is separate from the saved recipe book. Selecting/favoriting a supported entry saves only its name for existing tooltip verification; it does not add every catalog row to live recognition.

## Recycling

Snapshot retrieved 26 October 2026. Data contains recipe facts (item names, ingredient names/quantities, listed tech levels and source references), not copied guide prose.

- 161 primary entries: https://db.techhaven.org/en/item-lists/recyclable
- 40 additional entries/variants: https://neocron.fandom.com/wiki/Recycling_Recipes
- General mechanics: https://wiki.techhaven.org/Recycle
- Incomplete Swamp Shaman Trophy note: https://neocron-game.com/patch-notes

Primary DB entries take precedence over overlapping legacy spellings. Supplemental entries retain a legacy verification note; some names/ingredient variants may refer to the same current item. Two source-listed Cypherhelmet variants are retained as legacy alternatives, not silently treated as confirmed equivalent recipes. No current-game verification or universal completeness is claimed.

The official Swamp Shaman Trophy description does not publish exact ingredient identity/quantity. It is in known_incomplete metadata, not the executable recipe list. No missing quantities were invented.

The runtime reads this local JSON only. Opening a source link is an explicit user action; normal startup and macro execution do not fetch recipe pages.
