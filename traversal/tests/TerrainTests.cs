using System.Numerics;
using NavmeshPrototype;
using NeocronSharp.Core;

/// <summary>
/// Offline tests for the wasteland walker: the cell files (heightfield, placed models), the grid of
/// cells and their edges, the walking grid, and plans from the city's Outzone to Tech Haven.
/// Read-only; the world tests need the local install (navmeshes come from logs/terrain/ when cached).
/// </summary>
internal static class TerrainTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    public static void Run(Action<string, Action> test, string install)
    {
        test("Wasteland cells: world id, grid row/column and file code agree", () =>
        {
            Check(TerrainCell.CodeOf(2087) == "e_07" && TerrainCell.Row(2087) == 4 && TerrainCell.Column(2087) == 7, "2087 is E 07");
            Check(TerrainCell.IdAt(0, 9) == 2009 && TerrainCell.CodeOf(2009) == "a_09", "A 09 is 2009");
            // Row A is the north (+z), columns run east (+x): E 08 is east of E 07, D 07 north of it.
            var east = TerrainMap.CellOrigin(2088) - TerrainMap.CellOrigin(2087);
            var north = TerrainMap.CellOrigin(2067) - TerrainMap.CellOrigin(2087);
            Check(east == new Vector2(32768, 0) && north == new Vector2(0, 32768), $"east {east}, north {north}");
            var across = TerrainMap.Into(2087, new Vector3(16300, 100, 5), 2088);
            Check(across == new Vector3(16300 - 32768, 100, 5), $"a point past E 07's east edge is at the west of E 08 ({across})");
        });

        test("Sealed-model hulls are dropped, the model itself kept", () =>
        {
            // The hull's floor (two triangles at y = -10; its top corner sets the bounds) around one floor triangle at y = 0.
            var v = new[] { new Vector3(-10, -10, -10), new Vector3(10, -10, -10), new Vector3(10, -10, 10), new Vector3(-10, -10, 10),
                new Vector3(-1, 0, -1), new Vector3(1, 0, -1), new Vector3(0, 0, 1), new Vector3(10, 10, 10) };   // the last: the hull's top corner
            var mesh = new EnvironmentMesh(v, new[] { 0, 1, 2, 0, 2, 3, 4, 5, 6 });
            var kept = TerrainCell.WithoutHull(mesh);
            Check(kept.SequenceEqual(new[] { 4, 5, 6 }), $"only the inner triangle is kept ({string.Join(",", kept)})");
        });

        test("A cell edge crossing walks to just inside the edge and pushes well past it", () =>
        {
            if (!Directory.Exists(install)) return;
            var map = TerrainMap.Get(install);
            int a = map.Nearest(2087, new Vector3(16250, 0, 0)), b = map.Nearest(2088, new Vector3(-16250, 0, 0));
            Check(a >= 0 && b >= 0, "walkable squares by the E 07 / E 08 edge");
            var (walk, push) = map.CrossingPoints(a, b);
            Check(MathF.Abs(walk.X - (TerrainCell.Half - 96)) < 1 && push.X > TerrainCell.Half + 500 && MathF.Abs(push.Z - walk.Z) < 1, $"walk {walk}, push {push}");
        });

        if (!Directory.Exists(install)) return;

        test("E 07's heightfield is 512 x 512 at height = value / 4, and its props stand on it", () =>
        {
            var cell = TerrainCell.Load(install, 2087);
            Check(cell.Heights.Length == 512 * 512, "512 x 512 samples");
            Check(MathF.Abs(cell.Heights.Min() - 999) < 2 && MathF.Abs(cell.Heights.Max() - 4056) < 2, $"heights {cell.Heights.Min()}..{cell.Heights.Max()}");
            var gaps = cell.Props.Select(p => MathF.Abs(p.Y - cell.Height(p.X, p.Z))).OrderBy(g => g).ToList();
            Check(gaps[gaps.Count / 2] < 30, $"half the plants and stones are within 30 units of the ground (median {gaps[gaps.Count / 2]:F0})");
        });

        test("Doors in cells: Outzone 8's exit arrives at A 09's city gate; Tech Haven's door stands in E 07", () =>
        {
            var map = TerrainMap.Get(install);
            var arrival = map.ArrivalFrom(2009, 22, 5);
            Check(arrival != null && arrival.To == 22 && Vector2.Distance(new(arrival.Position.X, arrival.Position.Z), new(-8334, 1514)) < 5,
                $"A 09 door Index 5 at -8334,1514 (got {arrival?.Name} {arrival?.Position})");
            Check(map.Portals.Count(p => p.Cell == 2087 && p.To == 500) >= 2, "Tech Haven's entrance in E 07");
            Check(map.Portals.Any(p => p.Cell == 2093 && p.To == 650), "Canyon's entrance in E 13 (its model path carries stray bytes)");
            Check(map.Portals.Any(p => p.Cell == 2181 && p.To == 753), "the Military Base entrance in J 01");
            Check(!map.Portals.Any(p => p.Name.Contains("genrep", StringComparison.OrdinalIgnoreCase)), "outpost GenReps are not doors");
            Check(map.Landmarks.Any(l => l.Name == "Redrock Mine" && l.Cell == 2067), "outposts are landmarks (Redrock Mine in D 07)");
        });

        test("Plans: Outzone 9 to Tech Haven crosses A 07 .. E 07; city plans are unchanged", () =>
        {
            string logs = Path.Combine(Path.GetTempPath(), "traversal-terraintests-" + Guid.NewGuid().ToString("N")[..8]);
            Directory.CreateDirectory(logs);
            string cached = Path.Combine(Travel.Home, "logs", "door-graph.txt");
            if (File.Exists(cached)) File.Copy(cached, Path.Combine(logs, "door-graph.txt"));
            var travel = new Travel(install, id => throw new NotSupportedException("no baking in plan tests"), new Hud(), logs, 12, true);
            var plan = travel.WastelandPlan(23, 500, null);
            Check(plan != null, "a plan exists");
            var names = plan!.Sectors.Select(travel.SectorName).ToList();
            Check(plan.Sectors[0] == 23 && plan.Sectors[^1] == 500 && plan.Sectors.Contains(2007) && plan.Sectors.Contains(2087), $"plan: {string.Join(" > ", names)}");
            Check(plan.Segments.Count == 1 && plan.Segments[0].Exit?.To == 500, "one wasteland stretch, ending at Tech Haven's door");
            var cells = plan.Sectors.Where(travel.IsTerrain).ToList();
            for (int i = 1; i < cells.Count; i++)
                Check(Math.Abs(TerrainCell.Row(cells[i]) - TerrainCell.Row(cells[i - 1])) + Math.Abs(TerrainCell.Column(cells[i]) - TerrainCell.Column(cells[i - 1])) == 1,
                    $"{travel.SectorName(cells[i - 1])} and {travel.SectorName(cells[i])} share an edge");
            Check(travel.SectorPath(1, 102).SequenceEqual(new[] { 1, 102 }), "Plaza 1 to Plaza 4 is still one zone line");
            Check(travel.SectorPath(1, 500).Count > 0 && travel.Reach(1).ContainsKey(500), "Tech Haven is now reachable from Plaza 1");
        });

        test("A 07's city gate is not walled in (model hull removed): its navmesh reaches most of the cell", () =>
        {
            var nav = NavWorld.Bake(install, 2007);
            var island = nav.Island(new Vector3(-2296, 2889, 4735));
            var cell = TerrainCell.Load(install, 2007);
            int reached = 0;
            for (int j = 0; j < TerrainMap.N; j += 4)
                for (int i = 0; i < TerrainMap.N; i += 4)
                {
                    float x = -TerrainCell.Half + TerrainMap.Step * (i + 0.5f), z = -TerrainCell.Half + TerrainMap.Step * (j + 0.5f);
                    if (nav.OnIsland(new Vector3(x, cell.Height(x, z), z), island)) reached++;
                }
            Check(reached > 32 * 32 / 2, $"{reached} of {32 * 32} sample squares reached from the gate");
        });
    }
}
