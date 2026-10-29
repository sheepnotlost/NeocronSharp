using System.Diagnostics;
using System.Numerics;
using DotRecast.Core;
using DotRecast.Detour.Io;
using DotRecast.Recast.Toolset;
using DotRecast.Recast.Toolset.Builder;
using DotRecast.Recast.Toolset.Geom;

namespace NavmeshPrototype;

/// <summary>
/// The navmesh of a wasteland cell. A cell is 32768 units square: at the city settings (4-unit
/// voxels, one solo mesh) a bake ran past 5 minutes. Here the voxels are 32 units (the heightfield
/// itself is sampled every 64), the mesh is built in 16 tiles, and the result is cached in
/// logs/terrain/ until the cell's files change, so only the first trip through a cell waits.
/// </summary>
internal static class TerrainNav
{
    /// <summary>Bump when the settings or the cell geometry change, so old caches are not used.</summary>
    private const int Version = 7;   // 7: props from the cell's spawn file cut out (SectorObjects)

    public static string CacheDirectory => Path.Combine(Travel.Home, "logs", "terrain");

    public static RcNavMeshBuildSettings Settings() => new()
    {
        cellSize = 16f, cellHeight = 8f,
        // Slopes up to 55 degrees count as walkable (a guess: at 45 thin 1-sample ridges, 4-8% of a cell,
        // cut every cell into pockets). A 55-degree slope rises 46 units per 32-unit voxel: the climb
        // must allow that or every slope is a ledge.
        agentHeight = 72f, agentRadius = 16f, agentMaxClimb = 48f, agentMaxSlope = 55f,
        minRegionSize = 16, mergedRegionSize = 64,
        edgeMaxLen = 512f, edgeMaxError = 2f, vertsPerPoly = 6,
        detailSampleDist = 6f, detailSampleMaxError = 2f,
        filterLowHangingObstacles = true, filterLedgeSpans = true, filterWalkableLowHeightSpans = true,
        tiled = true, tileSize = 512,
    };

    private static readonly Dictionary<string, NavWorld> Loaded = new();

    public static NavWorld Bake(string install, int id, IReadOnlyList<Vector3>? obstacles = null)
    {
        string key = CacheKey(install, id, obstacles);
        lock (Loaded) if (Loaded.TryGetValue(key, out var known)) return known;
        var clock = Stopwatch.StartNew();
        var cell = TerrainCell.Load(install, id);
        string name = new NeocronSharp.Core.EnvironmentCatalog(install).Areas.FirstOrDefault(a => a.WorldId == id)?.Name ?? $"cell {cell.Code}";
        var world = cell.World(name);
        var settings = Settings();
        string file = Path.Combine(CacheDirectory, $"nav-{id}-{key}.bin");
        DotRecast.Detour.DtNavMesh? mesh = null;
        if (File.Exists(file))
        {
            try
            {
                using var reader = new BinaryReader(File.OpenRead(file));
                mesh = new DtMeshSetReader().Read(reader, settings.vertsPerPoly);
            }
            catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException or IndexOutOfRangeException) { mesh = null; }
        }
        if (mesh == null)
        {
            var src = world.StaticGeometry;
            float[] verts = new float[src.Vertices.Length * 3];
            for (int i = 0; i < src.Vertices.Length; i++) { verts[3 * i] = src.Vertices[i].X; verts[3 * i + 1] = src.Vertices[i].Y; verts[3 * i + 2] = src.Vertices[i].Z; }
            // Floors wind clockwise seen from above (as in GBSP): flip for Recast.
            int[] faces = new int[src.Triangles.Length];
            for (int i = 0; i < faces.Length; i += 3) { faces[i] = src.Triangles[i]; faces[i + 1] = src.Triangles[i + 2]; faces[i + 2] = src.Triangles[i + 1]; }
            var geometry = new DemoInputGeomProvider(verts, faces);
            foreach (var o in obstacles ?? Array.Empty<Vector3>())
            {
                const float half = 40;
                float[] square = { o.X - half, o.Y, o.Z - half, o.X + half, o.Y, o.Z - half, o.X + half, o.Y, o.Z + half, o.X - half, o.Y, o.Z + half };
                geometry.AddConvexVolume(square, o.Y - 80, o.Y + 160, new DotRecast.Recast.RcAreaModification(0));
            }
            // Rocks, crates, barrels and tree trunks from the cell's spawn file (not in the heightfield).
            try
            {
                foreach (var prop in SectorObjects.ReadDat(install, Path.Combine(install, "terrain", $"pak_{cell.Code}.dat")).Props)
                    geometry.AddConvexVolume(SectorObjects.Outline(prop), prop.Bottom - 32, prop.Top, new DotRecast.Recast.RcAreaModification(0));
            }
            catch (Exception e) when (e is IOException or InvalidDataException) { }
            var result = new TileNavMeshBuilder().Build(geometry, settings);
            if (!result.Success || result.NavMesh == null) throw new InvalidOperationException($"Navmesh bake failed for {name}.");
            mesh = result.NavMesh;
            try
            {
                Directory.CreateDirectory(CacheDirectory);
                string temp = file + ".tmp";
                using (var writer = new BinaryWriter(File.Create(temp))) new DtMeshSetWriter().Write(writer, mesh, RcByteOrder.LITTLE_ENDIAN, false);
                File.Move(temp, file, overwrite: true);
            }
            catch (IOException) { }
        }
        var nav = NavWorld.FromMesh(world, mesh, settings, clock.Elapsed);
        lock (Loaded) Loaded[key] = nav;
        return nav;
    }

    /// <summary>True when the cell's navmesh is already baked and cached (a trip through it will not wait).</summary>
    public static bool IsCached(string install, int id) => File.Exists(Path.Combine(CacheDirectory, $"nav-{id}-{CacheKey(install, id, null)}.bin"));

    // The cell's files (size and time), the settings version and the obstacles cut out of it.
    private static string CacheKey(string install, int id, IReadOnlyList<Vector3>? obstacles)
    {
        string code = TerrainCell.CodeOf(id);
        var parts = new List<string> { $"v{Version}" };
        foreach (var ext in new[] { "tfl", "dat" })
        {
            var info = new FileInfo(Path.Combine(install, "terrain", $"pak_{code}.{ext}"));
            parts.Add(info.Exists ? $"{info.Length}:{info.LastWriteTimeUtc.Ticks}" : "-");
        }
        foreach (var o in obstacles ?? Array.Empty<Vector3>()) parts.Add(FormattableString.Invariant($"{o.X:F0},{o.Y:F0},{o.Z:F0}"));
        var hash = System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(string.Join("|", parts)));
        return Convert.ToHexString(hash, 0, 6).ToLowerInvariant();
    }
}
