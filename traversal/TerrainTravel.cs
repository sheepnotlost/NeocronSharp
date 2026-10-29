using System.Diagnostics;
using System.Numerics;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Trips across the wasteland. Its cells (world 2000 + 20 * row + column) have no zone lines: you
/// walk off one edge into the neighbour. Doors into Tech Haven, the Military Base, Canyon, the
/// dungeons and back to the city's Outzone are WorldChanges inside models placed in the cells.
/// Planning: a shortest-path search over sectors in which a stretch of wasteland is one step,
/// costed by its straight-line length; that stretch is then routed on the wasteland-wide walking
/// grid (<see cref="TerrainMap"/>), which names the cells crossed and where. Walking: one leg per
/// cell, on the cell's own navmesh (<see cref="TerrainNav"/>), to just inside the edge and on across.
/// </summary>
internal sealed partial class Travel
{
    private TerrainMap? _terrain;
    private readonly Dictionary<int, bool> _isTerrain = new();
    private readonly Dictionary<TerrainMap.Portal, int> _portalNodes = new();

    /// <summary>The wasteland's walking grid, doors and outposts (loaded on first use; cached in logs/terrain/).</summary>
    public TerrainMap Terrain => _terrain ??= TerrainMap.Get(install);

    /// <summary>True for a wasteland cell ("E 07 - MOUNTAINS").</summary>
    public bool IsTerrain(int sector)
    {
        lock (_isTerrain)
        {
            if (sector <= 0) return false;   // the subway's hall nodes in plans (Subway.cs)
            if (!_isTerrain.TryGetValue(sector, out bool cell)) _isTerrain[sector] = cell = TerrainCell.Exists(install, sector);
            return cell;
        }
    }

    /// <summary>A sector with a door straight out into the wasteland (Outzone 8 and 9, Tech Haven, a dungeon...).</summary>
    public bool TouchesWasteland(int sector) => !IsTerrain(sector) && SafeLinks(sector).Any(l => IsTerrain(l.To));

    private readonly Dictionary<int, List<(EnvironmentFeature Exit, int To)>> _linkCache = new();

    // Links, kept for the run: the wasteland search asks for the same sectors' links many times.
    private List<(EnvironmentFeature Exit, int To)> SafeLinks(int sector)
    {
        lock (_linkCache) if (_linkCache.TryGetValue(sector, out var known)) return known;
        List<(EnvironmentFeature Exit, int To)> links;
        try { links = Links(sector).ToList(); }
        catch (Exception e) when (e is IOException or InvalidDataException) { links = new(); }
        lock (_linkCache) _linkCache[sector] = links;
        return links;
    }

    // Exits given up on in an offline plan (PlanTrip): avoided like blocked ones, but never written to the logs.
    private readonly HashSet<(int Sector, string Exit)> _planBlocked = new();
    private bool Avoided(int sector, string exit) => _blocked.Contains((sector, exit)) || _planBlocked.Contains((sector, exit));

    private HashSet<int>? _areaIds;
    private bool KnownWorld(int id) => (_areaIds ??= Areas.Select(a => a.WorldId).ToHashSet()).Contains(id);

    private IEnumerable<(EnvironmentFeature Exit, int To)> AllLinks(int sector) => IsTerrain(sector) ? TerrainLinks(sector) : Links(sector);

    /// <summary>The kind of the features <see cref="TerrainLinks"/> makes for a cell edge.</summary>
    public const string CellEdge = "CellEdge";

    /// <summary>Ways out of a wasteland cell: the doors placed in it, and the cells across its four edges.</summary>
    public IEnumerable<(EnvironmentFeature Exit, int To)> TerrainLinks(int cell)
    {
        var map = Terrain;
        if (!map.IsCell(cell)) yield break;
        foreach (var p in map.Portals.Where(p => p.Cell == cell && p.To != cell && KnownWorld(p.To) && !IsTerrain(p.To)))
            yield return (PortalFeature(p), p.To);
        foreach (var (name, dr, dc) in new[] { ("north", -1, 0), ("south", 1, 0), ("east", 0, 1), ("west", 0, -1) })
        {
            int row = TerrainCell.Row(cell) + dr, column = TerrainCell.Column(cell) + dc;
            if (row < 0 || column < 1 || column >= TerrainCell.Columns) continue;
            int next = TerrainCell.IdAt(row, column);
            if (map.IsCell(next))
                yield return (new EnvironmentFeature(CellEdge, $"edge:{name}", Vector3.Zero, new Dictionary<string, string> { ["NextLevel"] = next.ToString() }), next);
        }
    }

    private static EnvironmentFeature PortalFeature(TerrainMap.Portal p) => new("WorldChange", p.Name, p.Position, new Dictionary<string, string>
    {
        ["classname"] = "WorldChange", ["NextLevel"] = p.To.ToString(), ["Index"] = p.Index,
        ["NextLevelStartIndex"] = p.Arrival.ToString(System.Globalization.CultureInfo.InvariantCulture),
    });

    private int PortalNode(TerrainMap.Portal p)
    {
        lock (_portalNodes)
        {
            if (!_portalNodes.TryGetValue(p, out int g)) _portalNodes[p] = g = Terrain.Nearest(p.Cell, p.Position);
            return g;
        }
    }

    /// <summary>
    /// One stretch of wasteland in a plan: entered in <paramref name="Cell"/> at <paramref name="Entry"/>,
    /// left by the door <paramref name="Exit"/> (or ending in the target cell when that is null),
    /// along the walking-grid route <paramref name="Grid"/>.
    /// </summary>
    public sealed record WasteSegment(int Cell, Vector3 Entry, TerrainMap.Portal? Exit, int ToSector, List<int> Grid);

    /// <summary>A trip that crosses the wasteland: the sectors and cells in order, and each wasteland stretch.</summary>
    public sealed record WastePlan(List<int> Sectors, List<WasteSegment> Segments, float Cost);

    /// <summary>One step of the cost search: to a node, its seconds, the wasteland stretch it walks, and where it puts you in that node.</summary>
    private sealed record Step(int To, float Cost, (int Cell, Vector3 Entry, int Node, TerrainMap.Portal? Exit, int Goal)? Waste, Vector3? Arrive = null);

    // ---- Plan costs are seconds ----

    /// <summary>
    /// The walking pace plans assume, in units a second: the live walker's average along a route, turns and
    /// stairs included (Plaza 1, Plaza 3 and Pepper Park 1 legs on 29 Oct: 156-200; the gait itself runs 280-340).
    /// </summary>
    public const float WalkPace = 200;

    /// <summary>Straight lines between doors stretched for the walk round buildings (the live routes ran 1.25-2.45 times as far).</summary>
    public const float Detour = 1.5f;

    /// <summary>
    /// A zone line or door crossed: pushing through it and waiting while the next zone loads (6-11 s live),
    /// plus 10 s for the chance it needs a second try (many live crossings have). So of two ways that walk
    /// about as long, the one with fewer crossings wins.
    /// </summary>
    public const float ZoneSeconds = 20;

    /// <summary>
    /// What an interior (building, sewer, club) on the way costs on top of its walk, so a trip keeps to the
    /// streets unless one saves a lot (it used to cost 6 street lines).
    /// </summary>
    public const float InteriorSeconds = 200;

    /// <summary>
    /// A wasteland stretch: a fixed two half-cells (cell edges, slopes, the grid's guesswork) plus its straight
    /// length, at the offline simulator's 280 u/s: 58.5 s a half-cell.
    /// </summary>
    private const float WastePace = 280, HalfCellSeconds = TerrainCell.Half / WastePace;

    /// <summary>About one zone line, in seconds: how Reach turns times back into rough step counts.</summary>
    private const float ReachStep = 45;

    /// <summary>Seconds to walk between two points of one sector, from the straight line.</summary>
    public static float WalkSeconds(Vector3 a, Vector3 b) => Vector2.Distance(new(a.X, a.Z), new(b.X, b.Z)) * Detour / WalkPace;

    private readonly Dictionary<int, Vector3> _middles = new();

    /// <summary>Where plans assume you stand in a sector when nothing better is known: the middle of its exits.</summary>
    public Vector3 Middle(int sector)
    {
        lock (_middles)
        {
            if (_middles.TryGetValue(sector, out var known)) return known;
            var spots = SafeLinks(sector).Where(l => l.Exit.Kind == "WorldChange").Select(l => l.Exit.Position).ToList();
            return _middles[sector] = spots.Count == 0 ? Vector3.Zero : spots.Aggregate(Vector3.Zero, (a, b) => a + b) / spots.Count;
        }
    }

    /// <summary>Where you appear in <paramref name="into"/> coming through <paramref name="exit"/>: the WorldChange whose Index is the exit's arrival point.</summary>
    private Vector3? Arrival(int into, EnvironmentFeature exit)
    {
        if (IsTerrain(into) || into <= 0) return null;
        string index = exit.Properties.GetValueOrDefault("NextLevelStartIndex") ?? "";
        if (index is "" or "0") return null;
        try { return Features(into).FirstOrDefault(f => f.Kind == "WorldChange" && f.Properties.GetValueOrDefault("Index") == index)?.Position; }
        catch (Exception e) when (e is IOException or InvalidDataException) { return null; }
    }

    /// <summary>
    /// A sector chain timed as the cost search times it (from <paramref name="at"/>, else the first sector's
    /// middle): walking from where you appear to the nearest exit into the next sector, plus the crossing.
    /// </summary>
    private float PathSeconds(List<int> path, Vector3? at)
    {
        if (path.Count < 2) return 0;
        var here = at ?? Middle(path[0]);
        float seconds = 0;
        for (int i = 0; i + 1 < path.Count; i++)
        {
            int s = path[i], n = path[i + 1];
            var exits = SafeLinks(s).Where(l => l.To == n && !Avoided(s, l.Exit.Name)).ToList();
            if (exits.Count == 0) return float.MaxValue;
            var exit = exits.MinBy(l => WalkSeconds(here, l.Exit.Position)).Exit;
            seconds += WalkSeconds(here, exit.Position) + ZoneSeconds + (IsTerrain(n) || IsStreet(n) ? 0 : InteriorSeconds);
            here = Arrival(n, exit) ?? (IsTerrain(n) ? Vector3.Zero : Middle(n));
        }
        return seconds;
    }

    /// <summary>Where you appear in a cell coming through <paramref name="exit"/> from <paramref name="sector"/>.</summary>
    public Vector3? ArrivalIn(int cell, int sector, EnvironmentFeature exit)
    {
        int arrival = int.TryParse(exit.Properties.GetValueOrDefault("NextLevelStartIndex"), out int a) ? a : 0;
        return Terrain.ArrivalFrom(cell, sector, arrival)?.Position;
    }

    // Shortest-path steps out of one node of the sector graph, in seconds, from `at` (where you stand or
    // appear in the node; else its middle). A zone line or door: the walk to it plus the crossing. A step
    // through the wasteland: a fixed two half-cells plus its straight-line length (see HalfCellSeconds).
    private IEnumerable<Step> Steps(int node, int start, int target, Vector3? at)
    {
        // A subway hall: on to its own doors, or by train to the other halls' (Subway.cs).
        if (IsSubwayNode(node)) { foreach (var s in SubwaySteps(node, at)) yield return s; yield break; }
        if (IsTerrain(node))
        {
            // Only the start can be a cell: the stretch begins where you stand (or its biggest walkable area).
            var map = Terrain;
            int g0 = at is { } p ? map.Nearest(node, p) : -1;
            if (g0 < 0) { int main = map.MainComponent(node); g0 = main < 0 ? -1 : map.Nearest(node, Vector3.Zero, main, rings: TerrainMap.N); }
            if (g0 >= 0) foreach (var s in WasteSteps(node, map.Local(g0), g0, from: -1, target)) yield return s;
            yield break;
        }
        if (node != start && !PassesThrough(node, interiors: true)) yield break;
        // Faction offices and HQs let in only their own faction: a destination, never a way through.
        if (node != start && SectorName(node) is var name && (name.Contains("FACTION", StringComparison.OrdinalIgnoreCase) || name.Contains(" HQ", StringComparison.OrdinalIgnoreCase))) yield break;
        // As Neighbours (not blocked, and a way back), by each exit. An interior costs InteriorSeconds more,
        // so a trip keeps to the streets unless a building or sewer saves a lot (as SectorPath prefers streets).
        var here = at ?? Middle(node);
        foreach (var (exit, n) in SafeLinks(node))
        {
            if (IsTerrain(n) || Avoided(node, exit.Name) || !SafeLinks(n).Any(back => back.To == node)) continue;
            yield return new(n, WalkSeconds(here, exit.Position) + ZoneSeconds + (IsStreet(n) ? 0 : InteriorSeconds), null, Arrival(n, exit));
        }
        foreach (var (exit, cell) in SafeLinks(node).Where(l => IsTerrain(l.To) && !Avoided(node, l.Exit.Name)))
        {
            if (ArrivalIn(cell, node, exit) is not { } entry) continue;
            int g0 = Terrain.Nearest(cell, entry);
            float door = WalkSeconds(here, exit.Position) + ZoneSeconds;
            if (g0 >= 0) foreach (var s in WasteSteps(cell, entry, g0, from: node, target)) yield return s with { Cost = s.Cost + door };
        }
        // Into the subway hall behind a station door, to ride on from there.
        foreach (var s in SubwaySteps(node, here)) yield return s;
    }

    private IEnumerable<Step> WasteSteps(int cell, Vector3 entry, int g0, int from, int target)
    {
        var map = Terrain;
        int component = map.Component(g0);
        var here = TerrainMap.CellOrigin(cell) + new Vector2(entry.X, entry.Z);
        foreach (var p in map.Portals)
        {
            if (p.To == from || IsTerrain(p.To) || Avoided(p.Cell, p.Name) || !KnownWorld(p.To)) continue;
            int g = PortalNode(p);
            if (g < 0 || map.Component(g) != component) continue;
            // Only doors with a way back out into the wasteland (as for zone lines: one-way doors need "use").
            if (!SafeLinks(p.To).Any(l => IsTerrain(l.To))) continue;
            float distance = Vector2.Distance(here, TerrainMap.CellOrigin(p.Cell) + new Vector2(p.Position.X, p.Position.Z));
            yield return new(p.To, (2 + distance / TerrainCell.Half) * HalfCellSeconds, (cell, entry, g0, p, g), Arrival(p.To, PortalFeature(p)));
        }
        if (IsTerrain(target) && map.IsCell(target))
        {
            int goal = map.Nearest(target, Vector3.Zero, component, rings: TerrainMap.N);
            if (goal >= 0)
                yield return new(target, (2 + Vector2.Distance(here, map.Global(goal)) / TerrainCell.Half) * HalfCellSeconds, (cell, entry, g0, null, goal));
        }
    }

    /// <summary>
    /// The quickest way (cost in seconds) from <paramref name="from"/> to <paramref name="to"/> that may
    /// cross the wasteland or ride the subway (null when there is none). <paramref name="at"/> is where you
    /// stand in <paramref name="from"/> (in a cell: cell space), when known. Each node is timed from where
    /// its quickest way in puts you.
    /// </summary>
    public WastePlan? WastelandPlan(int from, int to, Vector3? at)
    {
        if (from == to) return new(new() { from }, new(), 0);
        var cost = new Dictionary<int, float> { [from] = 0 };
        var arrivals = new Dictionary<int, Vector3?> { [from] = at };
        var previous = new Dictionary<int, (int From, Step Step)>();
        var open = new PriorityQueue<int, float>(); open.Enqueue(from, 0);
        var done = new HashSet<int>();
        while (open.TryDequeue(out int node, out float c))
        {
            if (!done.Add(node)) continue;
            if (node == to) break;
            if (IsTerrain(node) && node != from) continue;   // a target cell ends a stretch; it is not walked on from
            foreach (var step in Steps(node, from, to, arrivals.GetValueOrDefault(node)))
            {
                float total = c + step.Cost;
                if (cost.TryGetValue(step.To, out float known) && known <= total) continue;
                cost[step.To] = total; previous[step.To] = (node, step); arrivals[step.To] = step.Arrive;
                open.Enqueue(step.To, total);
            }
        }
        if (!previous.ContainsKey(to)) return null;
        var steps = new List<(int From, Step Step)>();
        for (int n = to; n != from; n = previous[n].From) steps.Add(previous[n]);
        steps.Reverse();
        // A subway hall is the subway (world 1000) to everything outside the plan.
        static int Real(int n) => IsSubwayNode(n) ? Subway : n;
        var sectors = new List<int> { Real(from) }; var segments = new List<WasteSegment>();
        foreach (var (_, step) in steps)
        {
            if (step.Waste is { } w)
            {
                var grid = Terrain.Route(w.Node, w.Goal);
                if (grid.Count == 0) return null;
                foreach (int cell in Terrain.CellsAlong(grid)) if (sectors[^1] != cell) sectors.Add(cell);
                segments.Add(new(w.Cell, w.Entry, w.Exit, step.To, grid));
            }
            if (sectors[^1] != Real(step.To)) sectors.Add(Real(step.To));
        }
        return new(sectors, segments, cost[to]);
    }

    /// <summary>
    /// Sectors reached only by crossing the wasteland from <paramref name="start"/> (the doors in it,
    /// what lies behind them, and the cells themselves), with a rough count of steps.
    /// </summary>
    private Dictionary<int, int> WastelandReach(int start, IReadOnlyDictionary<int, int> already)
    {
        var cost = new Dictionary<int, float> { [start] = 0 };
        var open = new PriorityQueue<int, float>(); open.Enqueue(start, 0);
        var done = new HashSet<int>();
        var components = new Dictionary<int, float>();
        while (open.TryDequeue(out int node, out float c))
        {
            if (!done.Add(node)) continue;
            foreach (var step in Steps(node, start, target: -1, at: null))
            {
                if (step.Waste is { } w)
                {
                    int component = Terrain.Component(w.Node);
                    if (!components.TryGetValue(component, out float seen) || seen > c + ReachStep) components[component] = c + ReachStep;
                }
                float total = c + step.Cost;
                if (cost.TryGetValue(step.To, out float known) && known <= total) continue;
                cost[step.To] = total;
                open.Enqueue(step.To, total);
            }
        }
        var reach = new Dictionary<int, int>();
        // Seconds back to rough step counts (about one zone line each).
        foreach (var (sector, c) in cost) if (!already.ContainsKey(sector) && !IsSubwayNode(sector)) reach[sector] = (int)MathF.Ceiling(c / ReachStep);
        foreach (var (component, c) in components)
            foreach (int cell in Terrain.CellsOf(component))
                if (!already.ContainsKey(cell) && (!reach.TryGetValue(cell, out int r) || r > c / ReachStep + 1)) reach[cell] = (int)MathF.Ceiling(c / ReachStep + 1);
        return reach;
    }

    private readonly HashSet<int> _fitted = new();

    /// <summary>
    /// The first time in a cell: block the walking-grid squares its navmesh cannot reach from here
    /// (the grid judges slopes 256 units at a time and misses ridges and walls the navmesh sees), so
    /// the plan only uses ways this cell's navmesh can walk.
    /// </summary>
    private void FitGrid(int cell, Vector3 start, NavWorld nav)
    {
        if (!_fitted.Add(cell)) return;
        var island = nav.Island(start);
        if (island.Count == 0) return;
        int blocked = Terrain.Restrict(cell, p => nav.OnIsland(p, island));
        if (blocked > 0) Console.WriteLine($"  {SectorName(cell)}: {blocked} grid squares are not reachable on its navmesh from here; planning round them");
    }

    /// <summary>One walk inside a cell: where to go, where to push on to, and what lies beyond.</summary>
    public sealed record CellLeg(Vector3 Walk, Vector3? Push, int Next, bool Door, string Label, List<Vector3> Route, int Inside, TerrainMap.Portal? Portal);

    /// <summary>
    /// Plan the walk inside <paramref name="cell"/> for the first stretch of <paramref name="segment"/>:
    /// to the cell edge the grid route crosses (or a nearby stretch of the same edge that the navmesh
    /// reaches), or to the door that ends the stretch. Null when the navmesh reaches none of them.
    /// </summary>
    public CellLeg? PlanCellLeg(int cell, Vector3 start, WasteSegment segment, NavWorld nav)
    {
        var map = Terrain;
        var crossing = map.FirstCrossing(segment.Grid);
        if (crossing is { } c)
        {
            foreach (var (inside, beyond) in new[] { (c.Inside, c.Beyond) }.Concat(map.AlongEdge(c.Inside, c.Beyond).Take(24)))
            {
                var (walk, push) = map.CrossingPoints(inside, beyond);
                var route = nav.RouteNear(start, walk, out bool ok, maxMiss: 300);
                if (!ok || route.Count < 2 || Settle(nav, start, route) is not { } settled) continue;
                var end = settled[^1];
                int next = map.CellOf(beyond);
                return new(end, push + (end - walk) with { Y = 0 }, next, false, $"edge into {SectorName(next)}", settled, inside, null);
            }
            return null;
        }
        if (segment.Exit is { } door)
        {
            var route = nav.RouteNear(start, door.Position, out bool ok);
            string label = $"door into {SectorName(door.To)}";
            if (!ok || route.Count < 2)
            {
                // The entrance models' halls often come out as islands on the navmesh (the way in is a door
                // or a stair the voxels miss: Tech Haven's in E 07). Walk as close as the floor goes and push
                // on at the door, right-clicking it if it stops the walk, as for city doors.
                route = nav.RouteToward(start, door.Position);
                if (route.Count < 2) return null;
                var near = route[^1];
                float gap = new Vector2(door.Position.X - near.X, door.Position.Z - near.Z).Length();
                if (gap > 700 || MathF.Abs(door.Position.Y - near.Y) > 450) return null;
                label += $" (its floor is not on the navmesh: pushing on from {gap:F0} units)";
            }
            if (Settle(nav, start, route) is not { } settled) return null;
            var end = settled[^1];
            var on = new Vector3(door.Position.X - end.X, 0, door.Position.Z - end.Z);
            Vector3? push = on.Length() > 30 ? door.Position + Vector3.Normalize(on) * 300 : null;
            return new(end, push, door.To, true, label, settled, -1, door);
        }
        return null;
    }

    /// <summary>
    /// The walk's end as the live walk will route to it (LiveSteer snaps its target tightly): the end of
    /// <paramref name="route"/>, or a spot a little way back along it when the end sits where floors are
    /// stacked (entrance models) and the snap picks another one. Null when none routes.
    /// </summary>
    private static List<Vector3>? Settle(NavWorld nav, Vector3 start, List<Vector3> route)
    {
        var along = new RouteFollower(route);
        foreach (float back in new[] { 0f, 24, 48, 96, 160, 256, 400 })
        {
            if (back >= along.Total) break;
            var spot = along.PointAt(along.Total - back);
            var settled = nav.Route(start, spot, out bool complete);
            if (complete && settled.Count > 1 && PointNavigation.Distance(settled[^1], spot) < 8) return settled;
        }
        return null;
    }

    /// <summary>
    /// Walk one leg out in the wasteland (from Go): replan from where you stand, walk to the next cell
    /// edge or door and through it. False when the same leg must be tried again (an obstacle was
    /// mapped, or that crossing was given up and another is planned).
    /// </summary>
    private bool WastelandLeg(PlayerReader reader, PlayerSample sample, int here, int targetSector, NavWorld nav, string log, int leg,
        ref bool first, ref LiveSteer.Calibration? calibration, ref int failures, ref int obstaclesThisLeg)
    {
        FitGrid(here, sample.Position, nav);
        var plan = WastelandPlan(here, targetSector, sample.Position)
            ?? throw new InvalidOperationException($"No walkable way across the wasteland from here to {SectorName(targetSector)}.");
        if (plan.Segments.Count == 0 || plan.Segments[0].Cell != here) throw new InvalidOperationException("The wasteland plan does not start here.");
        var segment = plan.Segments[0];
        var step = PlanCellLeg(here, sample.Position, segment, nav);
        if (step == null)
        {
            // The grid says this way goes through, the cell's navmesh says no: never plan through there again.
            var crossing = Terrain.FirstCrossing(segment.Grid);
            if (crossing is { } c) Terrain.Block(c.Inside);
            else if (segment.Exit is { } door) Block(here, door.Name, "no walkable route to it on the navmesh");
            if (++failures > 8) throw new InvalidOperationException($"No walkable route out of {SectorName(here)} toward {SectorName(targetSector)}.");
            return false;
        }
        Console.WriteLine($"Leg {leg + 1}: {SectorName(here)} -> {SectorName(step.Next)} by the {step.Label} ({new RouteFollower(step.Route).Total:F0} units). " +
            $"Plan: {string.Join(" -> ", plan.Sectors.Select(SectorName))}");
        var clock = Stopwatch.StartNew();
        // The walk ends on the navmesh (Settle checked the tight snap): no wide snap, which can land on a stacked floor.
        var steer = new LiveSteer(reader, nav, here, step.Walk, false, step.Label, pulse, log, hud, run,
            zoneExit: true, countdown: first, known: calibration, pushTo: step.Push, openDoor: step.Door);
        try { steer.Run(); }
        catch (LiveSteer.BlockedAt blocked) when (!steer.Zoned && obstaclesThisLeg < 5)
        {
            var spot = blocked.Position + Vector3.Normalize(new(blocked.Forward.X, 0, blocked.Forward.Z)) * 48;
            AddObstacle(here, spot);
            obstaclesThisLeg++;
            Learn(here, step.Label, step.Next, false, clock.Elapsed.TotalSeconds, $"obstacle at {spot.X:F0},{spot.Z:F0}");
            Console.WriteLine($"Something is in the way at {spot.X:F0},{spot.Z:F0}; mapping it as an obstacle and going round.");
            first = false;
            return false;
        }
        catch (InvalidOperationException e) when (!steer.Zoned && IsRouteProblem(e.Message))
        {
            Learn(here, step.Label, step.Next, false, clock.Elapsed.TotalSeconds, e.Message);
            if (step.Portal is { } door) Block(here, door.Name, e.Message); else Terrain.Block(step.Inside);
            if (++failures > 8) throw;
            Console.WriteLine($"That way failed ({e.Message}); trying another.");
            first = false;
            return false;
        }
        finally { calibration ??= steer.Measured; }
        if (!steer.Zoned) throw new InvalidOperationException("Reached the cell edge without the game changing cell.");
        first = false;
        int arrived = WaitForSector(reader, step.Next);
        Learn(here, step.Label, arrived, arrived == step.Next, clock.Elapsed.TotalSeconds, arrived == step.Next ? null : $"arrived in {SectorName(arrived)}");
        if (arrived == here && ++failures > 6) throw new InvalidOperationException("Kept detecting a cell change that did not happen.");
        return true;
    }

    /// <summary>One leg of an offline trip plan (no game needed): how it is walked, how far, and whether the simulated walk arrives.</summary>
    public sealed record PlannedLeg(int From, int To, string Method, float Length, bool Ok, string? Note);

    /// <summary>
    /// Plan a whole trip offline, leg by leg, as <see cref="Go"/> would walk it: each street leg by its
    /// zone line, each wasteland leg on the cell's navmesh to the crossing (simulated with the live
    /// lag and mouse error). Starts at <paramref name="at"/>, else where people from the previous sector arrive.
    /// </summary>
    public List<PlannedLeg> PlanTrip(int from, int to, Vector3? at, Func<int, NavWorld> navFor, bool simulate = true)
    {
        LoadLearning();
        var legs = new List<PlannedLeg>();
        var random = new Random(7);
        int here = from, previous = -1; Vector3? position = at;
        for (int guard = 0; guard < 80 && here != to; guard++)
        {
            var nav = navFor(here);
            if (position is not { } p || !nav.Snap(p, out _, out var snapped, wide: true))
            {
                // Start where people arriving from the previous sector appear (any exit record, failing that).
                // In a cell with no position given: the middle of its biggest walkable area.
                var entry = IsTerrain(here) && Terrain.MainComponent(here) is var main && main >= 0
                        ? Terrain.Local(Terrain.Nearest(here, Vector3.Zero, main, rings: TerrainMap.N))
                    : SafeLinks(here).Where(e => e.To == previous).Select(e => (Vector3?)e.Exit.Position).FirstOrDefault()
                    ?? SafeLinks(here).Where(e => e.Exit.Kind == "WorldChange").Select(e => (Vector3?)e.Exit.Position).FirstOrDefault();
                if (entry is not { } e2 || !nav.Snap(e2, out _, out snapped, wide: true)) { legs.Add(new(here, to, "none", 0, false, "start is not on the navmesh")); break; }
            }
            if (IsTerrain(here))
            {
                FitGrid(here, snapped, nav);
                var plan = WastelandPlan(here, to, snapped);
                if (plan == null || plan.Segments.Count == 0) { legs.Add(new(here, to, "none", 0, false, "no way across the wasteland from here")); break; }
                if (Environment.GetEnvironmentVariable("TRAVERSAL_DEBUG") == "1") Console.WriteLine($"  [debug] in {SectorName(here)} at {snapped.X:F0},{snapped.Y:F0},{snapped.Z:F0}: plan {string.Join(" > ", plan.Sectors.Select(SectorName))}; first stretch exits by {plan.Segments[0].Exit?.Name ?? "-"}, start node {Terrain.Nearest(here, snapped)}");
                var step = PlanCellLeg(here, snapped, plan.Segments[0], nav);
                if (step == null)
                {
                    var crossing = Terrain.FirstCrossing(plan.Segments[0].Grid);
                    if (crossing is { } c) Terrain.Block(c.Inside); else if (plan.Segments[0].Exit is { } d) _planBlocked.Add((here, d.Name));
                    if (legs.Count(l => !l.Ok) > 8) break;
                    legs.Add(new(here, plan.Sectors.Count > 1 ? plan.Sectors[1] : to, "replanned", 0, false, "the navmesh does not reach the planned crossing; planning round it"));
                    continue;
                }
                float length = new RouteFollower(step.Route).Total;
                string? note = null; bool ok = true;
                if (simulate)
                {
                    // From the route's own ends (both on the navmesh). A stall on these 20-40k-unit walks is
                    // retried with other mouse noise, as a live walk replans; the note says how many tries.
                    Simulator.Outcome outcome = null!;
                    int tries = 0;
                    do outcome = Simulator.Run(nav, step.Route[0], step.Route[^1], 280, 0.0024f, 1.3f, 24, random);
                    while (!outcome.Arrived && outcome.Reason != "no route" && ++tries < 3);
                    ok = outcome.Arrived; note = ok ? $"simulated walk {outcome.Seconds:F0} s{(tries > 0 ? $" (after {tries} stall{(tries > 1 ? "s" : "")})" : "")}" : $"simulated walk failed: {outcome.Reason}";

                }
                legs.Add(new(here, step.Next, step.Door ? "wasteland door" : "cell edge", length, ok, note == null ? step.Label : $"{step.Label}; {note}"));
                previous = here;
                if (step.Door)
                {
                    position = SafeLinks(step.Next).Where(l => l.To == here).Select(l => (Vector3?)l.Exit.Position).FirstOrDefault();
                }
                else
                {
                    // Just across the edge, in the next cell's own coordinates.
                    var across = step.Push is { } push ? Vector3.Normalize((push - step.Walk) with { Y = 0 }) : Vector3.Zero;
                    position = TerrainMap.Into(here, step.Walk + across * 200, step.Next);
                }
                here = step.Next;
                continue;
            }
            // In the subway: ride the train first when the plan's door is in another hall (Subway.cs).
            if (here == Subway && SubwayPlanLeg(snapped, to, nav, legs) is { } boarded) { position = boarded; previous = -1; continue; }
            // After a leg was given up on, plan with it avoided (the street-only search does not know offline blocks).
            var path = here == Subway ? SubwayPath(snapped, to, nav, out _, out _)
                : _planBlocked.Count > 0 ? WastelandPlan(here, to, snapped)?.Sectors ?? new() : SectorPath(here, to, 12, snapped);
            if (path.Count < 2)
            {
                // A dead end (often an arrival spot estimated offline on a scrap of floor): go back the way
                // we came, as a walker would, and plan with this sector avoided.
                if (previous < 0 || legs.Count(l => l.Method == "backed out") >= 3) { legs.Add(new(here, to, "none", 0, false, "no chain of exits")); break; }
                foreach (var e in SafeLinks(previous).Where(e => e.To == here)) _planBlocked.Add((previous, e.Exit.Name));
                legs.Add(new(here, previous, "backed out", 0, false, $"no way on from {SectorName(here)}; planning again from {SectorName(previous)} without it"));
                here = previous; previous = -1; position = null;
                continue;
            }
            int next = path[1];
            var verts = nav.World.StaticGeometry.Vertices;
            var centre = new Vector3((verts.Min(v => v.X) + verts.Max(v => v.X)) / 2, 0, (verts.Min(v => v.Z) + verts.Max(v => v.Z)) / 2);
            var best = Links(here).Where(e => e.To == next && !Avoided(here, e.Exit.Name))
                .Select(e => (e.Exit, Line: LineFor(here, e.Exit, RotationFor(here, null), next, centre, nav)))
                .Where(e => e.Line.Walk != default)
                .Select(e => (e.Exit, e.Line, Route: nav.RouteNear(snapped, e.Line.Walk, out bool routed), Routed: routed))
                .Where(e => e.Route.Count > 1 && e.Routed)
                .OrderBy(e => new RouteFollower(e.Route).Total).FirstOrDefault();
            if (best.Exit == null)
            {
                // As Go does: give up on the exits into that sector and plan round them.
                legs.Add(new(here, next, "replanned", 0, false, "no walkable route to an exit into it; planning round it"));
                foreach (var e in Links(here).Where(e => e.To == next)) _planBlocked.Add((here, e.Exit.Name));
                if (legs.Count(l => !l.Ok) > 8) break;
                continue;
            }
            string method = next == Subway && best.Line.Push != null ? "subway stairs" : IsDoorLeg(here, next) ? "door" : best.Line.Push == null ? "exit record"
                : best.Line.Key == null ? (HasLearnedCrossing(here, next) ? "learned crossing" : "corridor tip") : IsPastRecord(best.Line.Key) ? "floor past the exit record" : "map arrow";
            legs.Add(new(here, next, method, new RouteFollower(best.Route).Total, true, best.Exit.Name));
            position = IsTerrain(next) ? ArrivalIn(next, here, best.Exit) : SafeLinks(next).Where(l => l.To == here).Select(l => (Vector3?)l.Exit.Position).FirstOrDefault();
            previous = here; here = next;
        }
        return legs;
    }

    /// <summary>Named places out in the wasteland (outposts), with the cell and the spot (cell space) to walk to.</summary>
    public IReadOnlyList<TerrainMap.Landmark> WastelandPlaces() => Terrain.Landmarks;
}
