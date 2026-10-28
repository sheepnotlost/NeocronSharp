# Quest inspector

Open NeocronSharp and select **Quests** at the top. Search by a quest name, NPC, item, place, mission ID, or words in dialogue. The selector limits the list to mission guides or other quest dialogue. Select an entry to inspect its requirements, objectives and rewards; **Dialogue** displays the NPC's words and possible responses. **Original source** is available for technical inspection.

From the Tracker tab, select a loaded NPC and choose **NPC quests** to search its name. A match is reference evidence, not a guarantee that the NPC currently offers that quest.

The included catalog is indexed from this Neocron installation's client files: 184 structured mission entries and 503 mission-related Lua scripts. All 184 structured entries have resolved source NPC names; 190 Lua files link to named NPC definitions and 310 contain resolved item operations. A Lua file can describe multiple missions or conditional alternatives, and structured files can share dialogue between missions. Server availability, progress, inventory, and exact map locations are not live. Legacy, event, or inactive scripts can be present.

Mission guides turn recognized objectives and item IDs into readable steps. Dialogue-only entries summarize item exchanges, costs and rank checks that can be identified, and quote possible location clues; some alternatives or conditions cannot be resolved automatically. The original source is preserved with line numbers. The app never executes game scripts. A source path and starting line are included for each result.

To regenerate the embedded catalog when Neocron updates, run Python 3:

```
python tools/build_quest_catalog.py "C:\Users\Kainen\Documents\Neocron AoSharp\Neocron Evolution 2.5" src/NeocronSharp.Core/QuestCatalogData.json
dotnet publish src/NeocronSharp/NeocronSharp.csproj -c Release -o dist
```

The generator reads the local files and requires only Python's standard library. Rebuilding the catalog and application is necessary to see updated game definitions; the included index does not update automatically.
