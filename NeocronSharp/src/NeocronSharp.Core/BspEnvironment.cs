using System.Buffers.Binary;
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;

namespace NeocronSharp.Core;

public sealed record EnvironmentFeature(string Kind, string Name, Vector3 Position, IReadOnlyDictionary<string, string> Properties);
public sealed record EnvironmentArea(int WorldId, string Name, string AssetPath);
public sealed record EnvironmentSummary(int WorldId, string Name, string Source, int Vertices, int Faces, int Models,
    int GroundPoints, int AirPoints, int Transitions, IReadOnlyList<EnvironmentFeature> Features, string? Error = null);
public sealed record EnvironmentMesh(Vector3[] Vertices, int[] Triangles);
public sealed record EnvironmentWorld(EnvironmentSummary Summary, EnvironmentMesh StaticGeometry);

public static class BspEnvironment
{
    private sealed record Chunk(int Offset, int Size, int Count);
    public static EnvironmentWorld Read(byte[] file, int worldId, string name, string source)
    {
        if (file.Length < 40 || file.Length > 64 * 1024 * 1024) throw new InvalidDataException("Invalid BSP size.");
        var chunks = new Dictionary<int, Chunk>(); int at = 0;
        while (at <= file.Length - 12)
        {
            int type = I(at), size = I(at + 4), count = I(at + 8); at += 12;
            long length = (long)size * count;
            if (size < 0 || count < 0 || length > file.Length - at || chunks.Count > 64) throw new InvalidDataException("Invalid BSP chunk bounds.");
            if (type == 65535) break;
            if (!chunks.TryAdd(type, new(at, size, count))) throw new InvalidDataException("Duplicate BSP chunk.");
            at += (int)length;
        }
        var header = Need(0, 28);
        if (!file.AsSpan(header.Offset, 4).SequenceEqual("GBSP"u8)) throw new InvalidDataException("Unsupported world format.");
        int version = I(header.Offset + 8);
        if (version is < 15 or > 17) throw new InvalidDataException($"Unsupported GBSP version {version}.");
        var entities = Need(16, 1); var features = new List<EnvironmentFeature>();
        using (var input = new MemoryStream(file, entities.Offset, entities.Count, false))
        using (var reader = new BinaryReader(input, Encoding.Latin1))
        {
            int count = reader.ReadInt32(); if (count is < 0 or > 100000) throw new InvalidDataException("Invalid entity count.");
            string Text()
            {
                int length = reader.ReadInt32();
                if (length is < 1 or > 65536 || length > input.Length - input.Position) throw new InvalidDataException("Invalid entity property.");
                byte[] bytes = reader.ReadBytes(length); if (bytes[^1] != 0) throw new InvalidDataException("Unterminated entity text.");
                return Encoding.Latin1.GetString(bytes, 0, bytes.Length - 1);
            }
            for (int i = 0; i < count; i++)
            {
                int props = reader.ReadInt32(); if (props is < 0 or > 2048) throw new InvalidDataException("Invalid entity property count.");
                var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                for (int j = 0; j < props; j++) { string key = Text(); values[key] = Text(); }
                string kind = values.GetValueOrDefault("classname", "");
                if (!new[] { "GroundPathPoint", "AirPathPoint", "WorldChange", "ModelController", "DeathMatchStart" }.Contains(kind)) continue;
                if (!values.TryGetValue("Origin", out var origin)) continue;
                string[] parts = origin.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length != 3 || !parts.All(v => float.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out float f) && float.IsFinite(f))) continue;
                features.Add(new(kind, values.GetValueOrDefault("%name%", kind), new(float.Parse(parts[0], CultureInfo.InvariantCulture), float.Parse(parts[1], CultureInfo.InvariantCulture), float.Parse(parts[2], CultureInfo.InvariantCulture)), values));
            }
            if (input.Position != input.Length) throw new InvalidDataException("Trailing BSP entity data.");
        }
        var vertices = Need(14, 12); var indices = Need(13, 4); var faces = Need(11, 36); var models = Need(1, 80);
        if (vertices.Count > 2_000_000 || faces.Count > 2_000_000 || indices.Count > 8_000_000 || models.Count < 1) throw new InvalidDataException("World geometry exceeds limits.");
        var points = new Vector3[vertices.Count];
        for (int i = 0; i < points.Length; i++)
        {
            int offset = vertices.Offset + i * 12;
            points[i] = new(BitConverter.ToSingle(file, offset), BitConverter.ToSingle(file, offset + 4), BitConverter.ToSingle(file, offset + 8));
            if (!float.IsFinite(points[i].X) || !float.IsFinite(points[i].Y) || !float.IsFinite(points[i].Z)) throw new InvalidDataException("Nonfinite geometry vertex.");
        }
        // Model zero is the static world. Moving doors/models are deliberately
        // retained as separate metadata rather than baked as permanently open.
        int firstFace = I(models.Offset + 44), faceCount = I(models.Offset + 48);
        if (firstFace < 0 || faceCount < 0 || firstFace > faces.Count - faceCount) throw new InvalidDataException("Invalid static-model face range.");
        var triangles = new List<int>();
        for (int i = firstFace; i < firstFace + faceCount; i++)
        {
            int offset = faces.Offset + i * 36, first = I(offset), count = I(offset + 4);
            if (first < 0 || count < 3 || count > 4096 || first > indices.Count - count) throw new InvalidDataException("Invalid face index range.");
            int Index(int j)
            { int v = I(indices.Offset + (first + j) * 4); if (v < 0 || v >= points.Length) throw new InvalidDataException("Invalid vertex index."); return v; }
            for (int j = 1; j < count - 1; j++) { triangles.Add(Index(0)); triangles.Add(Index(j)); triangles.Add(Index(j + 1)); }
        }
        var summary = new EnvironmentSummary(worldId, name, source, vertices.Count, faces.Count, models.Count,
            features.Count(f => f.Kind == "GroundPathPoint"), features.Count(f => f.Kind == "AirPathPoint"), features.Count(f => f.Kind == "WorldChange"), features);
        return new(summary, new(points, triangles.ToArray()));
        int I(int offset) => BinaryPrimitives.ReadInt32LittleEndian(file.AsSpan(offset, 4));
        Chunk Need(int type, int size) => chunks.TryGetValue(type, out var value) && value.Size == size ? value : throw new InvalidDataException($"Missing or incompatible BSP chunk {type}.");
    }
}

public sealed class EnvironmentCatalog
{
    private readonly string _install;
    private readonly GamePakArchive? _archive;
    private readonly Dictionary<int, EnvironmentSummary> _summaries = new();
    public IReadOnlyList<EnvironmentArea> Areas { get; }
    public IReadOnlyCollection<EnvironmentSummary> Scanned => _summaries.Values;
    public EnvironmentCatalog(string install)
    {
        _install = Path.GetFullPath(install);
        var info = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_worldinfo.csv")));
        string resources = NpcDefinitions.DecodeText(File.ReadAllBytes(Path.Combine(install, "worlds", "pak_worlds.ini")));
        var paths = new Dictionary<int, string>();
        foreach (Match match in Regex.Matches(resources, "(?im)^\\s*set\\s+(\\d+)\\s+\"([^\"]+\\.bsp)\""))
            paths[int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture)] = match.Groups[2].Value.Replace('\\', '/').TrimStart('.', '/');
        Areas = info.Where(i => paths.ContainsKey(i.Key) || !string.IsNullOrWhiteSpace(i.Value.GetValueOrDefault("DatPathOverride")))
            // DAT overrides change entity/spawn data, not the BSP geometry filename.
            .Select(i => new EnvironmentArea(i.Key, i.Value["Name"], paths.TryGetValue(i.Key, out var bsp)
                ? bsp : Path.ChangeExtension(i.Value["DatPathOverride"].Replace('\\', '/').TrimStart('.', '/'), ".bsp")))
            .OrderBy(a => a.Name, StringComparer.OrdinalIgnoreCase).ThenBy(a => a.WorldId).ToArray();
        string pak = Path.Combine(install, "worlds.pak"); if (File.Exists(pak)) _archive = new(pak);
    }
    public EnvironmentWorld Load(int worldId) => Load(worldId, out _);
    /// <summary>Loads a world and returns the SHA-256 (hex) of its decoded BSP bytes, e.g. to key a cache derived from the geometry.</summary>
    public EnvironmentWorld Load(int worldId, out string sourceSha256)
    {
        var area = Areas.FirstOrDefault(a => a.WorldId == worldId) ?? throw new InvalidDataException("No world asset is defined for this area.");
        string full = Path.GetFullPath(Path.Combine(_install, area.AssetPath.Replace('/', Path.DirectorySeparatorChar)));
        if (!full.StartsWith(_install + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("World path escapes the install.");
        string local = Path.Combine(Path.GetDirectoryName(full)!, "pak_" + Path.GetFileName(full)); byte[] bytes;
        if (File.Exists(local)) bytes = NpcDefinitions.DecodeBytes(File.ReadAllBytes(local));
        else if (File.Exists(full)) bytes = File.ReadAllBytes(full);
        else if (_archive != null) bytes = _archive.ReadWorld(area.AssetPath.StartsWith("worlds/") ? area.AssetPath[7..] : area.AssetPath);
        else throw new FileNotFoundException("World BSP asset is unavailable.");
        sourceSha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes));
        var world = BspEnvironment.Read(bytes, area.WorldId, area.Name, area.AssetPath); _summaries[worldId] = world.Summary; return world;
    }
    public void ScanAll(Action<int, int, string>? progress = null, CancellationToken token = default)
    {
        int count = 0;
        foreach (var area in Areas)
        {
            token.ThrowIfCancellationRequested();
            try { _ = Load(area.WorldId); }
            catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException)
            { _summaries[area.WorldId] = new(area.WorldId, area.Name, area.AssetPath, 0, 0, 0, 0, 0, 0, Array.Empty<EnvironmentFeature>(), e.Message); }
            progress?.Invoke(++count, Areas.Count, area.Name);
        }
    }
    public int[] WorldRoute(int from, int to)
    {
        if (from == to) return new[] { from };
        var previous = new Dictionary<int, int> { [from] = from }; var queue = new Queue<int>(); queue.Enqueue(from);
        while (queue.TryDequeue(out int current))
        {
            if (!_summaries.TryGetValue(current, out var summary)) continue;
            foreach (var feature in summary.Features.Where(f => f.Kind == "WorldChange"))
                if (int.TryParse(feature.Properties.GetValueOrDefault("NextLevel"), out int next) && next > 0 && previous.TryAdd(next, current))
                {
                    if (next == to) { var path = new List<int> { next }; while (path[^1] != from) path.Add(previous[path[^1]]); path.Reverse(); return path.ToArray(); }
                    queue.Enqueue(next);
                }
        }
        return Array.Empty<int>();
    }
    public static void ExportObj(EnvironmentWorld world, string path)
    {
        using var writer = new StreamWriter(path); writer.WriteLine("# Static world geometry; navigation input, not a validated walkability mesh.");
        foreach (var v in world.StaticGeometry.Vertices) writer.WriteLine(FormattableString.Invariant($"v {v.X} {v.Y} {v.Z}"));
        var triangles = world.StaticGeometry.Triangles;
        for (int i = 0; i < triangles.Length; i += 3) writer.WriteLine($"f {triangles[i] + 1} {triangles[i + 1] + 1} {triangles[i + 2] + 1}");
    }
}
