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
        // Made-up geometry: the boarding spot at the origin, its track 220 out (z = 220); platforms 0, 1, 2 round
        // x = 0, 5000, 10000 (|z| < 100); the car's middle stands 240 out from the spot, as live at Plaza.
        var board = new Vector3(0, -600, 0);
        var track = new Vector3(0, -646, 220);
        int PlatformAt(Vector3 p) => MathF.Abs(p.Z) < 100 ? (int)MathF.Round(p.X / 5000) is var i && MathF.Abs(p.X - i * 5000) < 400 ? i : -1 : -1;
        bool Beside(Vector3 p) => MathF.Abs(p.X - 10000) < 400 && MathF.Abs(p.Z - 220) < 300;
        SubwayRideLogic NewRide(Func<Vector3, bool>? beside = null) => new(board, track, 2, "PLAZA", "OUTZONE", PlatformAt, beside ?? Beside);
        (int, Vector3)[] Trains(params (int Key, Vector3 P)[] t) => t;

        test("Subway boarding: waits for a train standing on its track, walks up within reach, right-clicks", () =>
        {
            var logic = NewRide();
            double t = 0;
            var me = board;
            // The far side's train stands 450 the other way: never ours.
            var far = (8, new Vector3(0, -600, -450));
            SubwayRideLogic.Act At(Vector3? p, params (int, Vector3)[] trains) { var a = logic.Step(t, p, trains); t += 0.1; return a; }
            // Ours pulls in along the track (z = 240), 50 units a tick, and stops 30 along from the spot.
            for (float x = -3000; x < 30; x += 50) Check(At(me, (7, new Vector3(x, -600, 240)), far) == SubwayRideLogic.Act.Wait, "waits while the train is moving");
            var car = new Vector3(30, -600, 240);
            var acts = Enumerable.Range(0, 12).Select(_ => At(me, (7, car), far)).ToList();
            Check(acts[^1] == SubwayRideLogic.Act.Approach && logic.Train == 7 && logic.Goal == car && !acts.Contains(SubwayRideLogic.Act.Use),
                $"after it stands 1 s: walks up to it, not the far side's train (phase {logic.Phase}, train {logic.Train})");
            // 241 from the car's middle is beyond reach: walk on, 30 a tick, until within 190.
            var act = SubwayRideLogic.Act.Approach;
            int steps = 0;
            while (act == SubwayRideLogic.Act.Approach && steps++ < 40) { me += new Vector3(0, 0, 30); act = At(me, (7, car), far); }
            float d = PointNavigation.Distance(me, car);
            Check(act == SubwayRideLogic.Act.Use && d <= SubwayRideLogic.Reach && d > SubwayRideLogic.Reach - 31 && logic.UseDistance == d,
                $"right-clicks once within reach ({d:F0} units from its middle, act {act})");
            // Not aboard ("You cannot reach that!"): after 2.5 s it walks on and clicks again.
            acts = Enumerable.Range(0, 24).Select(_ => At(me, (7, car), far)).ToList();
            Check(!acts.Contains(SubwayRideLogic.Act.Use) && acts[^1] == SubwayRideLogic.Act.Wait, "waits 2.5 s for the click to take");
            acts = Enumerable.Range(0, 12).Select(_ => At(me, (7, car), far)).ToList();
            int walked = acts.IndexOf(SubwayRideLogic.Act.Approach), clicked = acts.IndexOf(SubwayRideLogic.Act.Use);
            Check(walked >= 0 && clicked > walked && logic.Uses == 2, $"then walks on and clicks again ({logic.Uses} uses)");
            // Seated: the position joins the car's middle.
            At(car with { Y = -595 }, (7, car), far);
            Check(logic.Phase == "riding" && logic.Train == 7, $"aboard train 7 (phase {logic.Phase})");

            // A car standing farther out (320): blocked at the edge, 260 from its middle, it clicks from there.
            logic = NewRide(); t = 0; me = board with { Z = 60 };
            var wide = new Vector3(0, -600, 320);
            acts = Enumerable.Range(0, 30).Select(_ => At(me, (5, wide))).ToList();
            int first = acts.IndexOf(SubwayRideLogic.Act.Approach), use = acts.IndexOf(SubwayRideLogic.Act.Use);
            Check(first >= 0 && use - first is >= 6 and <= 9 && MathF.Abs(logic.UseDistance - 260) < 1, $"blocked: clicks after 0.6 s of no progress ({use - first} ticks, from {logic.UseDistance:F0})");
        });

        test("Subway ride: rides past other stops on the train's position, Space at its own, done on the platform", () =>
        {
            var logic = NewRide();
            double t = 0;
            SubwayRideLogic.Act At(Vector3? p, Vector3 car) { var a = logic.Step(t, p, Trains((7, car), (9, new Vector3(-8000, -600, 900)))); t += 0.2; return a; }
            var spot = new Vector3(30, -600, 240);
            for (int i = 0; i < 8; i++) At(board, spot);
            for (int i = 0; i < 20 && logic.Phase != "using"; i++) At(board with { Z = 60 }, spot);
            At(null, spot); At(null, spot); At(null, spot); At(null, spot); At(null, spot); At(null, spot);
            Check(logic.Phase == "riding", $"aboard once the position stops reading after the click (phase {logic.Phase})");
            // Seated, the position does not read: the train's tells where we are. Platform 1's stop: not ours.
            for (float x = 0; x < 5000; x += 100) Check(At(null, new Vector3(x, -600, 240)) == SubwayRideLogic.Act.Wait, "riding");
            for (int i = 0; i < 50; i++) Check(At(null, new Vector3(5000, -600, 240)) == SubwayRideLogic.Act.Wait, "no Space at another stop");
            for (float x = 5000; x < 10000; x += 100) At(null, new Vector3(x, -600, 240));
            var stop = new Vector3(10000, -600, 240);
            var acts = Enumerable.Range(0, 12).Select(_ => At(null, stop)).ToList();
            Check(acts.Count(a => a == SubwayRideLogic.Act.Jump) == 1 && !acts.Contains(SubwayRideLogic.Act.Use) && logic.Phase == "leaving",
                $"one Space (no right-click) once the train stands 1.5 s at the stop wanted (phase {logic.Phase})");
            // Put on the platform 220 to the side.
            var last = SubwayRideLogic.Act.Wait;
            for (int i = 0; i < 10 && last != SubwayRideLogic.Act.Done; i++) last = At(new Vector3(10000, -600, 20), stop);
            Check(last == SubwayRideLogic.Act.Done && logic.Landed == 2, $"done on the Outzone platform (landed {logic.Landed})");
        });

        test("Subway ride: Space once more if still aboard, then a clear failure", () =>
        {
            var logic = NewRide();
            double t = 0;
            SubwayRideLogic.Act At(Vector3? p, Vector3 car) { var a = logic.Step(t, p, Trains((7, car))); t += 0.2; return a; }
            var spot = new Vector3(30, -600, 240);
            for (int i = 0; i < 8; i++) At(board, spot);
            for (int i = 0; i < 20 && logic.Phase != "using"; i++) At(board with { Z = 60 }, spot);
            At(spot, spot);
            Check(logic.Phase == "riding", $"aboard (phase {logic.Phase})");
            var stop = new Vector3(10000, -600, 240);
            for (float x = 0; x < 10000; x += 200) At(new Vector3(x, -600, 240), new Vector3(x, -600, 240));
            var acts = Enumerable.Range(0, 60).Select(_ => At(stop, stop)).ToList();
            Check(acts.Count(a => a == SubwayRideLogic.Act.Jump) == 2 && acts[^1] == SubwayRideLogic.Act.Fail && logic.Message!.Contains("pressed Space 2 times"),
                $"two Spaces, then fails: {logic.Message}");
        });

        test("Subway boarding: clear failures (no train, out of reach, off the edge) and a train that pulls out", () =>
        {
            var logic = NewRide();
            var act = SubwayRideLogic.Act.Wait;
            // Only the far side's train stands; ours never comes.
            for (double t = 0; t < SubwayRideLogic.BoardTimeout + 2 && act != SubwayRideLogic.Act.Fail; t += 0.2)
                act = logic.Step(t, board, Trains((8, new Vector3(0, -600, -450))));
            Check(act == SubwayRideLogic.Act.Fail && logic.Message!.Contains("No train stopped") && logic.Uses == 0, $"no train: {logic.Message}");

            // Never aboard: four clicks on each of three trains, then a failure naming the distance.
            logic = NewRide();
            int key = 1;
            double t2 = 0;
            act = SubwayRideLogic.Act.Wait;
            for (int round = 0; round < 3 && act != SubwayRideLogic.Act.Fail; round++, key++)
            {
                var car = new Vector3(0, -600, 240);
                int before = logic.Uses;
                for (int i = 0; i < 200 && act != SubwayRideLogic.Act.Fail && !(logic.Phase == "waiting" && logic.Uses > before); i++, t2 += 0.1)
                    act = logic.Step(t2, board with { Z = 60 }, Trains((key, car)));
                // It pulls out; the next one comes 30 s later.
                for (int i = 0; i < 20 && act != SubwayRideLogic.Act.Fail; i++, t2 += 0.1) act = logic.Step(t2, board with { Z = 60 }, Trains((key, new Vector3(i * 100, -600, 240))));
            }
            Check(act == SubwayRideLogic.Act.Fail && logic.Message!.Contains("Could not board") && logic.Uses == 12 && logic.Message.Contains("180 units"),
                $"out of reach: {logic.Message} ({logic.Uses} uses)");

            // Walking up, the floor drops away: stop with a failure, not on down the track.
            logic = NewRide();
            act = SubwayRideLogic.Act.Wait;
            for (double t = 0; t < 1.5; t += 0.1) act = logic.Step(t, board, Trains((7, new Vector3(30, -600, 240))));
            Check(act == SubwayRideLogic.Act.Approach, "walking up to the train");
            act = logic.Step(1.6, board with { Z = 80, Y = -646 }, Trains((7, new Vector3(30, -600, 240))));
            Check(act == SubwayRideLogic.Act.Fail && logic.Message!.Contains("edge"), $"off the edge: {logic.Message}");

            // The train pulls out while we walk up: back to waiting, for the next.
            logic = NewRide();
            for (double t = 0; t < 1.5; t += 0.1) logic.Step(t, board, Trains((7, new Vector3(30, -600, 240))));
            logic.Step(1.6, board, Trains((7, new Vector3(200, -600, 240))));
            Check(logic.Phase == "waiting" && logic.Uses == 0, $"pulled out before the click: waiting again (phase {logic.Phase})");
        });

        test("Subway ride without train readings: uses straight ahead, rides on the position, put off elsewhere", () =>
        {
            var logic = NewRide();
            double t = 0;
            SubwayRideLogic.Act At(Vector3? p) { var a = logic.Step(t, p); t += 0.2; return a; }
            int uses = 0;
            for (int i = 0; i < 50; i++) if (At(board) == SubwayRideLogic.Act.Use) uses++;
            Check(logic.Phase == "waiting" && uses == 3, $"after 2 s, uses every 3 s while waiting (phase {logic.Phase}, {uses} uses in 10 s)");
            At(new Vector3(0, -595, 220));
            Check(logic.Phase == "riding", $"aboard once the position moves to the train (phase {logic.Phase})");
            for (float x = 0; x < 10000; x += 100) At(new Vector3(x, -595, 220));
            var acts = Enumerable.Range(0, 12).Select(_ => At(new Vector3(10000, -595, 220))).ToList();
            Check(acts.Contains(SubwayRideLogic.Act.Jump) && logic.Phase == "leaving", $"Space to leave at the stop wanted (phase {logic.Phase})");
            var last = SubwayRideLogic.Act.Wait;
            for (int i = 0; i < 10 && last != SubwayRideLogic.Act.Done; i++) last = At(new Vector3(10000, -600, 0));
            Check(last == SubwayRideLogic.Act.Done && logic.Landed == 2, $"done on the Outzone platform (landed {logic.Landed})");

            logic = NewRide(_ => false);
            var act = logic.Step(0, board);
            for (double s = 0.2; s < 2.2; s += 0.2) act = logic.Step(s, board);   // the first use, after 2 s
            for (double s = 2.2; s < SubwayRideLogic.RideTimeout + 20 && act != SubwayRideLogic.Act.Fail; s += 0.2) act = logic.Step(s, null);
            Check(act == SubwayRideLogic.Act.Fail && logic.Message!.Contains("Could not read the position"), $"unreadable aboard: {logic.Message}");

            logic = NewRide(_ => false);
            for (double s = 0; s < 2.2; s += 0.2) logic.Step(s, board);
            logic.Step(2.2, new Vector3(0, -595, 220));
            act = SubwayRideLogic.Act.Wait;
            for (double s = 2.4; s < 20 && act == SubwayRideLogic.Act.Wait; s += 0.2) act = logic.Step(s, new Vector3(5000, -600, 0));
            Check(act == SubwayRideLogic.Act.Done && logic.Landed == 1, $"put off at platform 1: reported, to plan again from there (landed {logic.Landed})");
        });

        test("Live reads: one-off failures retried for up to 1 s; zone changes and lasting faults still fail", () =>
        {
            double now = 0;
            int calls = 0;
            Func<double> clock = () => now;
            void Sleep(int ms) => now += ms / 1000.0;
            const string torn = "Player orientation is not a valid rotation transform.";
            int value = NeocronSharp.ReadTolerance.Retry(() => ++calls < 4 ? throw new InvalidOperationException(torn) : 42, clock, Sleep);
            Check(value == 42 && calls == 4 && now < 0.1, $"a torn orientation for three reads passes ({calls} reads, {now:F2} s)");
            calls = 0; now = 0;
            try { NeocronSharp.ReadTolerance.Retry<int>(() => { calls++; throw new InvalidOperationException(torn); }, clock, Sleep); Check(false, "should fail"); }
            catch (InvalidOperationException e) { Check(e.Message == torn && now is >= 0.95 and < 1.1, $"lasting: fails after about 1 s with the same message ({now:F2} s, {calls} reads)"); }
            foreach (string zone in new[] { "A verified in-world player is unavailable. Log in and finish zoning.", "Player physics identity changed. Finish zoning and restart the test.",
                         "Player coordinates are not initialized.", "The game closed." })
            {
                calls = 0; now = 0;
                try { NeocronSharp.ReadTolerance.Retry<int>(() => { calls++; throw new InvalidOperationException(zone); }, clock, Sleep); Check(false, "should fail"); }
                catch (InvalidOperationException e) { Check(e.Message == zone && calls == 1, $"not retried: {zone} ({calls} reads)"); }
            }
            foreach (string glitch in new[] { torn, "Player changed during telemetry sampling.", "Client telemetry became unreadable.", "Invalid player coordinates." })
                Check(NeocronSharp.ReadTolerance.IsTransient(new InvalidOperationException(glitch)), $"transient: {glitch}");
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
