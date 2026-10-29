using System.Diagnostics;
using System.Numerics;
using DotRecast.Core.Numerics;
using DotRecast.Detour;
using DotRecast.Recast.Toolset;
using DotRecast.Recast.Toolset.Builder;
using DotRecast.Recast.Toolset.Geom;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>A baked Neocron world: Recast navmesh plus the Detour queries steering needs.</summary>
internal sealed class NavWorld
{
    public EnvironmentWorld World { get; }
    public DtNavMesh Mesh { get; }
    public RcNavMeshBuildSettings Settings { get; }
    public TimeSpan BakeTime { get; }
    private readonly DtNavMeshQuery _query;
    private readonly DtQueryDefaultFilter _filter = new();
    private static readonly RcVec3f Extents = new(32, 128, 32), WideExtents = new(96, 256, 96);

    /// <summary>Gravity lifts, as one-way links from where you step in to where you step off (<see cref="NavmeshPrototype.Lifts"/>).</summary>
    public IReadOnlyList<LiftLink> Lifts { get; private set; } = Array.Empty<LiftLink>();
    /// <summary>Doors inside the sector (from its spawn file): opened with one right click when one stops a walk.</summary>
    public IReadOnlyList<SectorObjects.Door> Doors { get; private set; } = Array.Empty<SectorObjects.Door>();
    /// <summary>How many solid props from the spawn file were cut out of the navmesh.</summary>
    public int PropCount { get; private set; }

    private NavWorld(EnvironmentWorld world, DtNavMesh mesh, RcNavMeshBuildSettings settings, TimeSpan bakeTime)
    { World = world; Mesh = mesh; Settings = settings; BakeTime = bakeTime; _query = new(mesh); }

    // Agent size in Neocron world units. First guesses, not measured: telemetry Y
    // is the feet, a Plaza 1 corridor floor-to-ceiling is ~224.
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

    /// <param name="obstacles">
    /// Spots found blocked in the game (props such as boxes and barrels are not level geometry):
    /// each is cut out of the navmesh as a small square so routes go round it.
    /// </param>
    public static NavWorld Bake(string install, int worldId, RcNavMeshBuildSettings? settings = null, IReadOnlyList<Vector3>? obstacles = null)
    {
        // Wasteland cells are heightfields, not GBSP levels: baked coarser, tiled, and cached.
        if (settings == null && TerrainCell.Exists(install, worldId)) return TerrainNav.Bake(install, worldId, obstacles);
        settings ??= DefaultSettings();
        var world = new EnvironmentCatalog(install).Load(worldId);
        var src = world.StaticGeometry;
        // GBSP floors wind clockwise seen from above (their cross(b-a, c-a) points
        // down); Recast marks a triangle walkable only when that normal points up.
        float[] verts = src.Vertices.SelectMany(p => new[] { p.X, p.Y, p.Z }).ToArray();
        int[] faces = new int[src.Triangles.Length];
        for (int i = 0; i < faces.Length; i += 3) { faces[i] = src.Triangles[i]; faces[i + 1] = src.Triangles[i + 2]; faces[i + 2] = src.Triangles[i + 1]; }
        var clock = Stopwatch.StartNew();
        var geometry = new DemoInputGeomProvider(verts, faces);
        foreach (var o in obstacles ?? Array.Empty<Vector3>())
        {
            const float half = 28;
            float[] square = { o.X - half, o.Y, o.Z - half, o.X + half, o.Y, o.Z - half, o.X + half, o.Y, o.Z + half, o.X - half, o.Y, o.Z + half };
            geometry.AddConvexVolume(square, o.Y - 40, o.Y + 120, new DotRecast.Recast.RcAreaModification(0));   // 0 = not walkable
        }
        // Props the spawn file places (barrels, crates, benches, desks, invisible walls) are not level
        // geometry: cut each out by its turned bounding box. Doors come from the same file.
        SectorObjects.Contents contents;
        try { contents = SectorObjects.Read(install, world.Summary.Source); if (!UseProps) contents = new(Array.Empty<SectorObjects.Prop>(), contents.Doors); }
        catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException) { contents = new(Array.Empty<SectorObjects.Prop>(), Array.Empty<SectorObjects.Door>()); }
        foreach (var prop in contents.Props)
            geometry.AddConvexVolume(SectorObjects.Outline(prop), prop.Bottom - 16, prop.Top, new DotRecast.Recast.RcAreaModification(0));
        var builder = new SoloNavMeshBuilder();
        var result = builder.Build(geometry, settings);
        if (!result.Success || result.NavMesh == null) throw new InvalidOperationException($"Navmesh bake failed for world {worldId}.");
        var nav = new NavWorld(world, result.NavMesh, settings, clock.Elapsed) { Doors = contents.Doors, PropCount = contents.Props.Count };
        // Gravity lifts: found on this first mesh (the floors beside each beam), then added as
        // off-mesh links. Only the Detour data is rebuilt; the voxel work is reused.
        var lifts = NavmeshPrototype.Lifts.Links(nav);
        if (lifts.Count == 0) return nav;
        foreach (var link in lifts)
            geometry.AddOffMeshConnection(Rc(link.Start), Rc(link.End), NavmeshPrototype.Lifts.LinkRadius, false,
                SampleAreaModifications.SAMPLE_POLYAREA_TYPE_JUMP, SampleAreaModifications.SAMPLE_POLYFLAGS_JUMP);
        var data = builder.BuildMeshData(geometry, settings.cellSize, settings.cellHeight, settings.agentHeight, settings.agentRadius, settings.agentMaxClimb, result.RecastBuilderResults[0]);
        var linked = new DtNavMesh();
        if (data == null || linked.Init(data, settings.vertsPerPoly, 0).Failed()) return nav;   // keep the mesh without lifts
        return new NavWorld(world, linked, settings, clock.Elapsed) { Doors = contents.Doors, PropCount = contents.Props.Count, Lifts = lifts };
    }

    /// <summary>Cut the spawn file's props out of city bakes (off only for diagnostics).</summary>
    public static bool UseProps { get; set; } = true;

    /// <summary>The lift link whose ends are these two route corners, if any.</summary>
    public LiftLink? LinkAt(Vector3 from, Vector3 to) =>
        Lifts.FirstOrDefault(l => Vector3.Distance(l.Start, from) < 6 && Vector3.Distance(l.End, to) < 6);

    /// <summary>Every floor polygon in a box, with its point nearest <paramref name="centre"/> (on the polygon's own height).</summary>
    public List<(long Poly, Vector3 Point)> FloorsIn(Vector3 centre, Vector3 half)
    {
        var polys = new long[4096];
        var list = new List<(long, Vector3)>();
        if (_query.QueryPolygons(Rc(centre), Rc(half), _filter, polys, out int count, polys.Length).Failed()) return list;
        for (int i = 0; i < count; i++)
        {
            Mesh.GetTileAndPolyByRefUnsafe(polys[i], out var tile, out var poly);
            if (poly.GetPolyType() != DtPolyTypes.DT_POLYTYPE_GROUND) continue;
            float y = 0;
            for (int k = 0; k < poly.vertCount; k++) y += tile.data.verts[poly.verts[k] * 3 + 1];
            y /= Math.Max(1, (int)poly.vertCount);
            if (_query.ClosestPointOnPoly(polys[i], new RcVec3f(centre.X, y, centre.Z), out var closest, out _).Succeeded()) list.Add((polys[i], V(closest)));
        }
        return list;
    }

    /// <summary>Each polygon's connected piece of floor: an id and how many polygons it has.</summary>
    public Dictionary<long, (int Id, int Size)> Components()
    {
        var map = new Dictionary<long, (int, int)>();
        int next = 0;
        for (int t = 0; t < Mesh.GetMaxTiles(); t++)
        {
            var tile = Mesh.GetTile(t);
            if (tile?.data?.header == null) continue;
            long baseRef = Mesh.GetPolyRefBase(tile);
            for (int j = 0; j < tile.data.header.polyCount; j++)
            {
                long start = baseRef | (long)j;
                if (map.ContainsKey(start) || tile.data.polys[j].GetPolyType() != DtPolyTypes.DT_POLYTYPE_GROUND) continue;
                var piece = new List<long> { start };
                var seen = new HashSet<long> { start };
                for (int k = 0; k < piece.Count; k++)
                {
                    Mesh.GetTileAndPolyByRefUnsafe(piece[k], out var ti, out var po);
                    for (int link = po.firstLink; link >= 0 && link < ti.links.Length; link = ti.links[link].next)
                    {
                        long n = ti.links[link].refs;
                        if (n != 0 && seen.Add(n)) piece.Add(n);
                    }
                }
                int id = next++;
                foreach (var p in piece) map[p] = (id, piece.Count);
            }
        }
        return map;
    }

    /// <summary>A world whose navmesh was built (or loaded from a cache) elsewhere: the wasteland cells.</summary>
    public static NavWorld FromMesh(EnvironmentWorld world, DtNavMesh mesh, RcNavMeshBuildSettings settings, TimeSpan bakeTime) => new(world, mesh, settings, bakeTime);

    public static RcVec3f Rc(Vector3 v) => new(v.X, v.Y, v.Z);
    public static Vector3 V(RcVec3f v) => new(v.X, v.Y, v.Z);

    public bool Snap(Vector3 p, out long poly, out Vector3 on, bool wide = false)
    {
        bool ok = _query.FindNearestPoly(Rc(p), wide ? WideExtents : Extents, _filter, out poly, out var hit, out _).Succeeded() && poly != 0;
        on = V(hit); return ok;
    }

    /// <summary>Corner path from one point to another; empty when either end is off the mesh.</summary>
    /// <summary>
    /// Corner path toward <paramref name="to"/> even when it lies off the mesh (beyond a zone
    /// line): ends at the walkable spot nearest it, which is the end of the corridor leading there.
    /// </summary>
    public List<Vector3> RouteToward(Vector3 from, Vector3 to)
    {
        if (!Snap(from, out long a, out var pa)) return new();
        // A far target can lie past the map's edge with no floor near it: step back toward
        // the start until there is some, so the path ends at the farthest tip that way.
        long b = 0; RcVec3f pbr = default;
        for (float back = 0; back < 1; back += 0.2f)
        {
            var probe = Vector3.Lerp(to, from, back);
            if (_query.FindNearestPoly(Rc(probe), new RcVec3f(600, 512, 600), _filter, out b, out pbr, out _).Succeeded() && b != 0) break;
        }
        if (b == 0) return new();
        var pb = V(pbr);
        Span<long> path = stackalloc long[4096];
        if (_query.FindPath(a, b, Rc(pa), Rc(pb), _filter, path, out int count, path.Length).Failed() || count == 0) return new();
        var corners = new DtStraightPath[1024];
        _query.FindStraightPath(Rc(pa), Rc(pb), path, count, corners, out int n, corners.Length, 0);
        return corners.Take(n).Select(c => V(c.pos)).ToList();
    }

    /// <summary>
    /// Route to <paramref name="to"/>, or failing that to the walkable spot nearest it if that
    /// is within <paramref name="maxMiss"/> (map arrows are drawn at the floor's edge and can sit
    /// in a wall or railing, beyond the normal snap distance).
    /// </summary>
    public List<Vector3> RouteNear(Vector3 from, Vector3 to, out bool complete, float maxMiss = 200)
    {
        var route = Route(from, to, out complete, wideTarget: true);
        if (route.Count > 1 && complete) return route;
        route = RouteToward(from, to);
        complete = route.Count > 1 && PointNavigation.Distance(route[^1], to) <= maxMiss;
        return route;
    }

    public List<Vector3> Route(Vector3 from, Vector3 to, out bool complete, bool wideTarget = false)
    {
        complete = false;
        if (!Snap(from, out long a, out var pa) || !Snap(to, out long b, out var pb, wideTarget)) return new();
        Span<long> path = stackalloc long[4096];
        if (_query.FindPath(a, b, Rc(pa), Rc(pb), _filter, path, out int count, path.Length).Failed() || count == 0) return new();
        complete = path[count - 1] == b;
        var corners = new DtStraightPath[1024];
        _query.FindStraightPath(Rc(pa), Rc(pb), path, count, corners, out int n, corners.Length, 0);
        return corners.Take(n).Select(c => V(c.pos)).ToList();
    }

    /// <summary>Every polygon connected to the one under <paramref name="from"/> (the island you can walk on from there).</summary>
    public HashSet<long> Island(Vector3 from)
    {
        var seen = new HashSet<long>();
        if (!Snap(from, out long start, out _, wide: true)) return seen;
        var stack = new Stack<long>(); stack.Push(start); seen.Add(start);
        while (stack.Count > 0)
        {
            Mesh.GetTileAndPolyByRefUnsafe(stack.Pop(), out var tile, out var poly);
            for (int link = poly.firstLink; link >= 0 && link < tile.links.Length; link = tile.links[link].next)
            {
                long next = tile.links[link].refs;
                if (next != 0 && seen.Add(next)) stack.Push(next);
            }
        }
        return seen;
    }

    /// <summary>True when the floor nearest <paramref name="p"/> (within <paramref name="reach"/> across, 400 up or down) is in <paramref name="island"/>.</summary>
    public bool OnIsland(Vector3 p, HashSet<long> island, float reach = 128)
    {
        // Any floor there that is on the island (the nearest one can be a scrap on a wall top or under a model).
        var polys = new long[256];
        if (_query.QueryPolygons(Rc(p), new RcVec3f(reach, 400, reach), _filter, polys, out int count, polys.Length).Failed()) return false;
        for (int i = 0; i < count; i++) if (island.Contains(polys[i])) return true;
        return false;
    }

    /// <summary>True when a straight walk from one point to another stays on the mesh (no wall or ledge between).</summary>
    public bool Clear(Vector3 from, Vector3 to)
    {
        if (!Snap(from, out long start, out var on)) return false;
        Span<long> visited = stackalloc long[256];
        var status = _query.Raycast(start, Rc(on), Rc(to), _filter, out float t, out _, visited, out _, visited.Length);
        return status.Succeeded() && t >= 1f;
    }

    /// <summary>Slide along the mesh surface as a character pressing into walls would (simulation only).</summary>
    public Vector3 Slide(Vector3 from, Vector3 to)
    {
        if (!Snap(from, out long start, out var on)) return from;
        Span<long> visited = stackalloc long[64];
        _query.MoveAlongSurface(start, Rc(on), Rc(to), _filter, out var result, visited, out int count, visited.Length);
        float y = result.Y;
        if (count > 0 && _query.GetPolyHeight(visited[count - 1], result, out float h).Succeeded()) y = h;
        return new(result.X, y, result.Z);
    }

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

    /// <summary>Resolve "x,y,z", "ground:Name" or "exit:Name" (a WorldChange) against this world.</summary>
    public (Vector3 Point, string Label, bool Wide) Target(string spec)
    {
        var parts = spec.Split(',');
        if (parts.Length == 3 && parts.All(p => float.TryParse(p, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out _)))
        {
            var f = parts.Select(p => float.Parse(p, System.Globalization.CultureInfo.InvariantCulture)).ToArray();
            return (new(f[0], f[1], f[2]), spec, false);
        }
        string kind = spec.StartsWith("exit:", StringComparison.OrdinalIgnoreCase) ? "WorldChange" : "GroundPathPoint";
        string name = spec[(spec.IndexOf(':') + 1)..];
        var feature = World.Summary.Features.FirstOrDefault(f => f.Kind == kind && string.Equals(f.Name, name, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidOperationException($"No {kind} named '{name}' in {World.Summary.Name}. Known: " +
                string.Join(", ", World.Summary.Features.Where(f => f.Kind == kind).Select(f => f.Name)));
        string next = feature.Properties.GetValueOrDefault("NextLevel") is { } n ? $" (to world {n})" : "";
        return (feature.Position, $"{kind} {feature.Name}{next}", kind == "WorldChange");
    }
}
