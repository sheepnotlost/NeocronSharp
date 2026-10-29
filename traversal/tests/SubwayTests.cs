using System.Numerics;
using NavmeshPrototype;
using NeocronSharp.Core;

/// <summary>
/// Offline tests for the subway: its four station halls and the track between them (from world 1000's
/// navmesh), plans that ride the train out to the Outzone, and the ride's decisions on made-up readings.
/// </summary>
internal static class SubwayTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    public static void Run(Action<string, Action> test, string install)
    {
        test("Subway ride: waits, boards, rides past other stops, steps off at its own", () =>
        {
            var board = new Vector3(0, -600, 0);
            // Platform 0 round the origin, platform 1 round x = 5000, platform 2 round x = 10000; the track 220 to the side (z = 220).
            int PlatformAt(Vector3 p) => MathF.Abs(p.Z) < 100 ? (int)MathF.Round(p.X / 5000) is var i && MathF.Abs(p.X - i * 5000) < 400 ? i : -1 : -1;
            bool Beside(Vector3 p) => MathF.Abs(p.X - 10000) < 400 && MathF.Abs(p.Z - 220) < 300;
            var logic = new SubwayRideLogic(board, 2, "PLAZA", "OUTZONE", PlatformAt, Beside);
            double t = 0;
            SubwayRideLogic.Act At(Vector3? p) { var a = logic.Step(t, p); t += 0.2; return a; }
            int uses = 0;
            for (int i = 0; i < 50; i++) if (At(board) == SubwayRideLogic.Act.Use) uses++;
            Check(logic.Phase == "waiting" && uses == 4, $"uses every 3 s while waiting (phase {logic.Phase}, {uses} uses in 10 s)");
            // Aboard: seated 220 units out, over the track.
            At(new Vector3(0, -595, 220));
            Check(logic.Phase == "riding", $"aboard once the position moves to the train (phase {logic.Phase})");
            // Through platform 1: the train stands there 10 s; not ours, no use.
            for (float x = 0; x < 5000; x += 100) Check(At(new Vector3(x, -595, 220)) == SubwayRideLogic.Act.Wait, "riding");
            for (int i = 0; i < 50; i++) Check(At(new Vector3(5000, -595, 220)) == SubwayRideLogic.Act.Wait, "no use at another stop");
            for (float x = 5000; x < 10000; x += 100) At(new Vector3(x, -595, 220));
            // At ours: still for 1.5 s, then use to step off.
            var acts = Enumerable.Range(0, 12).Select(_ => At(new Vector3(10000, -595, 220))).ToList();
            Check(acts.Contains(SubwayRideLogic.Act.Use) && logic.Phase == "leaving", $"uses the train to step off at the stop wanted (phase {logic.Phase})");
            // Put on the platform 220 to the side.
            SubwayRideLogic.Act last = SubwayRideLogic.Act.Wait;
            for (int i = 0; i < 10 && last != SubwayRideLogic.Act.Done; i++) last = At(new Vector3(10000, -600, 0));
            Check(last == SubwayRideLogic.Act.Done && logic.Landed == 2, $"done on the Outzone platform (landed {logic.Landed})");
        });

        test("Subway ride: clear failures (no train, position unreadable aboard) and being put off elsewhere", () =>
        {
            var board = new Vector3(0, -600, 0);
            int PlatformAt(Vector3 p) => MathF.Abs(p.Z) < 100 ? (int)MathF.Round(p.X / 5000) is var i && MathF.Abs(p.X - i * 5000) < 400 ? i : -1 : -1;
            var logic = new SubwayRideLogic(board, 2, "PLAZA", "OUTZONE", PlatformAt, _ => false);
            var act = SubwayRideLogic.Act.Wait;
            for (double t = 0; t < SubwayRideLogic.BoardTimeout + 2 && act != SubwayRideLogic.Act.Fail; t += 0.2) act = logic.Step(t, board);
            Check(act == SubwayRideLogic.Act.Fail && logic.Message!.Contains("No train"), $"no train: {logic.Message}");

            logic = new SubwayRideLogic(board, 2, "PLAZA", "OUTZONE", PlatformAt, _ => false);
            act = logic.Step(0, board);   // the first use
            for (double t = 0.2; t < SubwayRideLogic.RideTimeout + 10 && act != SubwayRideLogic.Act.Fail; t += 0.2) act = logic.Step(t, null);
            Check(act == SubwayRideLogic.Act.Fail && logic.Message!.Contains("Could not read the position"), $"unreadable aboard: {logic.Message}");

            logic = new SubwayRideLogic(board, 2, "PLAZA", "OUTZONE", PlatformAt, _ => false);
            logic.Step(0, board); logic.Step(0.2, new Vector3(0, -595, 220));
            act = SubwayRideLogic.Act.Wait;
            for (double t = 0.4; t < 20 && act == SubwayRideLogic.Act.Wait; t += 0.2) act = logic.Step(t, new Vector3(5000, -600, 0));
            Check(act == SubwayRideLogic.Act.Done && logic.Landed == 1, $"put off at platform 1: reported, to plan again from there (landed {logic.Landed})");
        });

        if (!Directory.Exists(install)) return;
        NavWorld? subwayNav = null;
        NavWorld Bake(int id) => id == Travel.Subway ? subwayNav ??= NavWorld.Bake(install, id) : throw new NotSupportedException("only the subway is baked here");
        Travel NewTravel()
        {
            string logs = Path.Combine(Path.GetTempPath(), "traversal-subwaytests-" + Guid.NewGuid().ToString("N")[..8]);
            Directory.CreateDirectory(logs);
            string cached = Path.Combine(Travel.Home, "logs", "door-graph.txt");
            if (File.Exists(cached)) File.Copy(cached, Path.Combine(logs, "door-graph.txt"));
            return new Travel(install, Bake, new Hud(), logs, 12, true);
        }

        test("Subway halls: Plaza, Via Rosso, Pepper Park and Outzone, joined only by track", () =>
        {
            var travel = NewTravel();
            var data = travel.ComputeSubway(Bake(Travel.Subway));
            Check(data.Platforms.Count == 4, $"four halls (got {data.Platforms.Count}: {string.Join(", ", data.Platforms.Select(p => p.Name))})");
            int Hall(int sector) => data.Stops.First(s => s.To == sector).Platform;
            Check(Hall(1) == Hall(2) && Hall(5) == Hall(6) && Hall(24) == Hall(9), "Plaza 1 and 2, Pepper Park 1 and 2, Outzone 1 and Outzone Station share a hall");
            Check(new[] { Hall(1), Hall(5), Hall(401), Hall(24) }.Distinct().Count() == 4, "the four halls are apart");
            var nav = Bake(Travel.Subway);
            foreach (var p in data.Platforms)
            {
                Check(p.Edge.Count > 0 && travel.PlatformAt(nav, p.Board) == p.Index, $"{p.Name}: a platform edge, and the boarding spot is on the hall's floor");
                Check(nav.Route(data.Stops.First(s => s.Platform == p.Index).Position, p.Board, out bool ok).Count > 1 && ok, $"{p.Name}: the platform is walked to from its doors");
                foreach (var q in data.Platforms.Where(q => q.Index != p.Index))
                {
                    Check(data.Track[p.Index][q.Index] > 3000, $"{p.Name} to {q.Name}: joined by track ({data.Track[p.Index][q.Index]:F0})");
                    Check(nav.Route(p.Board, q.Board, out bool walk) is var r && !(walk && r.Count > 1), $"{p.Name} to {q.Name}: no floor to walk between the halls");
                }
            }
        });

        test("Subway plans: out to the Outzone by train; city trips keep to the streets", () =>
        {
            var travel = NewTravel();
            Check(travel.Subways() is { Platforms.Count: 4 }, "subway halls known");
            // Streets to a station (Plaza 1's own, or Pepper Park 1's: the shorter ride), then the train.
            bool ByTrain(List<int> path, params int[] after)
            {
                int i = path.IndexOf(Travel.Subway);
                return path[0] == 1 && i >= 1 && i <= 3 && path.Take(i).All(travel.IsStreet) && path.Skip(i).Take(after.Length + 1).SequenceEqual(after.Prepend(Travel.Subway));
            }
            var toStation = travel.SectorPath(1, 24);
            Check(ByTrain(toStation, 24) && toStation.Count <= 5, $"Plaza 1 to Outzone Station by subway, not 10 sewers and a club ({string.Join(" > ", toStation.Select(travel.SectorName))})");
            var plan = travel.WastelandPlan(1, 500, null);
            Check(plan != null && ByTrain(plan.Sectors, 24, 2008),
                $"Plaza 1 to Tech Haven: subway, Outzone Station, A 08 ({(plan == null ? "none" : string.Join(" > ", plan.Sectors.Select(travel.SectorName)))})");
            Check(plan!.Sectors[^1] == 500 && plan.Sectors.Contains(2087), "and on to Tech Haven through E 07");
            Check(ByTrain(travel.SectorPath(1, 500), 24), "the trip itself takes the subway");
            var city = travel.SectorPath(1, 7);
            Check(city.Count >= 4 && !city.Contains(Travel.Subway), $"Plaza 1 to Pepper Park 3 stays on the streets ({string.Join(",", city)})");
            Check(travel.Reach(1).ContainsKey(24), "Outzone Station is now reachable from Plaza 1");
            // Standing in the subway's Plaza hall, bound for Outzone Station: the door is in the Outzone hall, so ride first.
            var nav = Bake(Travel.Subway);
            var data = travel.Subways()!;
            var plaza = data.Stops.First(s => s.To == 1);
            var path = travel.SubwayPath(plaza.Position, 24, nav, out int hall, out var stop);
            Check(hall == plaza.Platform && stop != null && stop.To == 24 && stop.Platform != hall && path.SequenceEqual(new[] { Travel.Subway, 24 }),
                $"from the Plaza hall: ride to the Outzone hall for Outzone Station (hall {hall}, stop {stop?.Exit} in hall {stop?.Platform})");
            // Already in the Plaza hall, bound for Plaza 2: walk, no ride.
            travel.SubwayPath(plaza.Position, 2, nav, out hall, out stop);
            Check(stop != null && stop.Platform == hall, "Plaza 2's door is in the same hall: no ride");
        });

        test("Subway timetable: the trains' loop from the spawn file, and rides timed by it", () =>
        {
            var travel = NewTravel();
            var table = travel.Timetable();
            Check(table != null && table.Stops.Count == 8, $"eight timed stops (got {table?.Stops.Count})");
            Check(table!.Period is > 300 and < 360 && table.Length is > 120_000 and < 145_000, $"a loop of about 133,000 units in about 329 s (got {table.Length:F0} in {table.Period:F0} s)");
            Check(table.Stops.All(s => s.Start - s.Stop is > 5 and < 20), "each stop lasts 5-20 s");
            var data = travel.Subways()!;
            int Hall(int sector) => data.Stops.First(s => s.To == sector).Platform;
            float plazaOut = travel.RideSeconds(Hall(1), Hall(24))!.Value, parkOut = travel.RideSeconds(Hall(5), Hall(24))!.Value;
            Check(plazaOut is > 120 and < 155, $"Plaza to Outzone: about 137 s aboard, stopping at Via Rosso and Pepper Park (got {plazaOut:F0})");
            Check(parkOut is > 40 and < 60, $"Pepper Park to Outzone: about 51 s aboard (got {parkOut:F0})");
            // Between stops the train runs at 2-3 times walking pace (Plaza to Outzone: 58,900 units of track).
            Check(data.Track[Hall(1)][Hall(24)] / plazaOut > 2 * Travel.WalkPace, "faster than walking");
        });

        NavWorld? plaza1 = null, park1 = null;
        NavWorld Street(int id) => id switch { 1 => plaza1 ??= NavWorld.Bake(install, 1), 5 => park1 ??= NavWorld.Bake(install, 5), _ => Bake(id) };

        test("Subway entrances: down the station stairs past the door record, no right-click", () =>
        {
            var travel = NewTravel();
            foreach (var (sector, exitName, room) in new[] { (5, "WorldChange9", -958f), (1, "WorldChange1", -382f) })
            {
                var nav = Street(sector);
                var exit = travel.Exits(sector).First(e => e.Exit.Name == exitName && e.To == Travel.Subway).Exit;
                var verts = nav.World.StaticGeometry.Vertices;
                var centre = new Vector3((verts.Min(v => v.X) + verts.Max(v => v.X)) / 2, 0, (verts.Min(v => v.Z) + verts.Max(v => v.Z)) / 2);
                var line = travel.LineFor(sector, exit, null, Travel.Subway, centre, nav);
                string name = travel.SectorName(sector);
                Check(line.Push is { } && MathF.Abs(line.Walk.Y - room) < 20, $"{name}: the walk ends on the station room's floor at {room:F0}, 128 below the stairs' landing (ends {line.Walk:F0})");
                var route = nav.Route(exit.Position, line.Walk, out bool ok);
                Check(ok && new RouteFollower(route).Total is > 600 and < 1300 && route.All(p => p.Y < exit.Position.Y + 40),
                    $"{name}: reached from the record by going only down, about 1,000 units");
                Check(PointNavigation.Distance(line.Push!.Value, line.Walk) > 200, $"{name}: pressing on past the room's far end");
                Check(!Travel.DoorAt(nav, exit.Position, line.Walk), $"{name}: no door object at the entrance, so no right-click");
            }
            // Pepper Park 1: not the street corridor west of the record, where the live push pressed and did not zone.
            var park = travel.LineFor(5, travel.Exits(5).First(e => e.Exit.Name == "WorldChange9").Exit, null, Travel.Subway, null, Street(5));
            Check(PointNavigation.Distance(park.Walk, new Vector3(1588, -830, 1157)) > 600, $"Pepper Park 1: not the corridor tip at 1588,1157 (walk ends {park.Walk:F0})");
        });

        test("Subway choice: Plaza 1 to Tech Haven boards at Plaza 1's own entrance when that is quicker", () =>
        {
            var travel = NewTravel();
            // Where the live trip of 29 Oct started, and on Plaza 1's subway door: Plaza 1's own entrance.
            foreach (var at in new[] { new Vector3(-869, -256, 790), new Vector3(64, -240, 2112) })
            {
                var plan = travel.WastelandPlan(1, 500, at);
                Check(plan != null && plan.Sectors.Take(3).SequenceEqual(new[] { 1, Travel.Subway, 24 }), $"from {at:F0}: Plaza 1, subway, Outzone Station ({(plan == null ? "none" : string.Join(" > ", plan.Sectors.Take(4).Select(travel.SectorName)))})");
                Check(travel.SectorPath(1, 500, 12, at).Take(2).SequenceEqual(new[] { 1, Travel.Subway }), $"from {at:F0}: the trip takes it too");
            }
            // Standing at the line into Plaza 3, Pepper Park's train (51 s aboard, not 137) is quicker.
            var far = travel.WastelandPlan(1, 500, new Vector3(-1024, -256, 3120));
            Check(far != null && far.Sectors.Take(4).SequenceEqual(new[] { 1, 101, 5, Travel.Subway }), $"from Plaza 1's line into Plaza 3: by Pepper Park 1 ({(far == null ? "none" : string.Join(" > ", far.Sectors.Take(4).Select(travel.SectorName)))})");
        });
    }
}
