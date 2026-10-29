using System.Numerics;
using System.Text.Json;
using NavmeshPrototype;
using NeocronSharp.Core;

const string Install = @"C:\Games\Neocron Client\Neocron Evolution 2.5";
int passed = 0, failed = 0;
void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
void Test(string name, Action action)
{
    try { action(); Console.WriteLine($"PASS {name}"); passed++; }
    catch (Exception e) { Console.WriteLine($"FAIL {name}: {e.Message}"); failed++; }
}
Vector3 P(float x, float z) => new(x, 0, z);

// The engine finds arrows.json and rotations.json next to itself; here, in the traversal folder.
Travel.Home = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, @"..\..\..\.."));
string Scratch()
{
    string dir = Path.Combine(Path.GetTempPath(), "traversal-tests-" + Guid.NewGuid().ToString("N")[..8]);
    Directory.CreateDirectory(dir);
    return dir;
}

// ---- pure logic ----

Test("Route progress only moves forward and names the next corner", () => {
    var follower = new RouteFollower(new[] { P(0, 0), P(100, 0), P(100, 100) });
    Check(follower.Total == 200, "length of an L route");
    follower.Update(P(50, 3));
    Check(Math.Abs(follower.Progress - 50) < 1, "projected onto the first leg");
    Check(follower.NextCorner == P(100, 0), "next corner is the bend");
    follower.Update(P(10, 0));
    Check(follower.Progress >= 49, "going back does not undo progress");
    follower.Update(P(100, 60));
    Check(Math.Abs(follower.Progress - 160) < 1 && follower.NextCorner == P(100, 100), "second leg");
});

Test("Aim falls back to the next corner when the view ahead is blocked", () => {
    var follower = new RouteFollower(new[] { P(0, 0), P(100, 0), P(100, 100) });
    var far = follower.Aim(P(0, 0), 150, (a, b) => true);
    Check(far == follower.PointAt(150), "clear line: aim the full look-ahead");
    var near = follower.Aim(P(0, 0), 150, (a, b) => false);
    Check(near == P(100, 0), "blocked line: aim at the next corner");
});

Test("Steering turns in place above the threshold and caps turns while moving", () => {
    var sharp = Steering.Decide(Vector3.Zero, P(1, 0), P(0, 100));
    Check(!sharp.Walk, "a 90-degree turn is made standing");
    var slight = Steering.Decide(Vector3.Zero, P(1, 0), P(100, 30));
    Check(slight.Walk && Math.Abs(slight.TurnRadians) <= Steering.MaxWalkingTurn + 1e-6f, "small turns while walking, capped");
    var ahead = Steering.Decide(Vector3.Zero, P(1, 0), P(100, 1));
    Check(ahead.Walk && ahead.TurnRadians == 0, "inside the deadband: no turn");
});

Test("Mouse gain is re-learned from what the camera really did", () => {
    var turns = new TurnController(0.002f);
    Check(turns.Pixels(0.02f, 24) == 10, "radians to pixels");
    Check(turns.Pixels(1f, 24) == 24, "clamped to the pulse budget");
    for (int i = 0; i < 30; i++) turns.Observe(10, 0.026f);   // camera really turns 2.6 mrad/px
    Check(Math.Abs(turns.Gain - 0.0026f) < 0.0001f, $"converges on the measured gain (got {turns.Gain})");
    float before = turns.Gain;
    turns.Observe(10, -0.026f);      // wrong way: a glitch, ignored
    turns.Observe(10, 0.5f);         // twenty times too far: ignored
    turns.Observe(2, 0.1f);          // too small a turn to judge
    Check(turns.Gain == before, "outliers do not move the gain");
});

// ---- the real world files (needs the local install) ----

if (!Directory.Exists(Install))
{
    Console.WriteLine($"SKIP world tests: no Neocron install at {Install}");
}
else
{
    var bakes = new Dictionary<int, NavWorld>();
    NavWorld Bake(int id) => bakes.TryGetValue(id, out var n) ? n : bakes[id] = NavWorld.Bake(Install, id);
    Travel NewTravel(string logs) => new(Install, Bake, new Hud(), logs, 12, true);

    Test("Only exits with a real arrival point count (Plaza 2 has 7)", () => {
        var travel = NewTravel(Scratch());
        var exits = travel.Exits(2).ToList();
        Check(exits.Count == 7, $"expected 7 real exits, got {exits.Count}");
        Check(exits.All(e => e.Exit.Properties["NextLevelStartIndex"] != "0"), "placeholders (start index 0) are excluded");
    });

    Test("Plans go street to street: no subway, no interiors on the way", () => {
        var travel = NewTravel(Scratch());
        var path = travel.SectorPath(1, 7);   // Plaza 1 to Pepper Park 3
        Check(path.Count >= 4 && path[0] == 1 && path[^1] == 7, $"a chain from Plaza 1 to Pepper Park 3 (got {string.Join(",", path)})");
        Check(path.Skip(1).SkipLast(1).All(s => s != Travel.Subway && travel.HasMap(s)), "every step between is a street with a map");
    });

    Test("Map rotations solved offline match the compass where it was read", () => {
        var travel = NewTravel(Scratch());
        foreach (var (sector, compass) in new[] { (1, 270), (2, 270), (101, 270), (5, 0), (6, 0) })
            Check(travel.RotationFor(sector, null) == compass, $"sector {sector}: expected {compass}");
        Check(travel.RotationFor(5, 90) == 90, "a live compass reading wins");
    });

    Test("A learned crossing is used first", () => {
        string logs = Scratch();
        File.WriteAllText(Path.Combine(logs, "traversal-crossings.txt"), "2\t101\t3269\t-383\t3995\t0.070\t-1.000\n");
        var travel = NewTravel(logs);
        travel.LoadLearning();
        var exit = travel.Exits(2).First(e => e.To == 101).Exit;
        var line = travel.LineFor(2, exit, null, 101);
        Check(line.Key == null && line.Push is { } push && push.Z < 3995 - 300, "push carries on along the learned heading");
        Check(Math.Abs(line.Walk.X - 3269) < 20 && Math.Abs(line.Walk.Z - (3995 + 120)) < 20, "approach from 120 units before the learned spot");
    });

    Test("A forgotten crossing falls back to the map", () => {
        string logs = Scratch();
        File.WriteAllText(Path.Combine(logs, "traversal-crossings.txt"), "2\t101\t3269\t-383\t3995\t0.070\t-1.000\n2\t101\tforget\n");
        var travel = NewTravel(logs);
        travel.LoadLearning();
        var line = travel.LineFor(2, travel.Exits(2).First(e => e.To == 101).Exit, null, 101);
        Check(line.Key != null, "an arrow is used once the crossing is forgotten");
    });

    Test("Arrows that do nothing, or lead elsewhere, are skipped", () => {
        string logs = Scratch();
        var exit = NewTravel(logs).Exits(2).First(e => e.To == 101).Exit;
        var first = NewTravel(logs).LineFor(2, exit, null, 101);
        Check(first.Key is not null, "an arrow is chosen");
        var key = first.Key!.Value;
        File.WriteAllText(Path.Combine(logs, "traversal-arrows.txt"), $"{key.Item1}\t{key.Item2}\t{key.Item3}\t0\n");
        var travel = NewTravel(logs); travel.LoadLearning();
        var second = travel.LineFor(2, exit, null, 101);
        Check(second.Key != key, "a dead arrow is not chosen again");
        File.WriteAllText(Path.Combine(logs, "traversal-arrows.txt"), $"{key.Item1}\t{key.Item2}\t{key.Item3}\t1\n");
        travel = NewTravel(logs); travel.LoadLearning();
        Check(travel.LineFor(2, exit, null, 101).Key != key, "an arrow known to lead to Plaza 1 is not used for Plaza 3");
        Check(travel.LineFor(2, travel.Exits(2).First(e => e.To == 1).Exit, null, 1).Key == key, "but it is the first choice for Plaza 1");
    });

    Test("A mapped obstacle is routed round", () => {
        var plain = Bake(1);
        var ground = plain.World.Summary.Features.Where(f => f.Kind == "GroundPathPoint" && plain.Snap(f.Position, out _, out _)).Select(f => f.Position).ToList();
        // A long route and a point on a straight stretch of it (not a corner).
        var (a, b) = (from x in ground from y in ground orderby Vector3.Distance(x, y) descending select (x, y)).First();
        var route = plain.Route(a, b, out bool ok);
        Check(ok && route.Count > 2, "a route across Plaza 1");
        int leg = Enumerable.Range(0, route.Count - 1).OrderByDescending(i => Vector3.Distance(route[i], route[i + 1])).First();
        var spot = Vector3.Lerp(route[leg], route[leg + 1], 0.5f);
        var cut = NavWorld.Bake(Install, 1, obstacles: new[] { spot });
        var detour = cut.Route(a, b, out bool ok2);
        Check(ok2 && detour.Count > 1, "still a route with the obstacle");
        float closest = detour.Zip(detour.Skip(1)).Min(s => DistanceToSegment(spot, s.First, s.Second));
        Check(closest > 20, $"the detour keeps clear of the obstacle (closest {closest:F0})");
    });

    Test("A zone-line arrow drawn in a wall is still reachable", () => {
        var nav = Bake(6);
        var entry = new Vector3(-1328, -240, -720);
        Check(nav.Snap(entry, out _, out var start, wide: true), "Pepper Park 2 entry on the mesh");
        var arrow = new Vector3(193, -192, 484);   // the '2' arrow, about 120 units from the floor
        var strict = nav.Route(start, arrow, out bool strictOk, wideTarget: true);
        var near = nav.RouteNear(start, arrow, out bool nearOk);
        Check(!(strict.Count > 1 && strictOk), "the plain route misses it");
        Check(nearOk && near.Count > 1, "RouteNear accepts the nearest floor within reach");
    });

    Test("The corridor toward a zone line follows the floor round walls", () => {
        var nav = Bake(2);
        Check(nav.Snap(new(-198, -250, 3411), out _, out var start, wide: true), "Plaza 2 arrow spot on the mesh");
        var corridor = nav.RouteToward(start, new(-929, -250, 3393));
        Check(corridor.Count > 3, $"goes round, not straight into the wall ({corridor.Count} corners)");
    });

    Test("An arrow far from every exit record gives way to the floor past the record", () => {
        var travel = NewTravel(Scratch());
        // Plaza 2 -> Plaza 1: the arrows pushed west at the corridor's mouth, into walls; the
        // floor goes on west from the exit record at -1072,2112, not south into its wall.
        var nav2 = Bake(2);
        var exit21 = travel.Exits(2).First(e => e.To == 1 && e.Exit.Name == "WorldChange2").Exit;
        var line = travel.LineFor(2, exit21, null, 1, nav: nav2);
        Check(travel.IsPastRecord(line.Key) && line.Push is not null, "Plaza 2 -> 1 uses the exit record");
        var tip = nav2.RouteToward(line.Walk, line.Push!.Value)[^1];
        Check(Vector3.Distance(line.Walk, exit21.Position) < 60, "walks to the exit record");
        Check(tip.X < -1400 && tip.Z > 2050, $"pushes on west along the floor (corridor ends at {tip.X:F0},{tip.Z:F0})");
        // Pepper Park 2 -> 3: the walker pressed a wall at x = 1407; the floor runs north from 1568,1920.
        var nav6 = Bake(6);
        var exit67 = travel.Exits(6).First(e => e.To == 7).Exit;
        line = travel.LineFor(6, exit67, null, 7, nav: nav6);
        Check(travel.IsPastRecord(line.Key) && line.Push is not null, "Pepper Park 2 -> 3 uses the exit record");
        tip = nav6.RouteToward(line.Walk, line.Push!.Value)[^1];
        Check(tip.Z > 2350 && tip.X > 1450, $"pushes on north along x 1568 (corridor ends at {tip.X:F0},{tip.Z:F0})");
        // A link whose arrow already pushes near its record keeps the arrow.
        var exit2_101 = travel.Exits(2).First(e => e.To == 101).Exit;
        var kept = travel.LineFor(2, exit2_101, null, 101, nav: nav2);
        Check(kept.Key != null && !travel.IsPastRecord(kept.Key), "Plaza 2 -> 3 still uses its map arrow");
    });

    Test("The simulated character crosses Plaza 1 with live-like lag and mouse error", () => {
        var nav = Bake(1);
        var ground = nav.World.Summary.Features.Where(f => f.Kind == "GroundPathPoint" && nav.Snap(f.Position, out _, out _)).Select(f => f.Position).ToList();
        var (a, b) = (from x in ground from y in ground orderby Vector3.Distance(x, y) descending select (x, y)).First();
        var outcome = Simulator.Run(nav, a, b, 280, 0.0024f, 1.3f, 24, new Random(3));
        Check(outcome.Arrived, $"arrives ({outcome.Reason})");
        Check(outcome.Replans == 0 && outcome.MaxOffRoute < 48, $"stays on the route (max off {outcome.MaxOffRoute:F0})");
    });
}

FollowTests.Run(Test);
PlaceTests.Run(Test, Install);
DoorObjectTests.Run(Test, Install);
TerrainTests.Run(Test, Install);
SubwayTests.Run(Test, Install);
LiftDoorTests.Run(Test, Install);
Console.WriteLine($"{passed} passed, {failed} failed");
return failed == 0 ? 0 : 1;

static float DistanceToSegment(Vector3 p, Vector3 a, Vector3 b)
{
    Vector2 pa = new(p.X - a.X, p.Z - a.Z), ab = new(b.X - a.X, b.Z - a.Z);
    float t = ab.LengthSquared() < 1e-4f ? 0 : Math.Clamp(Vector2.Dot(pa, ab) / ab.LengthSquared(), 0, 1);
    return (pa - ab * t).Length();
}
