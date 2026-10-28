namespace NeocronSharp.Core;

public sealed record PlayerGear(string Slot, int? DefinitionId, string? Name = null, int? TechLevel = null,
    float? BaseRange = null, int? MagazineSize = null, int? ShotsPerBurst = null, string? Asset = null);

public sealed record PlayerDetails(int? RankFirst, int? RankSecond, int? FactionId, string? FactionName,
    int? SoulLight, int? ClanId, int? ClanRank, bool? Dead, IReadOnlyList<PlayerGear> Gear,
    IReadOnlyDictionary<int, float> AppearanceValues)
{
    public string RankText => $"{RankFirst?.ToString() ?? "—"} / {RankSecond?.ToString() ?? "—"}";
    public string WeaponText => string.Join("; ", Gear.Where(g => g.Slot.StartsWith("Visible weapon") && g.DefinitionId.HasValue)
        .Select(g => g.Name ?? $"Weapon #{g.DefinitionId}"));
    public const string Coverage = "Client-published appearance data. Visible weapon slots and models are not a complete inventory. " +
        "Armor item names/condition, implants, quickbelt, backpack and player HP are unavailable. A model identifies appearance, not exact armor stats.";
}
