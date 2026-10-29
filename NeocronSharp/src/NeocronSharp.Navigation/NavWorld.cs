using System.Diagnostics;
using System.Numerics;
using DotRecast.Core;
using DotRecast.Core.Numerics;
using DotRecast.Detour;
using DotRecast.Detour.Io;
using DotRecast.Recast.Toolset;
using DotRecast.Recast.Toolset.Builder;
using DotRecast.Recast.Toolset.Geom;
using NeocronSharp.Core;

namespace NeocronSharp.Navigation;

/// <summary>A baked Neocron world: a Recast navmesh over the static level geometry (model zero) plus the Detour
/// queries a walker needs. Y is up; positions are the game's world units (telemetry Y is the feet).</summary>
public sealed class NavWorld
{
    public EnvironmentWorld World { get; }
    public DtNavMesh Mesh { get; }
    public RcNavMeshBuildSettings Settings { get; }
    /// <summary>How long the Recast bake took; zero when the mesh came from the cache.</summary>
    public TimeSpan BakeTime { get; }
    private readonly DtNavMeshQuery _query;
    private readonly DtQueryDefaultFilter _filter = new();
    public static readonly Vector3 Extents = new(32, 128, 32), WideExtents = new(96, 256, 96);

    private NavWorld(EnvironmentWorld world, DtNavMesh mesh, RcNavMeshBuildSettings settings, TimeSpan bakeTime)
    { World = world; Mesh = mesh; Settings = settings; BakeTime = bakeTime; _query = new(mesh); }

    // Agent size in Neocron world units. First guesses, not measured: telemetry Y is the feet,
    // a Plaza 1 corridor floor-to-ceiling is ~224.
    public static RcNavMeshBuildSettings DefaultSettings() => new()
    {
        cellSize = 4f, cellHeight = 2f,
        agentHeight = 72f, agentRadius = 16f, agentMaxClimb = 24f, agentMaxSlope = 45f,
        minRegionSize = 8, mergedRegionSize = 20,
        edgeMaxLen = 48f, edgeMaxError = 1.3f, vertsPerPoly = 6,
        detailSampleDist = 6f, detailSampleMaxError = 1f,
        filterLowHangingObstacles = true, filterLedgeSpans = true, filterWalkableLowHeightSpans = true,
        tiled = false,
    };

    /// <summary>Text that changes whenever a setting that shapes the mesh changes (part of the cache key).</summary>
    public static string Fingerprint(RcNavMeshBuildSettings s) => FormattableString.Invariant(
        $"v1|{s.cellSize}|{s.cellHeight}|{s.agentHeight}|{s.agentRadius}|{s.agentMaxClimb}|{s.agentMaxSlope}|{s.minRegionSize}|{s.mergedRegionSize}|") +
        FormattableString.Invariant($"{s.edgeMaxLen}|{s.edgeMaxError}|{s.vertsPerPoly}|{s.detailSampleDist}|{s.detailSampleMaxError}|") +
        FormattableString.Invariant($"{s.filterLowHangingObstacles}|{s.filterLedgeSpans}|{s.filterWalkableLowHeightSpans}|{s.tiled}|{s.partitioning}");

    /// <summary>Bakes a navmesh from a world's static geometry (about 5 s for Plaza SEC-1).</summary>
    public static NavWorld Build(EnvironmentWorld world, RcNavMeshBuildSettings? settings = null)
    {
        settings ??= DefaultSettings();
        var src = world.StaticGeometry;
        // GBSP floors wind clockwise seen from above (their cross(b-a, c-a) points down);
        // Recast marks a triangle walkable only when that normal points up.
        float[] verts = new float[src.Vertices.Length * 3];
        for (int i = 0; i < src.Vertices.Length; i++) { verts[i * 3] = src.Vertices[i].X; verts[i * 3 + 1] = src.Vertices[i].Y; verts[i * 3 + 2] = src.Vertices[i].Z; }
        int[] faces = new int[src.Triangles.Length - src.Triangles.Length % 3];
        for (int i = 0; i < faces.Length; i += 3) { faces[i] = src.Triangles[i]; faces[i + 1] = src.Triangles[i + 2]; faces[i + 2] = src.Triangles[i + 1]; }
        var clock = Stopwatch.StartNew();
        var result = new SoloNavMeshBuilder().Build(new DemoInputGeomProvider(verts, faces), settings);
        if (!result.Success || result.NavMesh == null) throw new InvalidOperationException($"Navmesh bake failed for world {world.Summary.WorldId}.");
        return new(world, result.NavMesh, settings, clock.Elapsed);
    }

    /// <summary>Wraps a mesh saved with <see cref="Save"/> for the same world and settings.</summary>
    public static NavWorld Load(EnvironmentWorld world, Stream stream, RcNavMeshBuildSettings? settings = null)
    {
        settings ??= DefaultSettings();
        using var reader = new BinaryReader(stream, System.Text.Encoding.UTF8, leaveOpen: true);
        var mesh = new DtMeshSetReader().Read(reader, settings.vertsPerPoly) ?? throw new InvalidDataException("Unreadable navmesh cache.");
        return new(world, mesh, settings, TimeSpan.Zero);
    }

    public void Save(Stream stream)
    {
        using var writer = new BinaryWriter(stream, System.Text.Encoding.UTF8, leaveOpen: true);
        new DtMeshSetWriter().Write(writer, Mesh, RcByteOrder.LITTLE_ENDIAN, false);
    }

    private static RcVec3f Rc(Vector3 v) => new(v.X, v.Y, v.Z);
    private static Vector3 V(RcVec3f v) => new(v.X, v.Y, v.Z);

    /// <summary>Nearest mesh point to <paramref name="p"/> inside the search box with these half extents.</summary>
    public bool Snap(Vector3 p, Vector3 halfExtents, out long poly, out Vector3 on)
    {
        bool ok = _query.FindNearestPoly(Rc(p), Rc(halfExtents), _filter, out poly, out var hit, out _).Succeeded() && poly != 0;
        on = V(hit); return ok;
    }

    public bool Snap(Vector3 p, out long poly, out Vector3 on, bool wide = false) => Snap(p, wide ? WideExtents : Extents, out poly, out on);

    /// <summary>Detour straight-path corners from one point to another (the first is the snapped start). Empty when
    /// either end is off the mesh. <paramref name="complete"/> is false when the target's polygon cannot be reached;
    /// the path then ends at the reachable point closest to it.</summary>
    public List<Vector3> Route(Vector3 from, Vector3 to, out bool complete, bool wideTarget = false) =>
        Route(from, to, wideTarget ? WideExtents : Extents, out complete);

    public List<Vector3> Route(Vector3 from, Vector3 to, Vector3 targetExtents, out bool complete)
    {
        complete = false;
        if (!Snap(from, out long a, out var pa) || !Snap(to, targetExtents, out long b, out var pb)) return new();
        var path = new long[4096];
        if (_query.FindPath(a, b, Rc(pa), Rc(pb), _filter, path, out int count, path.Length).Failed() || count == 0) return new();
        complete = path[count - 1] == b;
        var corners = new DtStraightPath[1024];
        _query.FindStraightPath(Rc(pa), Rc(pb), path, count, corners, out int n, corners.Length, 0);
        return corners.Take(n).Select(c => V(c.pos)).ToList();
    }

    /// <summary>True when a straight walk from one point to another stays on the mesh (no wall or ledge between).</summary>
    public bool Clear(Vector3 from, Vector3 to)
    {
        if (!Snap(from, out long start, out var on)) return false;
        var visited = new long[256];
        var status = _query.Raycast(start, Rc(on), Rc(to), _filter, out float t, out _, visited, out _, visited.Length);
        return status.Succeeded() && t >= 1f;
    }

    /// <summary>Ground polygons of the mesh (for drawing and checks).</summary>
    public List<Vector3[]> Polygons()
    {
        var list = new List<Vector3[]>();
        for (int i = 0; i < Mesh.GetMaxTiles(); i++)
        {
            var data = Mesh.GetTile(i)?.data; if (data?.header == null) continue;
            for (int j = 0; j < data.header.polyCount; j++)
            {
                var poly = data.polys[j]; if (poly.GetPolyType() != DtPolyTypes.DT_POLYTYPE_GROUND) continue;
                list.Add(Enumerable.Range(0, poly.vertCount).Select(k => { int v = poly.verts[k] * 3; return new Vector3(data.verts[v], data.verts[v + 1], data.verts[v + 2]); }).ToArray());
            }
        }
        return list;
    }

    /// <summary>Walked (ground-plane) length of a corner path.</summary>
    public static float Length(IReadOnlyList<Vector3> path)
    {
        float total = 0;
        for (int i = 1; i < path.Count; i++) total += PointNavigation.Distance(path[i - 1], path[i]);
        return total;
    }
}
