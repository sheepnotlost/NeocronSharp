using System.Numerics;

namespace NeocronSharp.Core;

public enum EntityKind { Npc, UnclassifiedCharacter, Player }

// Neocron hash keys are not globally unique: different actor classes can share one.
public readonly record struct EntityIdentity(ulong World, ulong Registry, ulong Node, ulong Physics, int Key, EntityKind Kind);
public sealed record WorldEntity(EntityIdentity Identity, string Name, Vector3 Position, string NativeClass,
    NpcStats? Stats = null, NpcReferenceData? ReferenceData = null, PlayerDetails? Player = null);
public sealed record EntitySnapshot(DateTimeOffset CapturedAt, ulong World, ulong Registry,
    Vector3 PlayerPosition, Vector3 PlayerForward, IReadOnlyList<WorldEntity> Entities, int RegistryEntries, SectorTelemetry? Sector = null);
public sealed record NearbyEntity(WorldEntity Entity, float Distance, float GroundDistance, float Bearing, float Height);

public static class EntityQuery
{
    public static NearbyEntity Describe(WorldEntity entity, Vector3 player, Vector3 forward)
    {
        var delta = entity.Position - player;
        float ground = MathF.Sqrt(delta.X * delta.X + delta.Z * delta.Z);
        // Same heading convention as the verified navigation backend: X/Z ground, Y up.
        float bearing = ground < 0.001f ? 0 : MathF.Atan2(
            forward.X * delta.Z - forward.Z * delta.X,
            forward.X * delta.X + forward.Z * delta.Z) * 180 / MathF.PI;
        return new(entity, delta.Length(), ground, bearing, delta.Y);
    }

    public static IReadOnlyList<NearbyEntity> Nearby(EntitySnapshot snapshot, string search = "", float radius = 0,
        bool includeUnclassified = false)
    {
        if (!float.IsFinite(radius) || radius < 0) throw new ArgumentOutOfRangeException(nameof(radius));
        return snapshot.Entities
            .Where(e => includeUnclassified || e.Identity.Kind != EntityKind.UnclassifiedCharacter)
            .Where(e => e.Name.Contains(search.Trim(), StringComparison.OrdinalIgnoreCase))
            .Select(e => Describe(e, snapshot.PlayerPosition, snapshot.PlayerForward))
            .Where(e => radius == 0 || e.Distance <= radius)
            .OrderBy(e => e.Distance).ThenBy(e => e.Entity.Name, StringComparer.OrdinalIgnoreCase)
            .ThenBy(e => e.Entity.Identity.Node).ToArray();
    }
}

/// <summary>Selection follows a concrete live actor, never a name or reused numeric key.</summary>
public sealed class EntityTracking
{
    private Dictionary<EntityIdentity, WorldEntity> _previous = new();
    private bool _hasBaseline;
    private (ulong World, ulong Registry, int? Sector) _session;
    public WorldEntity? Tracked { get; private set; }
    public bool Lost { get; private set; }
    public int Appeared { get; private set; }
    public int Disappeared { get; private set; }
    public void Track(WorldEntity entity) { Tracked = entity; Lost = false; }
    public void Clear() { Tracked = null; Lost = false; }
    public void Unavailable()
    {
        if (Tracked != null) Lost = true;
        _previous.Clear(); _hasBaseline = false;
        Appeared = Disappeared = 0;
    }
    public void Update(EntitySnapshot snapshot)
    {
        var session = (snapshot.World, snapshot.Registry, snapshot.Sector?.WorldId);
        bool changed = _hasBaseline && session != _session;
        if (changed && Tracked != null) Lost = true;
        var current = snapshot.Entities.ToDictionary(e => e.Identity);
        Appeared = _hasBaseline && !changed ? current.Keys.Count(k => !_previous.ContainsKey(k)) : 0;
        Disappeared = _hasBaseline && !changed ? _previous.Keys.Count(k => !current.ContainsKey(k)) : 0;
        if (Tracked != null && !Lost)
        {
            if (current.TryGetValue(Tracked.Identity, out var live) && live.NativeClass == Tracked.NativeClass && live.Name == Tracked.Name)
                Tracked = live;
            else Lost = true;
        }
        // A lost selection requires a new user selection, even if an address is reused later.
        _previous = current; _session = session; _hasBaseline = true;
    }
}
