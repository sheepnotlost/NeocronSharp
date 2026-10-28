using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;

namespace NeocronSharp.Core;

public sealed record SectorTelemetry(int WorldId, int? MapRotationDegrees);

public sealed record SectorMapDefinition(int WorldId, string Name, int BitmapId, string AssetPath,
    Vector2 BitmapReference, Vector2 WorldReference, float Scale)
{
    public Vector2 Project(Vector3 world, int compassMapRotation)
    {
        if (!float.IsFinite(world.X) || !float.IsFinite(world.Z) || !float.IsFinite(Scale) || Scale <= 0 ||
            !float.IsFinite(WorldReference.X) || !float.IsFinite(WorldReference.Y) ||
            !float.IsFinite(BitmapReference.X) || !float.IsFinite(BitmapReference.Y))
            throw new InvalidOperationException("Invalid sector-map coordinates.");
        // Same transform as RPOSMAPWINDOW RVA 0x134bfd..0x134cc3.
        float angle = (compassMapRotation - 90) * MathF.PI / 180;
        float x = world.X - WorldReference.X, z = world.Z - WorldReference.Y;
        return BitmapReference + new Vector2(MathF.Cos(angle) * x - MathF.Sin(angle) * z,
            MathF.Sin(angle) * x + MathF.Cos(angle) * z) * Scale;
    }
}

public sealed class SectorMapCatalog
{
    private readonly Dictionary<int, SectorMapDefinition> _maps = new();
    private readonly Dictionary<int, string> _names = new();
    public int Count => _maps.Count;
    public SectorMapDefinition? Find(int worldId) => _maps.GetValueOrDefault(worldId);
    public string Name(int worldId) => _names.GetValueOrDefault(worldId, $"Sector {worldId}");
    public SectorMapCatalog(string install)
    {
        var worlds = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_worldinfo.csv")));
        foreach (var row in worlds) _names[row.Key] = row.Value["Name"];
        string resources = NpcDefinitions.DecodeText(File.ReadAllBytes(Path.Combine(install, "gfx", "pak_gfx.ini")));
        var bitmaps = new Dictionary<int, string>();
        foreach (Match match in Regex.Matches(resources, "(?im)^\\s*set\\s+(\\d+)\\s+\"(gfx[\\\\/]maps[\\\\/][^\"]+)\"[^\\r\\n]*$"))
            bitmaps[int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture)] = match.Groups[2].Value.Replace('\\', '/');
        var maps = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_maps.csv")));
        int Int(Dictionary<string, string> row, string key) => int.Parse(row[key], CultureInfo.InvariantCulture);
        float Real(Dictionary<string, string> row, string key) => float.Parse(row[key], CultureInfo.InvariantCulture);
        foreach (var row in maps.Values)
        {
            int world = Int(row, "WorldId"), bitmap = Int(row, "BitmapId");
            float scale = Real(row, "Scale");
            float refX = Real(row, "WorldRefX"), refZ = Real(row, "WorldRefZ");
            if (!float.IsFinite(scale) || scale <= 0 || scale > 100 || !float.IsFinite(refX) || !float.IsFinite(refZ) || !bitmaps.TryGetValue(bitmap, out var path)) continue;
            _maps.TryAdd(world, new(world, Name(world), bitmap, path,
                new(Int(row, "BitmapRefX"), Int(row, "BitmapRefY")), new(refX, refZ), scale));
        }
    }
}
