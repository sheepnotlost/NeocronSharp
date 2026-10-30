// Navmesh prototype: bake a Recast navmesh from a Neocron GBSP world (static
// model zero) and route/steer across it.
//   report   [worldId] [telemetry.jsonl ...]  bake, sample route, telemetry check, SVG
//   simulate [worldId] [--pulse N] [--pairs N]  controller on a virtual character
//   plan     <target>                          live position, read-only: route + SVG
//   steer    <target> [--pulse N]              live: walks the route (W + mouse-look)
// Targets: "x,y,z", "ground:Name" or "exit:Name" (a WorldChange) in the current world.
using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using NavmeshPrototype;
using NeocronSharp;
using NeocronSharp.Core;

const string DefaultInstall = @"C:\Games\Neocron Client\Neocron Evolution 2.5";
string root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, @"..\..\.."));
string outDir = Path.Combine(root, "out");
Directory.CreateDirectory(outDir);

string command = args.FirstOrDefault()?.ToLowerInvariant() ?? "report";
var rest = args.Skip(1).ToList();
string? Option(string name)
{
    int i = rest.IndexOf(name); if (i < 0 || i + 1 >= rest.Count) return null;
    string value = rest[i + 1]; rest.RemoveRange(i, 2); return value;
}
string? pulseOption = Option("--pulse");
int pulse = int.Parse(pulseOption ?? "6");
int pairs = int.Parse(Option("--pairs") ?? "60");
bool run = rest.Remove("--run");

try
{
    switch (command)
    {
        case "report": return Report(rest);
        case "simulate": return Simulate(rest);
        case "plan": return Live(rest, steer: false);
        case "steer": return Live(rest, steer: true);
        case "nearby": return FollowCommand.Nearby(rest);
        case "follow": return FollowCommand.Follow(rest, root, pulse, run);
        case "places":
        {
            var procs = Process.GetProcessesByName("neocronclient");
            string exe = procs.Length == 1 ? procs[0].MainModule?.FileName ?? "" : throw new InvalidOperationException("Open exactly one Neocron client.");
            foreach (var p in procs) p.Dispose();
            using var reader = new PlayerReader(exe);
            var here = reader.ReadSample().Position;
            int sec = reader.ReadSectorId(reader.ReadSample().World) ?? throw new InvalidOperationException("Zoning.");
            var nav = BakeLogged(Path.GetDirectoryName(exe)!, sec);
            Console.WriteLine($"Player at {here}");
            foreach (var f in nav.World.Summary.Features.Where(f => f.Kind is "GroundPathPoint" or "WorldChange"))
            {
                var r = nav.Route(here, f.Position, out bool ok, f.Kind == "WorldChange");
                if (r.Count > 1 && ok) Console.WriteLine($"{new RouteFollower(r).Total,7:F0}  {r.Count,3} corners  {(f.Kind == "WorldChange" ? "exit:" : "ground:")}{f.Name}");
            }
            return 0;
        }
        case "travel":
        {
            // travel <sectorId> [target in that sector | arrive]
            if (rest.Count < 1 || !int.TryParse(rest[0], out int toSector)) throw new InvalidOperationException("Usage: travel <sectorId> [target]");
            string targetSpec = rest.Count > 1 ? rest[1] : Travel.Arrive;
            var procs = Process.GetProcessesByName("neocronclient");
            string exe = procs.Length == 1 ? procs[0].MainModule?.FileName ?? "" : throw new InvalidOperationException("Open exactly one Neocron client and log in.");
            foreach (var p in procs) p.Dispose();
            using var reader = new PlayerReader(exe);
            var baked = new Dictionary<int, NavWorld>();
            string install = Path.GetDirectoryName(exe)!;
            using var hud = new Hud();
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var travel = new Travel(install, id => baked.TryGetValue(id, out var n) ? n : baked[id] = BakeLogged(install, id), hud, logs, pulse, run);
            travel.Go(reader, toSector, targetSpec, targetSpec == Travel.Arrive ? travel.SectorName(toSector) : targetSpec);
            return 0;
        }
        case "where":
        {
            var procs = Process.GetProcessesByName("neocronclient");
            string exe = procs.Length == 1 ? procs[0].MainModule?.FileName ?? "" : throw new InvalidOperationException("Open exactly one Neocron client.");
            foreach (var p in procs) p.Dispose();
            using var reader = new PlayerReader(exe);
            var s0 = reader.ReadSample();
            Console.WriteLine($"sector {reader.ReadSectorId(s0.World)} at {s0.Position} facing {s0.Forward}; map rotation {reader.ReadMapRotation(s0.World)?.ToString() ?? "unknown"}");
            return 0;
        }
        case "actors":
        {
            // Read-only: every actor-registry node (class, position), e.g. to find the subway train.
            var procs = Process.GetProcessesByName("neocronclient");
            string exe = procs.Length == 1 ? procs[0].MainModule?.FileName ?? "" : throw new InvalidOperationException("Open exactly one Neocron client.");
            foreach (var p in procs) p.Dispose();
            using var reader = new PlayerReader(exe);
            var me = reader.ReadSample();
            foreach (var a in reader.ReadRegistryActors().OrderBy(a => a.Position is { } q ? PointNavigation.Distance(q, me.Position) : 1e9f))
                Console.WriteLine($"key {a.Key,8} class {a.TableRva:x8} physics {a.Physics:x}" + (a.Position is { } q
                    ? $" at {q.X:F0},{q.Y:F0},{q.Z:F0} ({PointNavigation.Distance(q, me.Position):F0} away)" + (a.Forward is { } f ? $" facing {f.X:F2},{f.Z:F2}" : "")
                    : ""));
            Console.WriteLine($"player at {me.Position}");
            if (rest.Count >= 1 && int.TryParse(rest[0], out int dumpKey))
                foreach (var a in reader.ReadRegistryActors().Where(a => a.Key == dumpKey))
                {
                    var f = reader.ReadActorFloats(a.Physics, 0x10, 0x200 / 4);
                    for (int i = 0; i < f.Length; i += 8)
                        Console.WriteLine($"+{0x10 + i * 4:x3}: " + string.Join(" ", f.Skip(i).Take(8).Select(v => float.IsFinite(v) && MathF.Abs(v) < 1e7 && (v == 0 || MathF.Abs(v) > 1e-6) ? v.ToString("G6") : "~")));
                }
            return 0;
        }
        case "toward":
        {
            // toward <sector> x,z x,z : offline, where the walkable floor toward the second point ends.
            var nav = BakeLogged(DefaultInstall, int.Parse(rest[0]));
            Vector3 P(string t) { var f = t.Split(',').Select(v => float.Parse(v, System.Globalization.CultureInfo.InvariantCulture)).ToArray(); return new(f[0], f.Length > 2 ? f[1] : -250, f[^1]); }
            var from = P(rest[1]); var to = P(rest[2]);
            if (nav.Snap(from, out _, out var on, wide: true)) from = on;
            var r = nav.RouteToward(from, to);
            var vs = nav.World.StaticGeometry.Vertices;
            Console.WriteLine($"sector spans x {vs.Min(v => v.X):F0}..{vs.Max(v => v.X):F0}, z {vs.Min(v => v.Z):F0}..{vs.Max(v => v.Z):F0}");
            Console.WriteLine($"{r.Count} corners: " + string.Join(" -> ", r.Select(c => $"({c.X:F0},{c.Z:F0})")));
            return 0;
        }
        case "simcity":
        {
            // Offline: for every city sector, every street neighbour and every way in, choose the
            // zone line as a live trip would, drive the simulated character there on the real
            // navmesh (live lag and mouse error), and check the push corridor leads on past it.
            int[] city = rest.Count > 0 ? rest.Select(int.Parse).ToArray() : new[] { 1, 2, 101, 102, 3, 4, 401, 5, 6, 7, 8, 801 };
            string logs = Path.Combine(root, "logs");
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), logs, pulse, run);
            travel.LoadLearning();
            int pass = 0, fail = 0;
            var random = new Random(7);
            foreach (int sector in city)
            {
                var nav = BakeLogged(DefaultInstall, sector);
                var verts = nav.World.StaticGeometry.Vertices;
                var centre = new Vector3((verts.Min(v => v.X) + verts.Max(v => v.X)) / 2, 0, (verts.Min(v => v.Z) + verts.Max(v => v.Z)) / 2);
                int? rotation = travel.RotationFor(sector, null);
                var exits = travel.Exits(sector).ToList();
                var neighbours = travel.Neighbours(sector).Where(travel.HasMap).ToList();
                foreach (int to in neighbours)
                    foreach (int from in neighbours.Where(n => n != to).DefaultIfEmpty(to))
                    {
                        // Entry: where people arriving from 'from' appear (that exit record), else the sector's first ground point.
                        var entry = exits.Where(e => e.To == from).Select(e => e.Exit.Position).FirstOrDefault();
                        if (entry == default || !nav.Snap(entry, out _, out var start, wide: true)) { Console.WriteLine($"  skip {travel.SectorName(sector)} from {travel.SectorName(from)}: entry not on the mesh"); continue; }
                        var best = exits.Where(e => e.To == to)
                            .Select(e => (e.Exit, Line: travel.LineFor(sector, e.Exit, rotation, to, centre, nav)))
                            .Where(e => e.Line.Walk != default)
                            .Select(e => (e.Exit, e.Line, Route: nav.RouteNear(start, e.Line.Walk, out bool ok), Ok: ok))
                            .Where(e => e.Route.Count > 1 && e.Ok)
                            .OrderBy(e => new RouteFollower(e.Route).Total).FirstOrDefault();
                        string label = $"{travel.SectorName(sector)}: in from {travel.SectorName(from)}, out to {travel.SectorName(to)}";
                        if (best.Exit == null) { fail++; Console.WriteLine($"  FAIL {label}: no walkable route to any zone line"); continue; }
                        var end = best.Route[^1];
                        var outcome = Simulator.Run(nav, start, end, 280, 0.0024f, 1.3f, 24, random);
                        // Past the line: does the floor carry on toward the push point (so the push has somewhere to go)?
                        float pushRoom = 0;
                        string how = best.Line.Push == null ? "exit record" : best.Line.Key == null ? "learned/outward"
                            : travel.IsPastRecord(best.Line.Key) ? "past exit record" : "map arrow";
                        if (best.Line.Push is { } push)
                        {
                            var corridor = nav.RouteToward(end, push);
                            pushRoom = corridor.Count > 1 ? new RouteFollower(corridor).Total : 0;
                        }
                        bool ok = outcome.Arrived;
                        if (ok) pass++; else fail++;
                        Console.WriteLine($"  {(ok ? "ok  " : "FAIL")} {label}: {how}, walk {new RouteFollower(best.Route).Total:F0} units, " +
                            $"sim {(ok ? $"{outcome.Seconds:F0}s" : outcome.Reason)}, push room {pushRoom:F0}");
                    }
            }
            Console.WriteLine($"{pass} legs pass, {fail} fail");
            return fail == 0 ? 0 : 1;
        }
        case "preview":
        {
            // preview <toSector> [target]: plan the whole trip and estimate every leg, without
            // moving. Uses the live position when the game is open, else starts in Plaza 1.
            // Prints one JSON line (for the Traversal tab) and writes out/preview.svg (first leg).
            int toSector = int.Parse(rest[0]);
            string targetSpec = rest.Count > 1 ? rest[1] : Travel.Arrive;
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var baked = new Dictionary<int, NavWorld>();
            NavWorld Nav(int id) => baked.TryGetValue(id, out var n) ? n : baked[id] = NavWorld.Bake(DefaultInstall, id);
            var travel = new Travel(DefaultInstall, Nav, new Hud(), logs, pulse, run);
            travel.LoadLearning();
            int here = 1; Vector3? live = null; int? liveRotation = null; string source = "Plaza 1 (game not open)";
            try
            {
                var procs = Process.GetProcessesByName("neocronclient");
                string exe = procs.Length == 1 ? procs[0].MainModule?.FileName ?? "" : "";
                foreach (var pr in procs) pr.Dispose();
                if (exe.Length > 0)
                {
                    using var reader = new PlayerReader(exe);
                    var sample = reader.ReadSample();
                    here = reader.ReadSectorId(sample.World) ?? here;
                    live = sample.Position; liveRotation = reader.ReadMapRotation(sample.World);
                    source = "your position";
                }
            }
            catch (InvalidOperationException) { }
            var chain = here == toSector ? new List<int> { here } : travel.SectorPath(here, toSector);
            var legs = new List<object>();
            string? picture = null;
            float total = 0;
            bool ok = chain.Count > 0 && chain[^1] == toSector;
            // A trip across the wasteland: every leg as Go walks it (cell edges, wasteland doors), no picture.
            bool wasteland = ok && chain.Any(travel.IsTerrain);
            if (wasteland)
            {
                var planned = travel.PlanTrip(here, toSector, live, Nav, simulate: false);
                foreach (var l in planned.Where(l => l.Method is not ("replanned" or "backed out")))
                {
                    legs.Add(new { from = travel.SectorName(l.From), to = travel.SectorName(l.To), method = l.Method, length = MathF.Round(l.Length), note = l.Note });
                    total += l.Length;
                }
                ok = planned.Count > 0 && planned[^1].To == toSector && planned.Where(l => l.Method is not ("replanned" or "backed out")).All(l => l.Ok);
            }
            for (int i = 0; ok && !wasteland && i + 1 < chain.Count; i++)
            {
                int from = chain[i], to = chain[i + 1];
                var nav = Nav(from);
                var verts = nav.World.StaticGeometry.Vertices;
                var centre = new Vector3((verts.Min(v => v.X) + verts.Max(v => v.X)) / 2, 0, (verts.Min(v => v.Z) + verts.Max(v => v.Z)) / 2);
                // Start: where you stand, else where people arriving from the previous sector appear.
                Vector3? start = i == 0 ? live : null;
                if (start == null && i > 0)
                    start = travel.Exits(from).Where(e => e.To == chain[i - 1]).Select(e => (Vector3?)e.Exit.Position).FirstOrDefault();
                start ??= travel.Exits(from).Select(e => (Vector3?)e.Exit.Position).FirstOrDefault();
                if (start is not { } st || !nav.Snap(st, out _, out var snapped, wide: true)) { legs.Add(new { from = travel.SectorName(from), to = travel.SectorName(to), method = "unknown", length = 0f, note = "start not on the map" }); continue; }
                int? rotation = travel.RotationFor(from, i == 0 ? liveRotation : null);
                var best = travel.Exits(from).Where(e => e.To == to)
                    .Select(e => (e.Exit, Line: travel.LineFor(from, e.Exit, rotation, to, centre, nav)))
                    .Where(e => e.Line.Walk != default)
                    .Select(e => (e.Exit, e.Line, Route: nav.RouteNear(snapped, e.Line.Walk, out bool routed), Routed: routed))
                    .Where(e => e.Route.Count > 1 && e.Routed)
                    .OrderBy(e => new RouteFollower(e.Route).Total).FirstOrDefault();
                if (best.Exit == null) { ok = false; legs.Add(new { from = travel.SectorName(from), to = travel.SectorName(to), method = "none", length = 0f, note = "no walkable route to a zone line" }); break; }
                float length = new RouteFollower(best.Route).Total;
                total += length;
                string method = best.Line.Push == null ? "exit record" : best.Line.Key == null
                    ? (travel.HasLearnedCrossing(from, to) ? "learned crossing" : "corridor tip (no map arrows)")
                    : travel.IsPastRecord(best.Line.Key) ? "floor past the exit record" : "map arrow";
                legs.Add(new { from = travel.SectorName(from), to = travel.SectorName(to), method, length = MathF.Round(length) });
                if (i == 0)
                {
                    picture = Path.Combine(outDir, "preview.svg");
                    var ground = nav.World.Summary.Features.Where(f => f.Kind == "GroundPathPoint").Select(f => f.Position);
                    File.WriteAllText(picture, Render.Svg(nav, best.Route, ground, Array.Empty<Vector3>(), live));
                }
            }
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new
            {
                ok, start = source, from = travel.SectorName(here), to = travel.SectorName(toSector),
                chain = chain.Select(travel.SectorName), legs, totalUnits = MathF.Round(total),
                // Running averaged ~125-200 u/s live including turns; quote a range.
                minutes = new[] { MathF.Round(total / 200 / 60, 1), MathF.Round(total / 125 / 60, 1) },
                target = targetSpec, picture,
            }));
            return ok ? 0 : 1;
        }
        case "scanworlds":
        {
            // Offline timing/inventory: load every world's entities once.
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), root, pulse, run);
            var clock = Stopwatch.StartNew(); int ok = 0, bad = 0, changes = 0;
            foreach (var area in travel.Areas)
            {
                try { changes += travel.Features(area.WorldId).Count(f => f.Kind == "WorldChange"); ok++; }
                catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException) { bad++; }
            }
            Console.WriteLine($"{travel.Areas.Count} areas: {ok} loaded, {bad} failed, {changes} WorldChanges, {clock.Elapsed.TotalSeconds:F1} s");
            return 0;
        }
        case "reachreport":
        {
            // Offline: over EVERY exit and game-routed door (no walking rules), which sectors can a
            // chain of zone lines and doors get to from Plaza 1, and which of those the walker can
            // use. Shows what blocks the rest (no world file, no street map, interior in the way).
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), logs, pulse, run);
            var walk = travel.Reach(1);
            var previous = new Dictionary<int, int> { [1] = 1 }; var queue = new Queue<int>(new[] { 1 });
            var unloadable = new SortedSet<int>();
            while (queue.Count > 0)
            {
                int s0 = queue.Dequeue();
                List<(NeocronSharp.Core.EnvironmentFeature Exit, int To)> exits;
                try { _ = travel.Features(s0); exits = travel.Links(s0).ToList(); }
                catch (Exception e) when (e is IOException or InvalidDataException) { unloadable.Add(s0); continue; }
                foreach (var (_, to) in exits) if (previous.TryAdd(to, s0)) queue.Enqueue(to);
            }
            string Kind(int s) => unloadable.Contains(s) ? "no world file" : s == Travel.Subway ? "subway" : travel.HasMap(s) ? "street" : "interior";
            // Why the walker does not get there: one-way links, or only by train.
            string Why(int s)
            {
                var chain = Chain(s);
                int i = chain.FindIndex(c => !walk.ContainsKey(c));
                int from = chain[i - 1], to = chain[i];
                return from == Travel.Subway ? "only by subway train" : !travel.Links(to).Any(b => b.To == from) ? $"no way back from {travel.SectorName(to)} to {travel.SectorName(from)}" : "beyond the hop limit";
            }
            List<int> Chain(int s) { var c = new List<int> { s }; while (previous[c[^1]] != c[^1]) c.Add(previous[c[^1]]); c.Reverse(); return c; }
            Console.WriteLine($"{previous.Count} sectors linked from Plaza 1 by exits; the walker reaches {walk.Count}.");
            foreach (var group in previous.Keys.Where(s => !walk.ContainsKey(s)).GroupBy(Kind).OrderBy(g => g.Key))
            {
                Console.WriteLine($"-- not reached, {group.Key}: {group.Count()}");
                foreach (int s in group.OrderBy(travel.SectorName).Take(rest.Contains("--all") ? int.MaxValue : 12))
                    Console.WriteLine($"   {travel.SectorName(s)} ({s}) [{(unloadable.Contains(s) ? "-" : Why(s))}]: " + string.Join(" > ", Chain(s).Select(c => $"{travel.SectorName(c)}[{Kind(c)[0]}]")));
            }
            return 0;
        }
        case "zones":
        {
            // JSON for the Traversal tab: every sector reachable on foot from Plaza 1, with its hop count.
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), logs, pulse, run);
            var hops = travel.Reach(1);
            var zones = hops.Select(h => new { id = h.Key, name = travel.SectorName(h.Key), hopsFromPlaza1 = h.Value }).OrderBy(z => z.name);
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(zones));
            return 0;
        }
        case "allplaces":
        {
            // JSON for Nav Walker: every zone reachable on foot, each followed by the doors in it
            // (shops, clubs, HQs, the subway), counted in zone lines from where you stand
            // (from Plaza 1 when the game is not open).
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), logs, pulse, run);
            int start = 1; Vector3? at = null;
            try
            {
                var procs = Process.GetProcessesByName("neocronclient");
                string exe = procs.Length == 1 ? procs[0].MainModule?.FileName ?? "" : "";
                foreach (var pr in procs) pr.Dispose();
                if (exe.Length > 0)
                {
                    using var reader = new PlayerReader(exe);
                    var sample = reader.ReadSample();
                    if (reader.ReadSectorId(sample.World) is int live) { start = live; at = sample.Position; }
                }
            }
            catch (Exception e) when (e is InvalidOperationException or IOException or System.ComponentModel.Win32Exception) { }
            var hops = travel.Reach(start);
            var streets = travel.Streets(start);
            // One row per (zone, target): the zone itself, the doors in it, then the Nav-Ray's
            // destinations, which rename a door they share and add apartment doors.
            var rows = new Dictionary<(int Zone, string Target), (string Name, string Kind, string Category)>();
            // Rows that never merge with another: objects (two can round to one spot) and the
            // Nav-Ray's "nearest" rows (several can pick the same object, which keeps its own row).
            var extra = new List<((int Zone, string Target) Key, (string Name, string Kind, string Category) Value)>();
            static bool Unreadable(Exception e) => e is IOException or InvalidDataException or ArgumentException;
            foreach (int zone in streets)
            {
                rows[(zone, Travel.Arrive)] = (travel.SectorName(zone), "Zone", "");
                // Doors: exits into named places with no street map; one per destination.
                List<(NeocronSharp.Core.EnvironmentFeature Exit, int To)> exits;
                try { exits = travel.Exits(zone).ToList(); } catch (Exception e) when (Unreadable(e)) { continue; }
                foreach (var door in exits.Where(e => e.To != zone && (e.To == Travel.Subway || !travel.HasMap(e.To)) && !travel.SectorName(e.To).StartsWith("sector ", StringComparison.Ordinal))
                             .GroupBy(e => e.To).Select(g => g.First()))
                    rows[(zone, "exit:" + door.Exit.Name)] = (travel.SectorName(door.To), "Entrance", "");
            }
            // One bad menu table must not lose the whole list: without it, no Nav-Ray names.
            List<NavRayCatalog.Entry> navRay;
            try { navRay = NavRayCatalog.Read(DefaultInstall, travel, streets); }
            catch (Exception e) when (Unreadable(e) || e is KeyNotFoundException or FormatException or OverflowException)
            {
                Console.Error.WriteLine($"Nav-Ray menus unreadable: {e.Message}");
                navRay = new();
            }
            foreach (var e in navRay.Where(e => e.Target != null && hops.ContainsKey(e.Zone)))
            {
                var key = (e.Zone, e.Target!);
                // The first Nav-Ray entry for a place names it (CityAdmin is listed twice).
                if (!rows.TryGetValue(key, out var row)) rows[key] = (e.Name, e.Kind, e.Category);
                else if (row.Category == "") rows[key] = (row.Kind == "Zone" ? row.Name : e.Name, row.Kind, e.Category);
            }
            // Objects and NPCs from each street's spawn file. Doors already listed (an exit
            // within 250 units) are not repeated. Targets are positions: the walk ends at the
            // nearest floor (shopkeepers stand behind counters).
            static string Spot(Vector3 v) => string.Create(System.Globalization.CultureInfo.InvariantCulture, $"{v.X:F0},{v.Y:F0},{v.Z:F0}");
            var objects = new WorldObjects(DefaultInstall, travel);
            var found = new List<(WorldObjects.Place Place, string Name)>();
            string[] doorKinds = { "Apartment", "Sewer entrance", "Entrance", "Access door", "Paid entrance" };
            foreach (int zone in streets)
            {
                List<WorldObjects.Place> here;
                List<Vector3> doors;
                try
                {
                    here = objects.In(zone);
                    doors = travel.Features(zone).Where(f => f.Kind == "WorldChange").Select(f => f.Position).ToList();
                }
                catch (Exception e) when (Unreadable(e)) { continue; }
                foreach (var same in here.Where(p => !(doorKinds.Contains(p.Kind) && doors.Any(d => Vector3.Distance(d, p.Position) < 250))).GroupBy(p => p.Name))
                {
                    int n = 0, count = same.Count();
                    // Repeated names in one zone (two GenReps, seven GoGuardians) get a number, west to east.
                    foreach (var p in same.OrderBy(p => p.Position.X).ThenBy(p => p.Position.Z))
                    {
                        n++;
                        string name = count > 1 ? $"{p.Name} {n}" : p.Name;
                        found.Add((p, name));
                        // A Nav-Ray entry already placed at this spot (Hacknet terminals) names it once.
                        if (!rows.ContainsKey((zone, Spot(p.Position)))) extra.Add(((zone, Spot(p.Position)), (name, p.Kind, "")));
                    }
                }
            }
            // The Nav-Ray's "nearest" entries: the closest one from where you stand, fewest zone
            // lines first, then straight-line distance (in your zone; else to the zone's first one).
            var nearestDone = new List<NavRayCatalog.Entry>();
            foreach (var e in navRay.Where(e => e.Target == null && e.Type is NavRayCatalog.GenRep or NavRayCatalog.GoGuardian or NavRayCatalog.CityCom or NavRayCatalog.Trader))
            {
                Func<WorldObjects.Place, bool> match = e.Type switch
                {
                    NavRayCatalog.GenRep => p => p.Kind == "GenRep",
                    NavRayCatalog.GoGuardian => p => p.Kind == "GoGuardian",
                    NavRayCatalog.CityCom => p => p.Kind == "CityCom",
                    _ => p => p.Kind == "Trader" && NavRayCatalog.TraderWords.TryGetValue(e.Aux, out var words)
                        && p.Labels.Any(l => words.Any(w => l.Contains(w, StringComparison.OrdinalIgnoreCase))),
                };
                var best = found.Where(f => match(f.Place)).OrderBy(f => hops[f.Place.World])
                    .ThenBy(f => f.Place.World == start && at is { } me ? Vector3.Distance(me, f.Place.Position) : 0).FirstOrDefault();
                if (best.Place == null) continue;
                nearestDone.Add(e);
                extra.Add(((best.Place.World, Spot(best.Place.Position)), ($"Nearest {Title(e.Name)}: {best.Name}", "Nearest", e.Category)));
            }
            // Outposts and landmarks out in the wasteland (from the world map's tables), at a
            // standing spot by each gate on the cell's navmesh. Cached; see WastelandPlaces.
            try
            {
                foreach (var w in WastelandPlaces(travel, logs, refresh: false).Where(w => w.OnNavmesh))
                    extra.Add(((w.Zone, w.Target), (w.Name, w.Kind, "Wasteland")));
            }
            catch (Exception e) when (Unreadable(e) || e is InvalidOperationException or JsonException) { }
            static string Title(string s) => System.Globalization.CultureInfo.InvariantCulture.TextInfo.ToTitleCase(s.ToLowerInvariant());
            int Rank(string kind) => kind switch { "Zone" => 0, "Nearest" => 1, "Entrance" => 2, _ => 3 };
            var places = rows.Select(r => (r.Key, r.Value)).Concat(extra).OrderBy(r => hops.GetValueOrDefault(r.Key.Zone, 99)).ThenBy(r => travel.SectorName(r.Key.Zone)).ThenBy(r => Rank(r.Value.Kind)).ThenBy(r => r.Value.Name)
                .Select(r => new { zone = r.Key.Zone, zoneName = travel.SectorName(r.Key.Zone), away = hops.GetValueOrDefault(r.Key.Zone, 99), target = r.Key.Target,
                    name = r.Value.Name, kind = r.Value.Kind, category = r.Value.Category });
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new
            {
                here = new { zone = start, name = travel.SectorName(start), live = at != null, x = at?.X ?? 0, z = at?.Z ?? 0 },
                places,
                notPlaced = navRay.Where(e => e.Target == null && !nearestDone.Contains(e)).Select(e => new { category = e.Category, name = e.Name, why = e.Why }),
            }));
            return 0;
        }
        case "zoneplaces":
        {
            // JSON for the Traversal tab: named places (ground points, exits) in one sector.
            int sector = int.Parse(rest[0]);
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), logs, pulse, run);
            var places = travel.Features(sector).Where(f => f.Kind is "GroundPathPoint" or "WorldChange")
                .Select(f => new
                {
                    target = (f.Kind == "WorldChange" ? "exit:" : "ground:") + f.Name,
                    label = f.Kind == "WorldChange"
                        ? $"Exit to {(int.TryParse(f.Properties.GetValueOrDefault("NextLevel"), out int to) ? travel.SectorName(to) : "?")} ({f.Name})"
                        : f.Name,
                })
                .OrderBy(p => p.target.StartsWith("exit:")).ThenBy(p => p.label);
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(places));
            return 0;
        }
        case "checkcity":
        {
            // Offline: entering each sector from each neighbour, can you walk to every other neighbour's exit?
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), logs, pulse, run);
            var sectors = rest.Select(int.Parse).ToList();
            int good = 0, bad = 0;
            foreach (int s0 in sectors)
            {
                NavWorld nav;
                try { nav = BakeLogged(DefaultInstall, s0); } catch (Exception e) when (e is InvalidOperationException or InvalidDataException or IOException) { Console.WriteLine($"  {s0}: cannot bake: {e.Message}"); continue; }
                var exits = travel.Exits(s0).ToList();
                var neighbours = travel.Neighbours(s0).ToList();
                foreach (int from in neighbours)
                    foreach (int to in neighbours.Where(n => n != from))
                    {
                        // Best case over all entry exits (from 'from') and all onward exits (to 'to').
                        float best = float.MaxValue; string? how = null;
                        foreach (var (entry, _) in exits.Where(e => e.To == from))
                            foreach (var (onward, _) in exits.Where(e => e.To == to))
                            {
                                if (!nav.Snap(entry.Position, out _, out var start, wide: true)) continue;
                                var r = nav.Route(start, onward.Position, out bool ok, wideTarget: true);
                                if (r.Count > 1 && ok && new RouteFollower(r).Total < best) { best = new RouteFollower(r).Total; how = $"{entry.Name}->{onward.Name}"; }
                            }
                        bool pass = how != null; if (pass) good++; else bad++;
                        Console.WriteLine($"  {(pass ? "ok  " : "FAIL")} {travel.SectorName(s0)}: from {travel.SectorName(from)} to {travel.SectorName(to)}{(pass ? $"  {best:F0} units ({how})" : "")}");
                    }
            }
            Console.WriteLine($"{good} walkable, {bad} not");
            return 0;
        }
        case "doors":
        {
            // doors <sector>: offline, for each exit the nearest moving model (door) in the world file.
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), root, pulse, run);
            int sector = int.Parse(rest[0]);
            var models = travel.Features(sector).Where(f => f.Kind == "ModelController").ToList();
            Console.WriteLine($"{models.Count} moving models");
            if (rest.Contains("--all"))
                foreach (var f in travel.Features(sector).Where(f => f.Kind == "WorldChange"))
                    Console.WriteLine($"  {f.Name} at {f.Position.X:F0},{f.Position.Z:F0}: " + string.Join(" ", f.Properties.Where(p => p.Key != "Origin").Select(p => $"{p.Key}={p.Value}")));
            foreach (var (exit, to) in travel.Exits(sector))
            {
                var near = models.OrderBy(m => Vector3.Distance(m.Position, exit.Position)).FirstOrDefault();
                Console.WriteLine($"{exit.Name,-16} -> {travel.SectorName(to),-30} at {exit.Position.X:F0},{exit.Position.Y:F0},{exit.Position.Z:F0}" +
                    (near == null ? "" : $"  nearest model {near.Name} at {near.Position.X:F0},{near.Position.Y:F0},{near.Position.Z:F0} ({Vector3.Distance(near.Position, exit.Position):F0} away) " +
                        string.Join(" ", near.Properties.Where(p => p.Key is not ("Origin" or "classname")).Select(p => $"{p.Key}={p.Value}"))));
            }
            return 0;
        }
        case "subway":
        {
            // subway: offline, the subway's stations, which share a floor, and the walks between them (Subway.cs).
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), Path.Combine(root, "logs"), pulse, run);
            travel.SubwayReport(BakeLogged(DefaultInstall, Travel.Subway));
            return 0;
        }
        case "exits":
        {
            var travel = new Travel(DefaultInstall, id => throw new NotSupportedException(), new Hud(), root, pulse, run);
            int from = int.Parse(rest[0]);
            foreach (var (exit, to) in travel.Exits(from)) Console.WriteLine($"{exit.Name,-16} -> {to,5} {travel.SectorName(to),-28} at {exit.Position.X:F0},{exit.Position.Z:F0}");
            if (rest.Count > 1) Console.WriteLine("path: " + string.Join(" -> ", travel.SectorPath(from, int.Parse(rest[1])).Select(travel.SectorName)));
            return 0;
        }
        case "runprobe":
        {
            // Which key combination makes the character run? Short presses, distance measured.
            var procs = Process.GetProcessesByName("neocronclient");
            string exe = procs.Length == 1 ? procs[0].MainModule?.FileName ?? "" : throw new InvalidOperationException("Open exactly one Neocron client.");
            foreach (var p in procs) p.Dispose();
            using var reader = new PlayerReader(exe);
            Thread.Sleep(6000);   // time to bring the game forward
            reader.RequireForeground();
            void K(ushort scan, bool up) => KeyProbe.Send(scan, up);
            float Measure(string name, Action down, Action up)
            {
                Thread.Sleep(400);
                var a = reader.ReadSample().Position; down(); Thread.Sleep(300); up(); Thread.Sleep(400);
                var b = reader.ReadSample().Position; float d = PointNavigation.Distance(a, b);
                Console.WriteLine($"{name,-22} {d,6:F1} units in 0.3 s");
                return d;
            }
            Measure("W only", () => K(0x11, false), () => K(0x11, true));
            Measure("Shift, then W", () => { K(0x2a, false); K(0x11, false); }, () => { K(0x11, true); K(0x2a, true); });
            Measure("W, then Shift", () => { K(0x11, false); Thread.Sleep(30); K(0x2a, false); }, () => { K(0x2a, true); K(0x11, true); });
            Measure("Caps Lock toggle + W", () => { K(0x3a, false); K(0x3a, true); Thread.Sleep(50); K(0x11, false); }, () => { K(0x11, true); });
            Measure("W after Caps Lock", () => K(0x11, false), () => K(0x11, true));
            K(0x3a, false); K(0x3a, true);   // put Caps Lock (Run Lock) back
            Measure("W, Caps Lock restored", () => K(0x11, false), () => K(0x11, true));
            return 0;
        }
        case "wasteland":
        {
            // wasteland [--portals]: offline, the wasteland walking grid: cells, walkable share, doors and outposts.
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var travel = new Travel(DefaultInstall, _ => throw new NotSupportedException(), new Hud(), logs, pulse, run);
            var map = travel.Terrain;
            Console.WriteLine($"{map.Cells.Count} cells; grid {(map.FromCache ? "read from the cache" : "built")} in {map.LoadTime.TotalSeconds:F1}s; " +
                $"{map.Portals.Count} doors in cells, {map.Landmarks.Count} outposts");
            foreach (int cell in map.Cells.Where(c => rest.Contains("--cells")))
                Console.WriteLine($"  {travel.SectorName(cell),-28} {100 * map.WalkableShare(cell),3:F0}% walkable");
            if (rest.Contains("--portals"))
                foreach (var p in map.Portals.OrderBy(p => p.Cell))
                    Console.WriteLine($"  {travel.SectorName(p.Cell),-26} {p.Name,-34} at {p.Position.X,6:F0},{p.Position.Z,6:F0} -> {travel.SectorName(p.To)} ({p.To}) Index={p.Index} arrival={p.Arrival}");
            foreach (var l in map.Landmarks)
                Console.WriteLine($"  {l.Kind,-8} {l.Name,-22} in {travel.SectorName(l.Cell),-24} at {l.Position.X:F0},{l.Position.Y:F0},{l.Position.Z:F0}");
            return 0;
        }
        case "wastelandplaces":
        {
            // JSON for Nav Walker / the Nav-Ray list: the outposts out in the wasteland, each as a walk target
            // (zone = the cell's world id, target = "x,y,z" on the cell's navmesh by the outpost's gate).
            // Bakes each outpost cell once (cached in logs/terrain/). Sectors behind wasteland doors (Tech Haven,
            // the Military Base, Canyon, the dungeons) need no row here: Reach lists them, walked to by "arrive".
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            var travel = new Travel(DefaultInstall, _ => throw new NotSupportedException(), new Hud(), logs, pulse, run);
            var rows = WastelandPlaces(travel, logs, refresh: true).Select(w => new { zone = w.Zone, zoneName = travel.SectorName(w.Zone), name = w.Name, kind = w.Kind,
                target = w.Target, onNavmesh = w.OnNavmesh });
            Console.WriteLine(JsonSerializer.Serialize(rows));
            return 0;
        }
        case "wasteplan":
        {
            // wasteplan <toSector> [fromSector] [--at x,y,z] [--target x,y,z] [--nosim]: offline, plan a whole trip that may cross
            // the wasteland, leg by leg as a live trip would walk it, and check each wasteland leg on the cell's
            // navmesh (baked once per cell, then cached in logs/terrain/). No game needed.
            string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
            string? targetOption = Option("--target"), atOption = Option("--at");
            bool simulate = !rest.Remove("--nosim");
            Vector3? at = atOption?.Split(',').Select(v => float.Parse(v, System.Globalization.CultureInfo.InvariantCulture)).ToArray() is { Length: 3 } a3 ? new Vector3(a3[0], a3[1], a3[2]) : null;
            int toSector = int.Parse(rest[0]), fromSector = rest.Count > 1 ? int.Parse(rest[1]) : 1;
            var baked = new Dictionary<int, NavWorld>();
            NavWorld Nav(int id)
            {
                if (baked.TryGetValue(id, out var n)) return n;
                var clock = Stopwatch.StartNew();
                n = baked[id] = NavWorld.Bake(DefaultInstall, id);
                if (clock.Elapsed.TotalSeconds > 1) Console.WriteLine($"  (map of {n.World.Summary.Name} ready in {clock.Elapsed.TotalSeconds:F1}s)");
                return n;
            }
            var travel = new Travel(DefaultInstall, Nav, new Hud(), logs, pulse, run);
            var total = Stopwatch.StartNew();
            var chain = travel.SectorPath(fromSector, toSector);
            Console.WriteLine($"Plan {travel.SectorName(fromSector)} -> {travel.SectorName(toSector)} ({total.Elapsed.TotalSeconds:F1}s): " +
                (chain.Count == 0 ? "none" : string.Join(" -> ", chain.Select(travel.SectorName))));
            if (chain.Count == 0) return 1;
            var legs = travel.PlanTrip(fromSector, toSector, at, Nav, simulate);
            float units = 0;
            foreach (var leg in legs)
            {
                units += leg.Length;
                Console.WriteLine($"  {(leg.Ok ? "ok  " : "FAIL")} {travel.SectorName(leg.From),-26} -> {travel.SectorName(leg.To),-26} {leg.Method,-26} {leg.Length,7:F0} units  {leg.Note}");
            }
            bool arrived = legs.Count > 0 && legs[^1].To == toSector && legs.Where(l => l.Method is not ("replanned" or "backed out")).All(l => l.Ok);
            if (targetOption != null && arrived)
            {
                var f = targetOption.Split(',').Select(v => float.Parse(v, System.Globalization.CultureInfo.InvariantCulture)).ToArray();
                var nav = Nav(toSector);
                bool reach = nav.Snap(new Vector3(f[0], f[1], f[2]), out _, out var on, wide: true);
                Console.WriteLine($"  target {targetOption}: {(reach ? $"floor at {on.X:F0},{on.Y:F0},{on.Z:F0}" : "no floor near it")}");
            }
            Console.WriteLine($"{(arrived ? "Arrives" : "Does not arrive")}: {legs.Count} legs, {units:F0} units (about {units / 200 / 60:F0}-{units / 125 / 60:F0} min), planned in {total.Elapsed.TotalSeconds:F1}s");
            return arrived ? 0 : 1;
        }
        case "cellisland":
        {
            // cellisland <cell> x,y,z: offline, which 256-unit squares of a cell its navmesh reaches from a point.
            // Writes out/island-<cell>.txt: 128 rows (north first) of '#' reached, '+' floor not reached, '.' no floor.
            int cell = int.Parse(rest[0]);
            var f = rest[1].Split(',').Select(v => float.Parse(v, System.Globalization.CultureInfo.InvariantCulture)).ToArray();
            var nav = NavWorld.Bake(DefaultInstall, cell);
            var island = nav.Island(new Vector3(f[0], f[1], f[2]));
            var cellData = TerrainCell.Load(DefaultInstall, cell);
            var lines = new List<string>();
            int reached = 0, floor = 0;
            // Optional window "x0,z0,x1,z1,step" (default: the whole cell in 256-unit squares).
            var w = rest.Count > 2 ? rest[2].Split(',').Select(v => float.Parse(v, System.Globalization.CultureInfo.InvariantCulture)).ToArray()
                : new[] { -TerrainCell.Half, -TerrainCell.Half, TerrainCell.Half, TerrainCell.Half, TerrainMap.Step };
            int columns = (int)((w[2] - w[0]) / w[4]), rows = (int)((w[3] - w[1]) / w[4]);
            for (int j = rows - 1; j >= 0; j--)
            {
                var line = new System.Text.StringBuilder();
                for (int i = 0; i < columns; i++)
                {
                    float x = w[0] + w[4] * (i + 0.5f), z = w[1] + w[4] * (j + 0.5f);
                    var p = new Vector3(x, cellData.Height(x, z), z);
                    bool on = nav.OnIsland(p, island, w[4] / 2), any = nav.Snap(p, out _, out _, wide: true);
                    line.Append(on ? '#' : any ? '+' : '.');
                    if (on) reached++; if (any) floor++;
                }
                lines.Add(line.ToString());
            }
            string file = Path.Combine(outDir, $"island-{cell}.txt");
            File.WriteAllLines(file, lines);
            Console.WriteLine($"{island.Count} polygons reached; {reached} squares reached, {floor} with floor; wrote {file}");
            return 0;
        }
        case "terraincell":
        {
            // terraincell <id> [--bake]: offline, what a wasteland cell holds (placed models, exits), how
            // well the placement transform sits the models on the heightfield, and the bake time.
            int id = int.Parse(rest[0]);
            var clock = Stopwatch.StartNew();
            var cell = TerrainCell.Load(DefaultInstall, id);
            Console.WriteLine($"{cell.Code}: loaded in {clock.Elapsed.TotalSeconds:F1}s; {cell.Placements.Count} placed models, {cell.Props.Count} props; " +
                $"height {cell.Heights.Min():F0}..{cell.Heights.Max():F0}");
            var travel = new Travel(DefaultInstall, _ => throw new NotSupportedException(), new Hud(), Path.Combine(root, "logs"), pulse, run);
            foreach (var p in cell.Placements)
            {
                string fit = "";
                if (p.Mesh != null && p.Mesh.Vertices.Length > 0)
                {
                    // How far the model's lowest vertices sit from the ground, for the transform as read and three variants.
                    // Spread of (vertex height - ground) over the model's lowest fifth: small when it sits on terrain shaped for it.
                    float Gap(Func<Vector3, Vector3> f)
                    {
                        var low = p.Mesh.Vertices.Select(f).OrderBy(v => v.Y).Take(Math.Max(4, p.Mesh.Vertices.Length / 5)).Select(v => v.Y - cell.Height(v.X, v.Z)).OrderBy(x => x).ToList();
                        float median = low[low.Count / 2];
                        return low.Average(x => MathF.Abs(x - median));
                    }
                    var origin = p.Position;
                    Vector3 Unturn(Vector3 v) => TerrainCell.Place(TerrainCell.Place(v - origin, Vector3.Zero, -p.Yaw), Vector3.Zero, -p.Yaw) + origin;
                    fit = $" ground gap {Gap(v => v):F0} (with offset {Gap(v => v + p.Offset):F0}, yaw reversed {(p.Yaw == 0 ? "-" : Gap(Unturn).ToString("F0"))})";
                }
                if (p.Exits.Count == 0 && !rest.Contains("--all")) continue;
                Console.WriteLine($"  {p.Model} at {p.Position.X:F0},{p.Position.Y:F0},{p.Position.Z:F0} (offset {p.Offset.X:F0},{p.Offset.Y:F0},{p.Offset.Z:F0}) yaw {p.Yaw:F0}{fit}");
                foreach (var e in p.Exits)
                    Console.WriteLine($"    {e.Name} at {e.Position.X:F0},{e.Position.Y:F0},{e.Position.Z:F0} (ground {cell.Height(e.Position.X, e.Position.Z):F0}) -> " +
                        $"{(int.TryParse(e.Properties.GetValueOrDefault("NextLevel"), out int to) ? travel.SectorName(to) : "?")} Index={e.Properties.GetValueOrDefault("Index")} NextLevelStartIndex={e.Properties.GetValueOrDefault("NextLevelStartIndex")}");
            }
            if (rest.Contains("--bake"))
            {
                clock.Restart();
                var nav = NavWorld.Bake(DefaultInstall, id);
                Console.WriteLine($"navmesh: {nav.Polygons().Count} polygons in {clock.Elapsed.TotalSeconds:F1}s (bake or cache {nav.BakeTime.TotalSeconds:F1}s)");
            }
            return 0;
        }
        case "survey":
            Survey.Run(DefaultInstall, 1, "WorldChange5", Path.Combine(outDir, "survey"), Math.Max(1, Environment.ProcessorCount - 2));
            return 0;
        case "hudtest":
        {
            using var hud = new Hud();
            hud.Post(Hud.Cyan, "NAVMESH  overlay test", "If you can read this, the route panel works.");
            Console.WriteLine(hud.Connected ? "Overlay reached." : $"Overlay not reached: {hud.LastError}");
            return hud.Connected ? 0 : 1;
        }
        default: Console.WriteLine("Commands: report | simulate | plan <target> | steer <target>"); return 2;
    }
}
catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException or OperationCanceledException)
{
    Console.WriteLine($"Stopped: {error.Message}");
    return 1;
}

int WorldArg(List<string> list) => list.Count > 0 && int.TryParse(list[0], out int w) ? w : 1;

// The wasteland's outposts and landmarks as walk targets: zone = the cell's world id, target =
// "x,y,z" on the cell's navmesh by the outpost's gate. Working that out bakes each outpost cell
// (cached in logs/terrain), so the answer is kept in logs/wasteland-places.json.
List<(int Zone, string Name, string Kind, string Target, bool OnNavmesh)> WastelandPlaces(Travel travel, string logs, bool refresh)
{
    string cache = Path.Combine(logs, "wasteland-places.json");
    if (!refresh && File.Exists(cache))
        return JsonSerializer.Deserialize<List<WastelandRow>>(File.ReadAllText(cache))!.Select(r => (r.Zone, r.Name, r.Kind, r.Target, r.OnNavmesh)).ToList();
    var map = travel.Terrain;
    var list = new List<(int, string, string, string, bool)>();
    foreach (var l in map.Landmarks)
    {
        var nav = NavWorld.Bake(DefaultInstall, l.Cell);
        int main = map.MainComponent(l.Cell);
        var start = map.Local(map.Nearest(l.Cell, l.Position, main, rings: TerrainMap.N));
        var near = nav.RouteToward(start, l.Position);
        bool ok = near.Count > 1 && new Vector2(near[^1].X - l.Position.X, near[^1].Z - l.Position.Z).Length() < 600;
        var at = ok ? near[^1] : l.Position;
        list.Add((l.Cell, l.Name, l.Kind, string.Create(System.Globalization.CultureInfo.InvariantCulture, $"{at.X:F0},{at.Y:F0},{at.Z:F0}"), ok));
    }
    File.WriteAllText(cache, JsonSerializer.Serialize(list.Select(r => new WastelandRow(r.Item1, r.Item2, r.Item3, r.Item4, r.Item5))));
    return list;
}

NavWorld BakeLogged(string install, int worldId)
{
    var nav = NavWorld.Bake(install, worldId);
    Console.WriteLine($"{nav.World.Summary.Name} (world {worldId}): {nav.World.StaticGeometry.Vertices.Length} verts, " +
        $"{nav.World.StaticGeometry.Triangles.Length / 3} tris; baked in {nav.BakeTime.TotalSeconds:F1}s");
    return nav;
}

List<(string Name, Vector3 P)> GroundOnMesh(NavWorld nav) => nav.World.Summary.Features
    .Where(f => f.Kind == "GroundPathPoint" && nav.Snap(f.Position, out _, out _)).Select(f => (f.Name, f.Position)).ToList();

int Report(List<string> list)
{
    int worldId = WorldArg(list);
    var logs = list.Skip(1).ToList();
    if (logs.Count == 0)
    {
        string dir = Path.Combine(root, @"..\NeocronSharp\logs");
        if (Directory.Exists(dir))
            logs = Directory.GetFiles(dir, "movement-*.jsonl").Concat(Directory.GetFiles(dir, "navigation-*.jsonl")).ToList();
    }
    var nav = BakeLogged(DefaultInstall, worldId);
    var ground = GroundOnMesh(nav);
    Console.WriteLine($"Ground points on mesh: {ground.Count}/{nav.World.Summary.GroundPoints}");

    // Route between the two authored ground points farthest apart that connect.
    List<Vector3> route = new();
    foreach (var (a, b) in from a in ground from b in ground where string.CompareOrdinal(a.Name, b.Name) < 0
                           orderby Vector3.Distance(a.P, b.P) descending select (a, b))
    {
        route = nav.Route(a.P, b.P, out bool complete);
        if (route.Count > 1 && complete)
        {
            Console.WriteLine($"Route {a.Name} -> {b.Name}: straight-line {Vector3.Distance(a.P, b.P):F0}, walked {new RouteFollower(route).Total:F0}, {route.Count} corners");
            break;
        }
        route = new();
    }
    if (route.Count < 2) Console.WriteLine("No complete route between any two ground points.");

    // Every recorded telemetry sample in this world should stand on the mesh.
    var trail = new List<Vector3>();
    foreach (var log in logs)
        foreach (var line in File.ReadLines(log))
        {
            using var doc = JsonDocument.Parse(line);
            if (!doc.RootElement.TryGetProperty("position", out var p) || p.ValueKind != JsonValueKind.Object) continue;
            trail.Add(new(p.GetProperty("X").GetSingle(), p.GetProperty("Y").GetSingle(), p.GetProperty("Z").GetSingle()));
        }
    int inside = 0, near = 0;
    foreach (var p in trail)
    {
        if (!nav.Snap(p, out _, out var on)) continue;
        float flat = PointNavigation.Distance(p, on);
        if (flat < 0.5f && MathF.Abs(p.Y - on.Y) < 24) inside++; else if (flat < nav.Settings.agentRadius * 2) near++;
    }
    if (trail.Count > 0)
        Console.WriteLine($"Telemetry samples: {trail.Count} from {logs.Count} logs; on mesh {inside} ({100.0 * inside / trail.Count:F1}%), " +
            $"within {nav.Settings.agentRadius * 2} {near}, off {trail.Count - inside - near} (logs are not tagged with a world)");
    string svg = Path.Combine(outDir, $"world-{worldId}.svg");
    File.WriteAllText(svg, Render.Svg(nav, route, ground.Select(g => g.P), trail));
    Console.WriteLine($"Wrote {svg}");
    return 0;
}

int Simulate(List<string> list)
{
    int worldId = WorldArg(list);
    var nav = BakeLogged(DefaultInstall, worldId);
    var ground = GroundOnMesh(nav);
    if (ground.Count < 2) { Console.WriteLine("Fewer than two ground points on the mesh."); return 1; }
    // Measured live on 29 Oct: ~190 u/s walking; ~2.4 mrad per pixel while moving,
    // ~30% more than the calibration step reports. Running speed is a guess.
    const float Gain = 0.0024f, Bias = 1.3f;
    foreach (var (name, speed) in new[] { ("walk", 190f), ("run", 320f) })
    {
        var random = new Random(1); // same pairs for both speeds
        var outcomes = new List<Simulator.Outcome>();
        for (int i = 0; i < pairs; i++)
        {
            var a = ground[random.Next(ground.Count)]; var b = ground[random.Next(ground.Count)];
            if (a.Name == b.Name) { i--; continue; }
            outcomes.Add(Simulator.Run(nav, a.P, b.P, speed, Gain, Bias, pulse * 2, random));
        }
        var routed = outcomes.Where(o => o.Reason != "no route").ToList();
        var ok = routed.Where(o => o.Arrived).ToList();
        float minutes = ok.Sum(o => o.Seconds) / 60;
        Console.WriteLine($"{name} {speed:F0} u/s: arrived {ok.Count}/{routed.Count}; max off-route {routed.DefaultIfEmpty().Max(o => o?.MaxOffRoute ?? 0):F0}; " +
            $"replans {routed.Sum(o => o.Replans)}; time/ideal {(ok.Count > 0 ? ok.Average(o => o.Seconds / (o.RouteLength / speed)) : 0):F2}x; " +
            $"sway: {(minutes > 0 ? ok.Sum(o => o.Reversals) / minutes : 0):F0} reversals/min, mean aim error {(ok.Count > 0 ? ok.Average(o => o.MeanAngleDegrees) : 0):F1} deg");
        foreach (var group in routed.Where(o => !o.Arrived).GroupBy(o => o.Reason)) Console.WriteLine($"    failed: {group.Key} x {group.Count()}");
    }
    return 0;
}

int Live(List<string> list, bool steer)
{
    if (list.Count == 0) throw new InvalidOperationException("Give a target: \"x,y,z\", ground:Name or exit:Name.");
    string executable;
    var running = Process.GetProcessesByName("neocronclient");
    try { executable = running.Length == 1 ? running[0].MainModule?.FileName ?? "" : throw new InvalidOperationException("Open exactly one Neocron client and log in first."); }
    finally { foreach (var p in running) p.Dispose(); }
    using var reader = new PlayerReader(executable);
    var sample = reader.ReadSample();
    int sector = reader.ReadSectorId(sample.World) ?? throw new InvalidOperationException("The current sector is unavailable. Finish zoning.");
    Console.WriteLine($"Player at {sample.Position}, sector {sector}");
    var nav = BakeLogged(Path.GetDirectoryName(executable)!, sector);
    var (target, label, wide) = nav.Target(list[0]);
    var route = nav.Route(sample.Position, target, out bool complete, wide);
    if (route.Count < 2) throw new InvalidOperationException($"No route to {label}: the player or target is off the navmesh.");
    float length = new RouteFollower(route).Total;
    Console.WriteLine($"Route to {label}: {route.Count} corners, {length:F0} units{(complete ? "" : " (INCOMPLETE: target not reachable on the mesh)")}");
    foreach (var c in route) Console.WriteLine($"  {c.X,8:F0} {c.Y,6:F0} {c.Z,8:F0}");
    string svg = Path.Combine(outDir, $"plan-{sector}.svg");
    File.WriteAllText(svg, Render.Svg(nav, route, GroundOnMesh(nav).Select(g => g.P), Array.Empty<Vector3>(), sample.Position));
    Console.WriteLine($"Wrote {svg}");
    using var hud = new Hud();
    hud.Post(complete ? Hud.Cyan : Hud.Red, $"NAVMESH  route to {label}",
        $"{route.Count} corners, {length:F0} units{(complete ? "" : "  (target not reachable on the mesh)")}",
        steer ? "Walk requested: click into Neocron within 5 s.  F8 stops." : "Planned only, not walking.");
    Console.WriteLine(hud.Connected ? "Route panel shown in-game." : $"In-game route panel not shown ({hud.LastError ?? "overlay not loaded"}).");
    if (!steer) return 0;
    if (!complete) throw new InvalidOperationException("Refusing to steer an incomplete route.");
    string logs = Path.Combine(root, "logs"); Directory.CreateDirectory(logs);
    string logPath = Path.Combine(logs, $"steer-{DateTime.UtcNow:yyyyMMdd-HHmmss}.jsonl");
    Console.WriteLine($"Logging to {logPath}");
    new LiveSteer(reader, nav, sector, target, wide, label, pulse, logPath, hud, run).Run();
    return 0;
}

record WastelandRow(int Zone, string Name, string Kind, string Target, bool OnNavmesh);
