using NeocronSharp.Core;

internal static class QuestTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        var catalog = new QuestCatalog();
        test("Quest index resolves NPC, objectives and reward from local data", () =>
        {
            var shaman = catalog.Search("Sorcha Nox", "Structured mission").Single(e => e.Id == "shamantrophy.mission.decontaminate_remains");
            check(shaman.Contact == "Sorcha Nox", "NPC must resolve by template");
            check(shaman.Details.Contains("Kri'nakh Shaman") && shaman.Details.Contains("Kri'nakh Poisongland") &&
                  shaman.Details.Contains("Swamp Shaman Remains"), "Objective and reward item IDs must resolve to names");
            check(shaman.Details.Contains("Collect 5 × Kri'nakh Poisongland") && shaman.Source.Contains("shamantrophy"), "Show the quantity in plain language");
            check(shaman.Conversation.Contains("Your response:") && !shaman.Details.Contains("npc_type:"), "Present conversation and objectives without raw YAML");
        });
        test("Quest search finds prerequisites and source branches without claiming completion", () =>
        {
            var engineer = catalog.Search("cooling plasma", "Structured mission").Single(e => e.Id == "nc_engineer.mission2");
            check(engineer.Details.Contains("Replacement part acquisition"), "Show the prerequisite mission by name");
            var gun = catalog.Search("woc_bigbadgun", "Lua quest script").Single();
            check(gun.Dialogue.Contains("GETBASERANK()") && gun.Dialogue.Contains("result >=55") &&
                gun.Dialogue.Contains("STARTMISSION(MISSION1)"), "Keep rank condition and dialogue context");
            check(gun.Details.Contains("base rank: at least 55") && gun.Conversation.Contains("NPC:") && !gun.Conversation.Contains("SAY(\""), "Present rank and spoken dialogue in readable form");
            check(gun.Note.Contains("conditional", StringComparison.OrdinalIgnoreCase), "Branches must be labeled as conditional");
        });
        test("Legacy Lua item exchanges read as possible outcomes", () =>
        {
            var tsunami = catalog.Search("antsunami01", "Lua quest script").Single();
            check(tsunami.Details.Contains("ITEMS THE NPC MAY ASK FOR") && tsunami.Details.Contains("Secret Info"), "Show conditional item exchange");
            check(tsunami.Details.Contains("LOCATION CLUES") && tsunami.Details.Contains("J08"), "Show actual dialogue location clue");
            check(tsunami.Conversation.Contains("Your response:") && !tsunami.Details.Contains("SCRIPT NOTES"), "Keep code out of readable views");
        });
        test("Quest category filters and multiple search terms work", () =>
        {
            check(catalog.Entries.Count(e => e.Category == "Structured mission") >= 100, "Structured coverage");
            check(catalog.Entries.Count(e => e.Category == "Lua quest script") >= 300, "Script coverage");
            check(catalog.Search("sorcha poisongland", "Structured mission").Any(e => e.Id == "shamantrophy.mission.decontaminate_remains"), "Search across fields");
            check(!catalog.Search("sorcha", "Lua quest script").Any(e => e.Category == "Structured mission"), "Category filter");
            check(catalog.Issues.Count == 0, "Source index had parse issues");
        });
    }
}
