using System.Collections.Concurrent;
using System.Diagnostics;
using System.Numerics;
using System.Text;
using System.Text.Json;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Offline coverage survey: bake every world, check every zone exit lands on the
/// navmesh, group exits that are walkable from each other, then chain sectors
/// through exits starting from one sector. No game input; reads files only.
/// </summary>
internal static class Survey
{
    public sealed record ExitInfo(string Name, int To, bool OnMesh, int Component);
    public sealed record WorldInfo(int WorldId, string Name, string Asset, string? Error, int Vertices, int Polygons,
        double BakeSeconds, int GroundPoints, int GroundOnMesh, List<ExitInfo> Exits);

    public static void Run(string install, int start, string startExit, string outDir, int parallelism)
    {
        var catalog = new EnvironmentCatalog(install);
        var areas = catalog.Areas;
        var assets = areas.GroupBy(a => a.AssetPath, StringComparer.OrdinalIgnoreCase).ToList();
        Console.WriteLine($"{areas.Count} worlds, {assets.Count} unique map files; baking with {parallelism} threads...");
        var results = new ConcurrentDictionary<string, WorldInfo>(StringComparer.OrdinalIgnoreCase);
        int done = 0; var clock = Stopwatch.StartNew();
        Parallel.ForEach(assets, new ParallelOptions { MaxDegreeOfParallelism = parallelism }, group =>
        {
            var area = group.First();
            results[group.Key] = Measure(install, area);
            int n = Interlocked.Increment(ref done);
            if (n % 20 == 0 || n == assets.Count) Console.WriteLine($"  {n}/{assets.Count} map files ({clock.Elapsed.TotalMinutes:F1} min)");
        });

        // Every world id (variants share a map file) gets its file's result.
        var worlds = areas.Select(a => results[a.AssetPath] with { WorldId = a.WorldId, Name = a.Name }).ToDictionary(w => w.WorldId);
        Directory.CreateDirectory(outDir);
        File.WriteAllText(Path.Combine(outDir, "survey.json"), JsonSerializer.Serialize(worlds.Values.OrderBy(w => w.WorldId), new JsonSerializerOptions { WriteIndented = true }));

        // Walk the sector graph. A state is (sector, exit group); arriving in a sector
        // puts you at the exit leading back where you came from.
        var reached = new Dictionary<int, string>();      // sector -> how it was reached
        var visited = new HashSet<(int, int)>();
        var queue = new Queue<(int Sector, int Component, string Via)>();
        if (!worlds.TryGetValue(start, out var first)) throw new InvalidOperationException($"No world {start}.");
        int startComponent = first.Exits.FirstOrDefault(e => e.Name.Equals(startExit, StringComparison.OrdinalIgnoreCase))?.Component ?? 0;
        queue.Enqueue((start, startComponent, "start")); reached[start] = "start";
        var unknownEntry = new HashSet<int>();
        while (queue.Count > 0)
        {
            var (sector, component, via) = queue.Dequeue();
            if (!visited.Add((sector, component)) || !worlds.TryGetValue(sector, out var w)) continue;
            foreach (var exit in w.Exits.Where(e => e.OnMesh && e.Component == component && e.To != sector))
            {
                if (!worlds.TryGetValue(exit.To, out var next) || next.Error != null || next.Polygons == 0) continue;
                reached.TryAdd(exit.To, $"{w.Name} via {exit.Name}");
                var back = next.Exits.Where(e => e.To == sector && e.OnMesh).Select(e => e.Component).Distinct().ToList();
                if (back.Count == 0) { unknownEntry.Add(exit.To); continue; }
                foreach (int c in back) queue.Enqueue((exit.To, c, exit.Name));
            }
        }

        File.WriteAllText(Path.Combine(outDir, "survey.md"), Report(worlds, reached, unknownEntry, start, clock.Elapsed));
        Console.WriteLine($"Done in {clock.Elapsed.TotalMinutes:F1} min. Reachable on foot from {first.Name}: {reached.Count} sectors. Report: {Path.Combine(outDir, "survey.md")}");
    }

    private static WorldInfo Measure(string install, EnvironmentArea area)
    {
        var clock = Stopwatch.StartNew();
        try
        {
            var nav = NavWorld.Bake(install, area.WorldId);
            var features = nav.World.Summary.Features;
            var ground = features.Where(f => f.Kind == "GroundPathPoint").ToList();
            int groundOn = ground.Count(g => nav.Snap(g.Position, out _, out _));
            var exits = features.Where(f => f.Kind == "WorldChange").ToList();
            var snapped = exits.Select(e => nav.Snap(e.Position, out _, out _, wide: true)).ToArray();
            // Union exits that a complete walking route joins.
            var parent = Enumerable.Range(0, exits.Count).ToArray();
            int Find(int i) => parent[i] == i ? i : parent[i] = Find(parent[i]);
            for (int i = 0; i < exits.Count; i++)
                for (int j = i + 1; j < exits.Count; j++)
                {
                    if (!snapped[i] || !snapped[j] || Find(i) == Find(j)) continue;
                    var route = nav.Route(exits[i].Position, exits[j].Position, out bool complete, wideTarget: true);
                    if (route.Count > 1 && complete) parent[Find(i)] = Find(j);
                }
            var list = exits.Select((e, i) => new ExitInfo(e.Name,
                int.TryParse(e.Properties.GetValueOrDefault("NextLevel"), out int to) ? to : 0, snapped[i], snapped[i] ? Find(i) : -1)).ToList();
            return new(area.WorldId, area.Name, area.AssetPath, null, nav.World.StaticGeometry.Vertices.Length, nav.Polygons().Count,
                clock.Elapsed.TotalSeconds, ground.Count, groundOn, list);
        }
        catch (Exception e) when (e is InvalidOperationException or InvalidDataException or IOException or ArgumentException or IndexOutOfRangeException or NullReferenceException)
        {
            return new(area.WorldId, area.Name, area.AssetPath, $"{e.GetType().Name}: {e.Message}", 0, 0, clock.Elapsed.TotalSeconds, 0, 0, new());
        }
    }

    private static string Report(Dictionary<int, WorldInfo> worlds, Dictionary<int, string> reached, HashSet<int> unknownEntry, int start, TimeSpan took)
    {
        var all = worlds.Values.ToList();
        var failed = all.Where(w => w.Error != null).ToList();
        var empty = all.Where(w => w.Error == null && w.Polygons == 0).ToList();
        var ok = all.Where(w => w.Error == null && w.Polygons > 0).ToList();
        var exits = ok.SelectMany(w => w.Exits).ToList();
        var sb = new StringBuilder();
        sb.AppendLine($"# Navmesh coverage survey\n\nOffline, from the installed world files; {took.TotalMinutes:F0} min. Agent: height 72, radius 16, step 24 (unmeasured guesses).\n");
        sb.AppendLine("| | Worlds |\n|---|---|");
        sb.AppendLine($"| Total world definitions | {all.Count} |");
        sb.AppendLine($"| Walkable navmesh built | {ok.Count} |");
        sb.AppendLine($"| Map read but no walkable floor found | {empty.Count} |");
        sb.AppendLine($"| Map could not be read/baked | {failed.Count} |");
        sb.AppendLine($"| **Reachable on foot from {worlds[start].Name}** (walk-through exits only) | **{reached.Count}** |");
        sb.AppendLine($"| ...of which the arrival point is unknown (no exit back) | {unknownEntry.Count} |\n");
        sb.AppendLine($"Zone exits in baked worlds: {exits.Count}; on the navmesh: {exits.Count(e => e.OnMesh)} ({100.0 * exits.Count(e => e.OnMesh) / Math.Max(1, exits.Count):F0}%).\n");

        static string Group(string name)
        {
            string n = name.ToUpperInvariant();
            foreach (var (key, label) in new[] { ("SEWER", "Sewers"), ("SUBWAY", "Subway"), ("APP", "Apartments"), ("SHOWROOM", "Apartments"), ("HQ", "Faction HQs"),
                ("PLAZA", "Plaza"), ("VIARIS", "Via Rosso"), ("PEPPER", "Pepper Park"), ("OUTZONE", "Outzone"), ("INDUSTRIAL", "Industrial"), ("JAIL", "Jail") })
                if (n.Contains(key)) return label;
            if (System.Text.RegularExpressions.Regex.IsMatch(n, @"^[A-Z] ?\d\d")) return "Wasteland (outdoor grid)";
            if (n.Contains("CAVE") || n.Contains("DUNGEON") || n.Contains("MINE") || n.Contains("BUNKER")) return "Caves/dungeons";
            return "Other";
        }
        sb.AppendLine("## By area type\n\n| Type | Worlds | Navmesh | Reachable on foot |\n|---|---|---|---|");
        foreach (var g in all.GroupBy(w => Group(w.Name)).OrderByDescending(g => g.Count()))
            sb.AppendLine($"| {g.Key} | {g.Count()} | {g.Count(w => w.Error == null && w.Polygons > 0)} | {g.Count(w => reached.ContainsKey(w.WorldId))} |");

        sb.AppendLine("\n## Reachable sectors\n");
        foreach (var (id, how) in reached.OrderBy(r => worlds[r.Key].Name))
            sb.AppendLine($"- {worlds[id].Name} ({id}){(unknownEntry.Contains(id) ? " (arrival point unknown)" : "")}: {how}");
        sb.AppendLine("\n## No walkable floor found (sample)\n");
        foreach (var w in empty.Take(40)) sb.AppendLine($"- {w.Name} ({w.WorldId}), {w.Vertices} vertices, {w.Asset}");
        sb.AppendLine("\n## Could not bake\n");
        foreach (var w in failed.Take(40)) sb.AppendLine($"- {w.Name} ({w.WorldId}): {w.Error}");
        return sb.ToString();
    }
}
