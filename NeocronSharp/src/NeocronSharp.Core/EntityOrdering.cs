namespace NeocronSharp.Core;

public enum EntitySortColumn { Name, Type, Rank, HitPoints, Weapon, HealthPercent, Distance, Faction, Direction }

public static class EntityOrdering
{
    public static NearbyEntity[] Sort(IEnumerable<NearbyEntity> rows, EntitySortColumn column, bool descending = false)
    {
        var result = rows.ToArray();
        Array.Sort(result, (a, b) =>
        {
            var x = a.Entity; var y = b.Entity;
            int comparison = column switch
            {
                EntitySortColumn.Name => Text(x.Name, y.Name),
                EntitySortColumn.Type => Text(Type(x), Type(y)),
                EntitySortColumn.Rank => Number(x.Player?.RankFirst ?? x.Stats?.Rank, y.Player?.RankFirst ?? y.Stats?.Rank),
                EntitySortColumn.HitPoints => Number(x.Stats?.Health?.Current, y.Stats?.Health?.Current),
                EntitySortColumn.Weapon => Text(Weapon(x), Weapon(y)),
                EntitySortColumn.HealthPercent => Number(x.Stats?.Health?.Percent, y.Stats?.Health?.Percent),
                EntitySortColumn.Distance => Number(a.Distance, b.Distance),
                EntitySortColumn.Faction => Text(Faction(x), Faction(y)),
                EntitySortColumn.Direction => Number(a.Bearing, b.Bearing),
                _ => throw new ArgumentOutOfRangeException(nameof(column))
            };
            if (comparison == 0 && column == EntitySortColumn.Rank)
                comparison = Number(x.Player?.RankSecond ?? 0, y.Player?.RankSecond ?? 0);
            if (comparison == 0 && column == EntitySortColumn.HitPoints)
                comparison = Number(x.Stats?.Health?.Maximum, y.Stats?.Health?.Maximum);
            // Stable secondary keys keep equal values from jumping between refreshes.
            if (comparison == 0) comparison = StringComparer.OrdinalIgnoreCase.Compare(x.Name, y.Name);
            if (comparison == 0) comparison = a.Distance.CompareTo(b.Distance);
            if (comparison == 0) comparison = x.Identity.Node.CompareTo(y.Identity.Node);
            if (comparison == 0) comparison = x.Identity.Physics.CompareTo(y.Identity.Physics);
            return comparison;
        });
        return result;

        int Number(double? a, double? b)
        {
            if (a.HasValue && !double.IsFinite(a.Value)) a = null;
            if (b.HasValue && !double.IsFinite(b.Value)) b = null;
            if (!a.HasValue || !b.HasValue) return a.HasValue ? -1 : b.HasValue ? 1 : 0;
            return descending ? b.Value.CompareTo(a.Value) : a.Value.CompareTo(b.Value);
        }
        int Text(string? a, string? b)
        {
            if (string.IsNullOrWhiteSpace(a)) a = null;
            if (string.IsNullOrWhiteSpace(b)) b = null;
            if (a == null || b == null) return a != null ? -1 : b != null ? 1 : 0;
            return descending ? StringComparer.OrdinalIgnoreCase.Compare(b, a) : StringComparer.OrdinalIgnoreCase.Compare(a, b);
        }
    }

    private static string Type(WorldEntity entity) => entity.Identity.Kind switch { EntityKind.Npc => "NPC", EntityKind.Player => "Player", _ => "Unknown" };
    private static string? Weapon(WorldEntity entity) => entity.Player is { } player ? player.WeaponText :
        entity.ReferenceData?.WeaponName ?? (entity.Stats is { } stats ? stats.WeaponId == 0 ? "None / unarmed" : $"Weapon #{stats.WeaponId}" : null);
    private static string? Faction(WorldEntity entity)
    {
        if (entity.Player is { } player) return player.FactionName ?? player.FactionId?.ToString();
        return entity.ReferenceData?.FactionName ?? (entity.Stats?.FactionId is { } id ? id == 0 ? "Unspecified (0)" : $"Faction #{id}" : null);
    }
}
