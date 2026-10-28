using System.Text.Json;

namespace NeocronSharp.Core;

/// <summary>Reference evidence extracted from the installed client, not live mission state.</summary>
public sealed record QuestEntry(string Id, string Title, string Category, string Contact,
    string Description, string Details, string Conversation, string Dialogue, string Source, int Line, string Note);

public sealed class QuestCatalog
{
    private sealed record CatalogData(int Version, QuestEntry[] Entries, string[] Issues);
    public IReadOnlyList<QuestEntry> Entries { get; }
    public IReadOnlyList<string> Issues { get; }

    public QuestCatalog()
    {
        using var input = typeof(QuestCatalog).Assembly.GetManifestResourceStream("NeocronSharp.Core.QuestCatalogData.json")
            ?? throw new InvalidDataException("Quest catalog resource is missing.");
        var data = JsonSerializer.Deserialize<CatalogData>(input, new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
            ?? throw new InvalidDataException("Quest catalog is empty.");
        if (data.Version != 1 || data.Entries == null || data.Issues == null)
            throw new InvalidDataException("Quest catalog version is unsupported.");
        Entries = data.Entries.OrderBy(e => e.Category != "Structured mission").ThenBy(e => e.Title, StringComparer.OrdinalIgnoreCase).ThenBy(e => e.Id, StringComparer.Ordinal).ToArray();
        Issues = data.Issues;
    }

    public IEnumerable<QuestEntry> Search(string query, string? category = null)
    {
        string[] terms = query.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        return Entries.Where(e => category is null || e.Category == category).Where(e => terms.All(term =>
            e.Title.Contains(term, StringComparison.OrdinalIgnoreCase) || e.Id.Contains(term, StringComparison.OrdinalIgnoreCase) ||
            e.Contact.Contains(term, StringComparison.OrdinalIgnoreCase) || e.Description.Contains(term, StringComparison.OrdinalIgnoreCase) ||
            e.Details.Contains(term, StringComparison.OrdinalIgnoreCase) || e.Conversation.Contains(term, StringComparison.OrdinalIgnoreCase) || e.Dialogue.Contains(term, StringComparison.OrdinalIgnoreCase) ||
            e.Source.Contains(term, StringComparison.OrdinalIgnoreCase)));
    }
}
