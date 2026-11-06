using System.Diagnostics;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// A walk that covers every floor reachable from a start (a dungeon's arrival): one point per patch of floor, on every
/// level, visited nearest first by walking distance, so it works through the place a room at a time instead of
/// crossing it back and forth.
/// </summary>
internal static class SweepPlan
{
    /// <summary>Units across a patch of floor, and up between floors: one point to walk to in each.</summary>
    public const float Cell = 450, Floor = 150;
    /// <summary>A patch with less floor than this share of a full one (a stair, a ledge, a doorway) gets no point of its own.</summary>
    public const float MinShare = 0.08f;
    private const int Candidates = 12;

    public static float Area(Vector3[] poly)
    {
        float sum = 0;
        for (int i = 0; i < poly.Length; i++)
        {
            var a = poly[i]; var b = poly[(i + 1) % poly.Length];
            sum += a.X * b.Z - b.X * a.Z;
        }
        return MathF.Abs(sum) / 2;
    }

    /// <summary>One point per patch of reachable floor: the middle of the floor piece nearest the patch's middle, so it is on the floor.</summary>
    public static List<Vector3> Waypoints(NavWorld nav, Vector3 start)
    {
        var island = nav.Island(start);
        var patches = new Dictionary<(int, int, int), List<(Vector3 At, float Area)>>();
        foreach (var poly in nav.Polygons())
        {
            var centre = poly.Aggregate(Vector3.Zero, (a, b) => a + b) / poly.Length;
            // The piece itself on the island: a floor near it, above or below, is not enough (it gave points no walk reached).
            if (!nav.Snap(centre, out long under, out var on) || !island.Contains(under) || MathF.Abs(on.Y - centre.Y) > 20) continue;
            var key = ((int)MathF.Floor(centre.X / Cell), (int)MathF.Floor(centre.Z / Cell), (int)MathF.Round(centre.Y / Floor));
            if (!patches.TryGetValue(key, out var list)) patches[key] = list = new();
            list.Add((centre, Area(poly)));
        }
        var points = new List<Vector3>();
        foreach (var list in patches.Values)
        {
            float area = list.Sum(p => p.Area);
            if (area < MinShare * Cell * Cell) continue;
            var middle = list.Aggregate(Vector3.Zero, (a, p) => a + p.At * p.Area) / area;
            points.Add(list.OrderBy(p => Vector3.DistanceSquared(p.At, middle)).First().At);
        }
        return points;
    }

    /// <summary>Walking distance, or infinity with no complete route.</summary>
    public static float Walk(NavWorld nav, Vector3 from, Vector3 to)
    {
        var route = nav.Route(from, to, out bool complete);
        return route.Count > 1 && complete ? new RouteFollower(route).Total : float.PositiveInfinity;
    }

    /// <summary>Nearest by walking next, from the start: of the points nearest as the crow flies (a floor away counts extra), the shortest walk.</summary>
    public static List<Vector3> Order(NavWorld nav, IReadOnlyList<Vector3> points, Vector3 start)
    {
        var left = points.ToList();
        var tour = new List<Vector3>();
        var at = start;
        static float Near(Vector3 a, Vector3 b) => PointNavigation.Distance(a, b) + 3 * MathF.Abs(a.Y - b.Y);
        while (left.Count > 0)
        {
            var ranked = left.OrderBy(p => Near(at, p)).ToList();
            var best = ranked.Take(Candidates).Select(p => (At: p, Walk: Walk(nav, at, p))).MinBy(c => c.Walk);
            if (float.IsPositiveInfinity(best.Walk))
                best = ranked.Skip(Candidates).Select(p => (At: p, Walk: Walk(nav, at, p))).Where(c => !float.IsPositiveInfinity(c.Walk))
                    .DefaultIfEmpty((At: ranked[0], Walk: float.PositiveInfinity)).MinBy(c => c.Walk);
            tour.Add(best.At);
            left.Remove(best.At);
            at = best.At;
        }
        return tour;
    }

    /// <summary>The point to start at: the nearest walk from here.</summary>
    public static int Nearest(NavWorld nav, IReadOnlyList<Vector3> tour, Vector3 here)
    {
        var ranked = Enumerable.Range(0, tour.Count).OrderBy(i => Vector3.Distance(here, tour[i])).Take(Candidates).ToList();
        return ranked.Count == 0 ? 0 : ranked.MinBy(i => Walk(nav, here, tour[i]));
    }

    /// <summary>The plan for a sector, made once and kept in logs (local only), so a sweep picked up after a fight walks the same points.</summary>
    public static List<Vector3> Load(NavWorld nav, int sector, Vector3 start, string logs)
    {
        string file = Path.Combine(logs, $"sweep-{sector}.json");
        try
        {
            if (File.Exists(file) && JsonSerializer.Deserialize<Saved>(File.ReadAllText(file)) is { Cell: SweepPlan.Cell, Points.Length: > 0 } saved)
                return saved.Points.Select(p => new Vector3(p[0], p[1], p[2])).ToList();
        }
        catch (JsonException) { }
        var tour = Order(nav, Waypoints(nav, start), start);
        File.WriteAllText(file, JsonSerializer.Serialize(new Saved(Cell, tour.Select(p => new[] { p.X, p.Y, p.Z }).ToArray())));
        return tour;
    }

    private sealed record Saved(float Cell, float[][] Points);
}

/// <summary>Who the sweep stops for: the living NPC nearest by walking, no further than a set walk, on the floor it stands on.</summary>
internal static class SweepTargets
{
    public static (WorldEntity Npc, float Walk)? Next(NavWorld nav, Vector3 me, IEnumerable<WorldEntity> actors, IReadOnlySet<string> skip, float engage)
    {
        (WorldEntity Npc, float Walk)? best = null;
        foreach (var e in actors)
        {
            if (e.Identity.Kind != EntityKind.Npc || FollowCommand.Dead(e) || skip.Contains(FollowCommand.Id(e))) continue;
            if (Vector3.Distance(me, e.Position) > engage) continue;         // no walk is shorter than the straight line
            var route = nav.RouteNear(me, e.Position, out bool complete);
            if (route.Count < 2 || !complete || MathF.Abs(route[^1].Y - e.Position.Y) > 150) continue;
            float walk = new RouteFollower(route).Total;
            if (walk <= engage && (best == null || walk < best.Value.Walk)) best = (e, walk);
        }
        return best;
    }
}

/// <summary>
/// sweep [--world N] [--from K --left C] [--skip id,id] [--engage 1500] [--calibration speed,gain] [--pulse N]: live. Walks the
/// sector's sweep plan point by point, without running, and stops the moment a living NPC is within the engage walk, printing
/// "enemy &lt;id&gt; &lt;distance&gt; &lt;name&gt;". The hunt fights it and starts the sweep again from the point it was walking to.
/// Prints "sweep next K left C of N" before each point and "swept" once every point is walked. A point that can't be walked
/// to is skipped. Ends on F8, Stop, focus loss, or a zone change like every live walk.
/// </summary>
internal static class SweepCommand
{
    public const string Swept = "swept", EnemyWord = "enemy";
    public const float DefaultEngage = 1500, Reached = 120;
    private const int LookEveryMs = 250;
    private static readonly string[] SkipPoint = { "No complete route", "Steering exceeded its time limit", "Kept leaving the route", "Replanning found no route",
        "Off the gravity lift", DoorOpener.Failed };

    public static string Next(int k, int left, int count) => $"sweep next {k} left {left} of {count}";

    public static int Run(List<string> rest, string root, int pulse)
    {
        string? Option(string name)
        {
            int i = rest.IndexOf(name);
            if (i < 0 || i + 1 >= rest.Count) return null;
            string value = rest[i + 1]; rest.RemoveRange(i, 2); return value;
        }
        int? Number(string name) => Option(name) is { } text ? int.Parse(text, CultureInfo.InvariantCulture) : null;
        int? world = Number("--world"), from = Number("--from"), left = Number("--left");
        float engage = Option("--engage") is { } e ? float.Parse(e, CultureInfo.InvariantCulture) : DefaultEngage;
        var skip = (Option("--skip") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries).ToHashSet();
        LiveSteer.Calibration known = FollowWalk.Typical;
        if (Option("--calibration") is { } c)
        {
            var parts = c.Split(',');
            known = new(float.Parse(parts[0], CultureInfo.InvariantCulture), float.Parse(parts[1], CultureInfo.InvariantCulture));
        }

        using var reader = new PlayerReader(FollowCommand.ClientExecutable());
        var sample = reader.ReadSteady();
        int sector = reader.ReadSectorId(sample.World) ?? throw new InvalidOperationException("The current sector is unavailable. Finish zoning.");
        string install = Path.GetDirectoryName(reader.Executable)!;
        string Name(int s) => FollowCommand.Catalog(install).Areas.FirstOrDefault(a => a.WorldId == s)?.Name ?? $"sector {s}";
        if (world is { } w && w != sector) throw new InvalidOperationException($"You are in {Name(sector)}, not {Name(w)}: the sweep only walks there.");
        var nav = FollowCommand.Mapped(install, sector, root);
        string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
        using var hud = new Hud();
        var travel = new Travel(install, id => nav, hud, logs, pulse, false);
        var arrival = InsideMap.Build(install, nav, travel).Marks.FirstOrDefault(m => m.Kind == "arrival")?.Position ?? sample.Position;
        var tour = SweepPlan.Load(nav, sector, arrival, logs);
        if (tour.Count == 0) throw new InvalidOperationException($"No floor to sweep in {Name(sector)}.");
        int k = Math.Clamp(from ?? SweepPlan.Nearest(nav, tour, sample.Position), 0, tour.Count - 1), toGo = Math.Clamp(left ?? tour.Count, 0, tour.Count);
        Console.WriteLine($"Sweeping {Name(sector)}: point {k + 1} of {tour.Count}, {toGo} to go, stopping for any NPC within {engage:F0} units' walk. F8 stops.");
        Travel.FocusGame(reader.Window);
        string stamp = $"{DateTime.UtcNow:yyyyMMdd-HHmmss}";
        int blocks = 0;
        while (toGo > 0)
        {
            Console.WriteLine(Next(k, toGo, tour.Count));
            var clock = Stopwatch.StartNew();
            long lookAt = 0;
            (WorldEntity Npc, float Walk)? found = null;
            var steer = new LiveSteer(reader, nav, sector, tour[k], true, $"point {k + 1} of {tour.Count}", pulse,
                Path.Combine(logs, $"sweep-{stamp}-{k}.jsonl"), hud, run: false, countdown: false, known: known, near: Reached)
            {
                StopWhen = s =>
                {
                    if (clock.ElapsedMilliseconds < lookAt) return null;
                    lookAt = clock.ElapsedMilliseconds + LookEveryMs;
                    found = SweepTargets.Next(nav, s.Position, FollowCommand.ReadSnapshot(reader).Entities, skip, engage);
                    return found is { } f ? $"{f.Npc.Name} is {f.Walk:F0} units' walk away." : null;
                },
            };
            try { steer.Run(); }
            catch (LiveSteer.BlockedAt blocked) when (blocks < FollowCommand.GoRoundTries)
            {
                blocks++;
                FollowCommand.MapBlock(root, sector, blocked);
                nav = FollowCommand.Mapped(install, sector, root);
                continue;
            }
            catch (Exception error) when (error is LiveSteer.BlockedAt || (error is InvalidOperationException && SkipPoint.Any(error.Message.Contains)))
            {
                Console.WriteLine($"Skipping point {k + 1}: {error.Message}");
            }
            if (found is { } enemy)
            {
                var me = reader.ReadSteady().Position;
                Console.WriteLine($"{EnemyWord} {FollowCommand.Id(enemy.Npc)} {Vector3.Distance(me, enemy.Npc.Position):F0} {enemy.Npc.Name}");
                return 0;
            }
            blocks = 0;
            k = (k + 1) % tour.Count;
            toGo--;
        }
        Console.WriteLine(Next(k, 0, tour.Count));
        Console.WriteLine(Swept);
        hud.Post(Hud.Green, "SWEEP  done", $"Walked all {tour.Count} points of {Name(sector)}.");
        return 0;
    }
}
