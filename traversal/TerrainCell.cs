using System.Buffers.Binary;
using System.Numerics;
using System.Text;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// One wasteland cell ("E 07 - MOUNTAINS", world 2087), read from the client's own files:
/// <list type="bullet">
/// <item><c>terrain\pak_e_07.tfl</c>: a "VF00" container (zlib, like every pak_ file) whose
/// directory ("DT01", at the offset in header bytes 12-15) holds 256 JPEG texture tiles,
/// <c>qtree.dat</c> (render LOD) and <c>map.dat</c>: the heightfield, 512 x 512 u16 after a
/// 4-byte size header; height = value / 4. Sample (i, j) sits at x = -16384 + 64 i, z = -16384 + 64 j.</item>
/// <item><c>terrain\pak_e_07.dat</c>: the cell's spawn file. Record 1000008 places a BSP model
/// (buildings, rocks, and the "terrainchange" entrances whose WorldChanges are the cell's doors);
/// record 1000003 places small props (plants, stones).</item>
/// <item><c>terrain\pak_e_07.bsp</c> is only a sky box: no floor, no exits.</item>
/// </list>
/// Cells sit on a grid: world id = 2000 + 20 * row + column, row A = 0 at the north (+z),
/// column 01 at the west (-x). Walking off an edge zones into the neighbour, which shares it.
/// </summary>
internal sealed class TerrainCell
{
    public const int Samples = 512;
    public const float Spacing = 64, Half = Samples * Spacing / 2;   // 32768-unit cells, centred on 0
    public const int FirstId = 2000, Columns = 20;

    public int Id { get; }
    public string Code { get; }   // "e_07"
    public float[] Heights { get; }
    public IReadOnlyList<Placement> Placements { get; }
    public IReadOnlyList<Vector3> Props { get; }

    /// <summary>A BSP model placed in the cell, with its static geometry and exits already moved into cell space.</summary>
    public sealed record Placement(string Model, Vector3 Position, float Yaw, EnvironmentMesh? Mesh, IReadOnlyList<EnvironmentFeature> Exits, Vector3 Offset = default);

    private TerrainCell(int id, string code, float[] heights, List<Placement> placements, List<Vector3> props)
    { Id = id; Code = code; Heights = heights; Placements = placements; Props = props; }

    public static int Row(int id) => (id - FirstId) / Columns;
    public static int Column(int id) => (id - FirstId) % Columns;
    public static int IdAt(int row, int column) => FirstId + row * Columns + column;
    public static string CodeOf(int id) => $"{(char)('a' + Row(id))}_{Column(id):D2}";

    /// <summary>The cell's heightfield file, or null when this world id is not a terrain cell on disk.</summary>
    public static string? TflPath(string install, int id)
    {
        if (id < FirstId || id >= FirstId + 12 * Columns || Column(id) == 0) return null;
        string path = Path.Combine(install, "terrain", $"pak_{CodeOf(id)}.tfl");
        return File.Exists(path) ? path : null;
    }

    public static bool Exists(string install, int id) => TflPath(install, id) != null;

    /// <summary>Terrain height at a cell-space point (bilinear), clamped to the cell.</summary>
    public float Height(float x, float z) => Sample(Heights, x, z);

    public static float Sample(float[] heights, float x, float z)
    {
        float fi = Math.Clamp((x + Half) / Spacing, 0, Samples - 1.001f), fj = Math.Clamp((z + Half) / Spacing, 0, Samples - 1.001f);
        int i = (int)fi, j = (int)fj; float u = fi - i, v = fj - j;
        float a = heights[j * Samples + i], b = heights[j * Samples + i + 1], c = heights[(j + 1) * Samples + i], d = heights[(j + 1) * Samples + i + 1];
        return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v;
    }

    /// <summary>Just the heightfield (fast: no models). Used for the wasteland-wide planning grid.</summary>
    public static float[] ReadHeights(string install, int id)
    {
        string path = TflPath(install, id) ?? throw new FileNotFoundException($"No terrain for world {id}.");
        byte[] file = Decode(File.ReadAllBytes(path));
        if (file.Length < 28 || !file.AsSpan(0, 4).SequenceEqual("VF00"u8)) throw new InvalidDataException("Unrecognised terrain file.");
        var (offset, size) = Directory(file)["map.dat"];
        if (size < 4 + Samples * Samples * 2 || offset + size > file.Length) throw new InvalidDataException("Terrain heightfield has the wrong size.");
        if (BinaryPrimitives.ReadUInt16LittleEndian(file.AsSpan(offset)) != Samples || BinaryPrimitives.ReadUInt16LittleEndian(file.AsSpan(offset + 2)) != Samples)
            throw new InvalidDataException("Terrain heightfield is not 512 x 512.");
        var heights = new float[Samples * Samples];
        for (int k = 0; k < heights.Length; k++) heights[k] = BinaryPrimitives.ReadUInt16LittleEndian(file.AsSpan(offset + 4 + 2 * k)) / 4f;
        return heights;
    }

    // The VF00 directory: "DT01", then entries of (u32 name length, name, 12 bytes, u32 size, u32 offset, 12 bytes).
    private static Dictionary<string, (int Offset, int Size)> Directory(byte[] file)
    {
        int at = (int)BinaryPrimitives.ReadUInt32LittleEndian(file.AsSpan(12));
        if (at < 28 || at + 8 > file.Length || !file.AsSpan(at, 4).SequenceEqual("DT01"u8)) throw new InvalidDataException("Terrain directory missing.");
        var map = new Dictionary<string, (int, int)>(StringComparer.OrdinalIgnoreCase);
        int p = at + 8;
        while (p + 4 < file.Length)
        {
            int length = BinaryPrimitives.ReadInt32LittleEndian(file.AsSpan(p));
            if (length is >= 2 and <= 64 && p + 4 + length + 20 <= file.Length && file[p + 3 + length] == 0)
            {
                string name = Encoding.Latin1.GetString(file, p + 4, length - 1);
                if (name.All(c => c > 32 && c < 127))
                {
                    int q = p + 4 + length + 12;
                    map[name] = (BinaryPrimitives.ReadInt32LittleEndian(file.AsSpan(q + 4)), BinaryPrimitives.ReadInt32LittleEndian(file.AsSpan(q)));
                    p = q + 20;
                    continue;
                }
            }
            p++;
        }
        return map;
    }

    private static byte[] Decode(byte[] bytes)
    {
        try { return NpcDefinitions.DecodeBytes(bytes); }
        catch (InvalidDataException) { return bytes; }
    }

    private static readonly Dictionary<string, EnvironmentWorld?> Models = new(StringComparer.OrdinalIgnoreCase);
    private static GamePakArchive? _worldsPak;

    /// <summary>A placed model's BSP (worlds\terrainchange\..., worlds\terrainbsp\...), loose pak_ file first, then worlds.pak.</summary>
    private static EnvironmentWorld? Model(string install, string relative)
    {
        lock (Models)
        {
            if (Models.TryGetValue(relative, out var known)) return known;
            EnvironmentWorld? world = null;
            try
            {
                string full = Path.GetFullPath(Path.Combine(install, relative.Replace('/', Path.DirectorySeparatorChar)));
                string local = Path.Combine(Path.GetDirectoryName(full)!, "pak_" + Path.GetFileName(full));
                byte[] bytes;
                if (File.Exists(local)) bytes = Decode(File.ReadAllBytes(local));
                else if (File.Exists(full)) bytes = File.ReadAllBytes(full);
                else
                {
                    _worldsPak ??= new GamePakArchive(Path.Combine(install, "worlds.pak"));
                    bytes = _worldsPak.ReadWorld(relative.StartsWith("worlds/", StringComparison.OrdinalIgnoreCase) ? relative[7..] : relative);
                }
                world = BspEnvironment.Read(bytes, 0, relative, relative);
            }
            catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException) { world = null; }
            return Models[relative] = world;
        }
    }

    /// <summary>Read a cell: heightfield, placed models (with their exits) and props.</summary>
    public static TerrainCell Load(string install, int id)
    {
        var heights = ReadHeights(install, id);
        string code = CodeOf(id);
        var placements = new List<Placement>(); var props = new List<Vector3>();
        string dat = Path.Combine(install, "terrain", $"pak_{code}.dat");
        if (File.Exists(dat))
            foreach (var (type, e) in WorldObjects.Elements(Decode(File.ReadAllBytes(dat))))
            {
                if (type == PlacedModel && e.Length > 48)
                {
                    // i32, position, a second vector (not a translation: models fit the ground far better without it),
                    // u32 path length, rotation (degrees; [9] = yaw), u32, path.
                    var position = V(e, 4);
                    float yaw = BitConverter.ToSingle(e, 36);
                    int length = BitConverter.ToInt32(e, 28);
                    if (length < 2 || 48 + length > e.Length) continue;
                    // Some paths carry stray bytes after the name (E 13's canyon2terrain.bsp): stop at the first NUL or blank.
                    string path = Encoding.Latin1.GetString(e, 48, length).Split('\0')[0].Trim().TrimStart('.', '\\').Replace('\\', '/');
                    var model = Model(install, path);
                    if (model == null) { placements.Add(new(path, position, yaw, null, Array.Empty<EnvironmentFeature>(), V(e, 16))); continue; }
                    var mesh = new EnvironmentMesh(model.StaticGeometry.Vertices.Select(v => Place(v, position, yaw)).ToArray(), WithoutHull(model.StaticGeometry));
                    string name = Path.GetFileNameWithoutExtension(path);
                    var exits = model.Summary.Features.Where(f => f.Kind == "WorldChange")
                        .Select(f => new EnvironmentFeature(f.Kind, $"{f.Name}@{name}", Place(f.Position, position, yaw), f.Properties)).ToList();
                    placements.Add(new(path, position, yaw, mesh, exits, V(e, 16)));
                }
                else if (type == Prop && e.Length >= 12) props.Add(V(e, 0));
            }
        return new(id, code, heights, placements, props);
    }

    private const uint PlacedModel = 1000008, Prop = 1000003;

    /// <summary>
    /// A BSP model is a sealed level: a box (floor, ceiling, four walls) at its bounds encloses it. Placed
    /// on the terrain that box would wall in the whole model (the A 07 city exit became an island), so
    /// every triangle lying flat on one of the bounding planes is dropped.
    /// </summary>
    internal static int[] WithoutHull(EnvironmentMesh mesh)
    {
        var v = mesh.Vertices;
        if (v.Length == 0) return mesh.Triangles;
        float minX = v.Min(p => p.X), maxX = v.Max(p => p.X), minY = v.Min(p => p.Y), maxY = v.Max(p => p.Y), minZ = v.Min(p => p.Z), maxZ = v.Max(p => p.Z);
        bool On(int a, int b, int c, Func<Vector3, float> axis, float plane) =>
            MathF.Abs(axis(v[a]) - plane) < 1 && MathF.Abs(axis(v[b]) - plane) < 1 && MathF.Abs(axis(v[c]) - plane) < 1;
        var kept = new List<int>(mesh.Triangles.Length);
        for (int i = 0; i + 2 < mesh.Triangles.Length; i += 3)
        {
            int a = mesh.Triangles[i], b = mesh.Triangles[i + 1], c = mesh.Triangles[i + 2];
            if (On(a, b, c, p => p.X, minX) || On(a, b, c, p => p.X, maxX) || On(a, b, c, p => p.Y, minY) || On(a, b, c, p => p.Y, maxY)
                || On(a, b, c, p => p.Z, minZ) || On(a, b, c, p => p.Z, maxZ)) continue;
            kept.Add(a); kept.Add(b); kept.Add(c);
        }
        return kept.ToArray();
    }

    private static Vector3 V(byte[] e, int at) => new(BitConverter.ToSingle(e, at), BitConverter.ToSingle(e, at + 4), BitConverter.ToSingle(e, at + 8));

    /// <summary>A model-space point placed in the cell: turned about the vertical by <paramref name="yaw"/> degrees, then moved.</summary>
    public static Vector3 Place(Vector3 local, Vector3 position, float yaw)
    {
        if (yaw == 0) return local + position;
        float a = yaw * MathF.PI / 180, c = MathF.Cos(a), s = MathF.Sin(a);
        return new Vector3(local.X * c + local.Z * s, local.Y, -local.X * s + local.Z * c) + position;
    }

    /// <summary>Every door out of the cell (the WorldChanges of its placed entrance models), in cell space.</summary>
    public IEnumerable<EnvironmentFeature> Exits => Placements.SelectMany(p => p.Exits);

    /// <summary>
    /// The cell as a world for the navmesh: the heightfield as triangles (every
    /// <paramref name="step"/>-th sample) plus every placed model's static geometry, and the exits.
    /// </summary>
    public EnvironmentWorld World(string name, int step = 1)
    {
        int n = (Samples - 1) / step + 1;
        var verts = new List<Vector3>(n * n);
        for (int j = 0; j < n; j++)
            for (int i = 0; i < n; i++)
            {
                int si = Math.Min(i * step, Samples - 1), sj = Math.Min(j * step, Samples - 1);
                verts.Add(new(-Half + si * Spacing, Heights[sj * Samples + si], -Half + sj * Spacing));
            }
        var tris = new List<int>((n - 1) * (n - 1) * 6);
        // Wound like GBSP floors (clockwise from above): NavWorld flips every triangle for Recast.
        for (int j = 0; j + 1 < n; j++)
            for (int i = 0; i + 1 < n; i++)
            {
                int a = j * n + i, b = a + 1, c = a + n, d = c + 1;
                tris.AddRange(new[] { a, b, c, b, d, c });
            }
        foreach (var p in Placements.Where(p => p.Mesh != null))
        {
            int baseIndex = verts.Count;
            verts.AddRange(p.Mesh!.Vertices);
            tris.AddRange(p.Mesh.Triangles.Select(t => t + baseIndex));
        }
        var features = Exits.ToList();
        var summary = new EnvironmentSummary(Id, name, $"terrain/{Code}", verts.Count, tris.Count / 3, Placements.Count, 0, 0, features.Count, features);
        return new(summary, new(verts.ToArray(), tris.ToArray()));
    }
}
