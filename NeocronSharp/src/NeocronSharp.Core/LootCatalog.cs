using System.Globalization;

namespace NeocronSharp.Core;

public sealed record LootNpc(int TemplateId, string Name, int Rank, int FactionId, int ContainerId);
public sealed record LootItem(int ItemId, string Name, int TechLevel, string RuleSource, int ChanceRaw, float QualityFactor)
{
    public string OutputRule => QualityFactor < 0 ? "Special generation: base item reference; not proof of a finished-item drop" : "Item candidate";
}
public sealed record LootRule(int ReferenceId, string Source, int ChanceRaw, float QualityFactor, int CandidateCount);
public sealed record LootTable(int TemplateId, int ContainerId, int? ItemsAtOnce, int? RespawnTimeRaw,
    string Status, IReadOnlyList<LootItem> Items, IReadOnlyList<LootRule> Rules);

public sealed class LootCatalog
{
    public IReadOnlyList<LootNpc> Npcs { get; }
    private readonly Dictionary<int, Dictionary<string, string>> _items, _containers, _groups;
    private readonly Dictionary<int, List<Dictionary<string, string>>> _children;
    private readonly Dictionary<int, LootItem[]> _groupItems = new();
    private readonly Dictionary<int, LootTable> _cache = new();
    public int NpcsWithContainer => Npcs.Count(n => n.ContainerId > 0);
    public int ContainerCount => _containers.Count;
    public int ItemCount => _items.Count;
    public const string SourceNote = "Local client loot definitions; possible candidates, not actual corpse contents or verified per-kill odds. Server, rank and script rules can change outcomes.";

    public LootCatalog(string install)
    {
        var directory = Path.Combine(install, "definitions");
        Dictionary<int, Dictionary<string, string>> Table(string file) => NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(directory, file)));
        var npcs = Table("pak_npcs.csv"); var characters = Table("pak_characters.csv");
        _items = Table("pak_items.csv"); _containers = Table("pak_itemcontainers.csv"); _groups = Table("pak_itemgroups.csv");
        _children = NpcDefinitions.ParseRows(File.ReadAllBytes(Path.Combine(directory, "pak_itemcontainerchildren.csv")))
            .GroupBy(r => I(r, "EntryId")).ToDictionary(g => g.Key, g => g.ToList());
        Npcs = npcs.Select(pair =>
        {
            var row = pair.Value; int model = I(row, "ModelTargetValue");
            string name = I(row, "ModelTargetType") == 1 && characters.TryGetValue(model, out var character) ? character["Name"] : $"NPC template {pair.Key}";
            return new LootNpc(pair.Key, name, I(row, "Skill"), I(row, "FactionId"), I(row, "ItemContainerId"));
        }).OrderBy(n => n.Name, StringComparer.OrdinalIgnoreCase).ThenBy(n => n.Rank).ThenBy(n => n.TemplateId).ToArray();
        foreach (var group in _items.GroupBy(x => I(x.Value, "LootGroupId")))
            _groupItems[group.Key] = group.Select(x => new LootItem(x.Key, x.Value["Name"], I(x.Value, "TechLevel"), "", 0, 0)).ToArray();
    }
    private static int I(Dictionary<string, string> row, string key) => int.Parse(row[key], CultureInfo.InvariantCulture);
    private static float F(Dictionary<string, string> row, string key) => float.Parse(row[key], CultureInfo.InvariantCulture);

    public LootTable Get(int templateId)
    {
        if (_cache.TryGetValue(templateId, out var cached)) return cached;
        var npc = Npcs.FirstOrDefault(n => n.TemplateId == templateId);
        if (npc == null) return new(templateId, 0, null, null, "NPC template not present in local definitions.", Array.Empty<LootItem>(), Array.Empty<LootRule>());
        if (npc.ContainerId <= 0) return _cache[templateId] = new(templateId, npc.ContainerId, null, null,
            "No standard loot container is assigned. This does not rule out script or mission rewards.", Array.Empty<LootItem>(), Array.Empty<LootRule>());
        _containers.TryGetValue(npc.ContainerId, out var container);
        var items = new List<LootItem>(); var rules = new List<LootRule>();
        foreach (var row in _children.GetValueOrDefault(npc.ContainerId) ?? new())
        {
            int reference = I(row, "Id"), chance = I(row, "Chance"); float quality = F(row, "Quality");
            if (!float.IsFinite(quality) || Math.Abs((long)reference) > int.MaxValue) continue;
            string source;
            LootItem[] candidates;
            if (reference < 0)
            {
                int group = -reference; source = _groups.TryGetValue(group, out var name) ? $"Group {group}: {name["Name"]}" : $"Loot group {group}";
                candidates = _groupItems.GetValueOrDefault(group) ?? Array.Empty<LootItem>();
            }
            else
            {
                source = "Direct item";
                candidates = _items.TryGetValue(reference, out var item)
                    ? new[] { new LootItem(reference, item["Name"], I(item, "TechLevel"), "", 0, 0) }
                    : new[] { new LootItem(reference, $"Unresolved item #{reference}", 0, "", 0, 0) };
            }
            rules.Add(new(reference, source, chance, quality, candidates.Length));
            items.AddRange(candidates.Select(c => c with { RuleSource = source, ChanceRaw = chance, QualityFactor = quality }));
            if (items.Count > 100000) throw new InvalidDataException("Loot candidate limit exceeded.");
        }
        return _cache[templateId] = new(templateId, npc.ContainerId, container == null ? null : I(container, "ItemsAtOnce"),
            container == null ? null : I(container, "RespawnTime"), rules.Count == 0 ? "Assigned container has no local child rules." : SourceNote,
            items.OrderBy(i => i.Name, StringComparer.OrdinalIgnoreCase).ThenBy(i => i.RuleSource).ToArray(), rules);
    }

    public IReadOnlyList<LootNpc> Search(string query, bool onlyAssigned = false)
    {
        string term = query.Trim();
        return Npcs.Where(n => !onlyAssigned || n.ContainerId > 0).Where(n => term.Length == 0 ||
            n.Name.Contains(term, StringComparison.OrdinalIgnoreCase) || n.TemplateId.ToString().Contains(term) ||
            (n.ContainerId > 0 && Get(n.TemplateId).Items.Any(i => i.Name.Contains(term, StringComparison.OrdinalIgnoreCase) || i.RuleSource.Contains(term, StringComparison.OrdinalIgnoreCase)))).ToArray();
    }
}
