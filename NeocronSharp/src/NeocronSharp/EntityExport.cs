using System.Text.Json;
using NeocronSharp.Core;

namespace NeocronSharp;

internal static class EntityExport
{
    public static string Json(EntitySnapshot snapshot, int processId) => JsonSerializer.Serialize(new
    {
        status = "read-only-ok", snapshot.CapturedAt, processId,
        supportedSha256 = PlayerReader.SupportedSha256, snapshot.RegistryEntries,
        sector = snapshot.Sector,
        npcCount = snapshot.Entities.Count(e => e.Identity.Kind == EntityKind.Npc),
        playerCount = snapshot.Entities.Count(e => e.Identity.Kind == EntityKind.Player),
        unclassifiedCharacterCount = snapshot.Entities.Count(e => e.Identity.Kind == EntityKind.UnclassifiedCharacter),
        player = new { snapshot.PlayerPosition.X, snapshot.PlayerPosition.Y, snapshot.PlayerPosition.Z },
        entities = EntityQuery.Nearby(snapshot, includeUnclassified: true).Select(row => new
        {
            row.Entity.Name, kind = row.Entity.Identity.Kind.ToString(), row.Entity.NativeClass,
            liveNpcStats = row.Entity.Stats, localDefinition = row.Entity.ReferenceData,
            playerDetails = row.Entity.Player,
            nativeKey = row.Entity.Identity.Key, instance = $"{row.Entity.Identity.Node:x}:{row.Entity.Identity.Physics:x}",
            position = new { row.Entity.Position.X, row.Entity.Position.Y, row.Entity.Position.Z },
            row.Distance, row.GroundDistance, bearingDegreesRight = row.Bearing, row.Height
        })
    }, new JsonSerializerOptions { WriteIndented = true });
}
