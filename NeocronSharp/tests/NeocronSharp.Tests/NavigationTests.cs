using System.Numerics;
using System.Text.Json;
using NeocronSharp.Core;
using NeocronSharp.Navigation;

internal static class NavigationTests
{
    private sealed class FakeWorlds(NavWorld nav) : INavWorlds
    {
        public int Gets;
        public NavWorld Get(int worldId) { Gets++; return worldId == nav.World.Summary.WorldId ? nav : throw new InvalidDataException("No world asset is defined for this area."); }
        public string? WorldName(int worldId) => worldId == 7 ? "TEST DESTINATION" : null;
        public string LastSource => "memory";
    }

    /// <summary>A 1000 x 1000 floor at Y = 0 with a 200-high wall block across x 490..510, z 0..800, so the way
    /// from the near-left corner to the near-right one has to go round the wall's far end. GBSP winding (floor
    /// normals point down), like the game's levels.</summary>
    private static EnvironmentWorld TestWorld()
    {
        var v = new List<Vector3>(); var t = new List<int>();
        void Quad(Vector3 a, Vector3 b, Vector3 c, Vector3 d) { int i = v.Count; v.AddRange(new[] { a, b, c, d }); t.AddRange(new[] { i, i + 1, i + 2, i, i + 2, i + 3 }); }
        Quad(new(0, 0, 0), new(1000, 0, 0), new(1000, 0, 1000), new(0, 0, 1000));
        float x0 = 490, x1 = 510, z1 = 800, h = 200;
        Quad(new(x0, 0, 0), new(x0, h, 0), new(x0, h, z1), new(x0, 0, z1));
        Quad(new(x1, 0, 0), new(x1, 0, z1), new(x1, h, z1), new(x1, h, 0));
        Quad(new(x0, 0, z1), new(x0, h, z1), new(x1, h, z1), new(x1, 0, z1));
        Quad(new(x0, 0, 0), new(x1, 0, 0), new(x1, h, 0), new(x0, h, 0));
        Quad(new(x0, h, 0), new(x1, h, 0), new(x1, h, z1), new(x0, h, z1));
        EnvironmentFeature Exit(string name, Vector3 at, string next, string start) => new("WorldChange", name, at,
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["classname"] = "WorldChange", ["Index"] = "4", ["NextLevel"] = next, ["NextLevelStartIndex"] = start });
        var features = new List<EnvironmentFeature>
        {
            Exit("WorldChange10", new(100, 16, 900), "1", "0"),       // a placeholder (no arrival point), straight "down" in Z
            Exit("WorldChange2", new(900, 16, 100), "7", "1"),        // the real zone exit, beyond the wall in +X
            Exit("WorldChange3", new(5000, 16, 5000), "7", "2"),      // off the mesh
            new("GroundPathPoint", "GroundPathPoint1", new(100, 0, 100), new Dictionary<string, string>()),
        };
        var summary = new EnvironmentSummary(42, "TEST SECTOR", "test.bsp", v.Count, t.Count / 3, 1, 1, 0, 3, features);
        return new(summary, new(v.ToArray(), t.ToArray()));
    }

    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        var world = TestWorld();
        var nav = NavWorld.Build(world);
        var start = new Vector3(100, 0, 100);
        var goal = new Vector3(900, 0, 100);

        test("Navmesh bakes GBSP-wound floors and routes around a wall", () =>
        {
            check(nav.Polygons().Count > 0, "The floor is walkable");
            var path = nav.Route(start, goal, out bool complete);
            check(complete && path.Count >= 3, $"Complete multi-corner route ({path.Count} corners)");
            check(path.Max(p => p.Z) > 800, "The route goes round the wall's far end");
            check(NavWorld.Length(path) > 1400, $"Walked length beats the blocked straight line ({NavWorld.Length(path):F0})");
            check(PointNavigation.Distance(path[^1], goal) < 1 && Math.Abs(path[^1].Y - goal.Y) < 4, $"Ends on the goal ({path[^1]})");
            check(!nav.Clear(start, goal) && nav.Clear(start, new(100, 0, 900)), "Raycast sees the wall and the open floor");
        });
        test("A saved navmesh loads back and plans the same route", () =>
        {
            using var stream = new MemoryStream();
            nav.Save(stream);
            stream.Position = 0;
            var loaded = NavWorld.Load(world, stream);
            var a = nav.Route(start, goal, out _); var b = loaded.Route(start, goal, out bool complete);
            check(complete && a.Count == b.Count && a.Zip(b).All(p => Vector3.Distance(p.First, p.Second) < 0.01f), "Same corners after a round trip");
            check(loaded.BakeTime == TimeSpan.Zero && loaded.Polygons().Count == nav.Polygons().Count, "Loaded, not baked");
        });
        test("Navmesh cache key follows the world, the BSP hash and the build settings", () =>
        {
            var settings = NavWorld.DefaultSettings();
            string a = NavMeshStore.CacheFileName(1, new string('A', 64), settings);
            check(a.StartsWith("world-1-aaaaaaaaaaaaaaaa-") && a.EndsWith(".navmesh"), a);
            check(a != NavMeshStore.CacheFileName(1, new string('B', 64), settings), "A changed BSP changes the key");
            check(a != NavMeshStore.CacheFileName(2, new string('A', 64), settings), "Worlds do not share a key");
            settings.agentRadius = 20;
            check(a != NavMeshStore.CacheFileName(1, new string('A', 64), settings), "Changed settings change the key");
        });

        var worlds = new FakeWorlds(nav);
        var protocol = new NavPlanProtocol(worlds);
        var here = new NavLocation(42, start);
        JsonElement Ask(string request, NavLocation? at = null) => JsonDocument.Parse(protocol.Answer(request, () => at ?? here)).RootElement;
        test("Navplan lists exits with destinations and routes", () =>
        {
            var answer = Ask("{\"to\":\"exits\",\"id\":5}");
            check(answer.GetProperty("ok").GetBoolean() && answer.GetProperty("id").GetInt32() == 5 && answer.GetProperty("world").GetInt32() == 42, answer.ToString());
            check(answer.GetProperty("worldName").GetString() == "TEST SECTOR" && answer.GetProperty("mesh").GetString() == "memory", "World and mesh source");
            var exits = answer.GetProperty("exits").EnumerateArray().ToList();
            check(string.Join(",", exits.Select(e => e.GetProperty("name").GetString())) == "WorldChange2,WorldChange3,WorldChange10", "Natural name order");
            var two = exits[0];
            check(two.GetProperty("nextLevel").GetInt32() == 7 && two.GetProperty("nextLevelName").GetString() == "TEST DESTINATION" &&
                two.GetProperty("nextLevelStartIndex").GetInt32() == 1 && two.GetProperty("destinationKnown").GetBoolean(), two.ToString());
            check(two.GetProperty("complete").GetBoolean() && two.GetProperty("pathLength").GetDouble() > 1400, "Walked length to the exit");
            check(Math.Abs(two.GetProperty("bearing").GetDouble() - 90) < 0.01 && Math.Abs(two.GetProperty("distance").GetDouble() - 800) < 0.01, "Bearing/distance from the player");
            check(exits[1].GetProperty("pathLength").ValueKind == JsonValueKind.Null && !exits[1].GetProperty("complete").GetBoolean(), "Off-mesh exit has no route");
            check(!exits[2].GetProperty("destinationKnown").GetBoolean() && exits[2].GetProperty("nextLevelName").ValueKind == JsonValueKind.Null, "Placeholder exit");
        });
        test("Navplan plans to an exit by name", () =>
        {
            var answer = Ask("{\"to\":\"exit\",\"name\":\"worldchange2\"}");
            check(answer.GetProperty("ok").GetBoolean() && answer.GetProperty("complete").GetBoolean(), answer.ToString());
            var path = answer.GetProperty("path").EnumerateArray().Select(p => p.EnumerateArray().Select(c => c.GetSingle()).ToArray()).ToList();
            check(path.Count >= 3 && path.All(p => p.Length == 3), "Corner list of [x,y,z]");
            check(Math.Abs(path[0][0] - 100) < 1 && Math.Abs(path[0][2] - 100) < 1, "Starts at the player");
            check(Math.Abs(path[^1][0] - 900) < 1 && Math.Abs(path[^1][2] - 100) < 1, "Ends at the exit");
            check(answer.GetProperty("exit").GetProperty("name").GetString() == "WorldChange2", "Exit info");
            check(answer.GetProperty("from").EnumerateArray().Select(c => c.GetDouble()).SequenceEqual(new double[] { 100, 0, 100 }), "From is the live position");
            var missing = Ask("{\"to\":\"exit\",\"name\":\"WorldChange9\",\"id\":\"q\"}");
            check(!missing.GetProperty("ok").GetBoolean() && missing.GetProperty("id").GetString() == "q" &&
                missing.GetProperty("error").GetString()!.Contains("WorldChange2, WorldChange3, WorldChange10"), missing.ToString());
        });
        test("Navplan picks the reachable zone exit nearest a bearing", () =>
        {
            check(Ask("{\"to\":\"exit\",\"bearing\":80}").GetProperty("exit").GetProperty("name").GetString() == "WorldChange2", "Bearing 80 -> +X exit");
            // WorldChange10 lies at 180 but is a placeholder, so the zone exit still wins.
            check(Ask("{\"to\":\"exit\",\"bearing\":180}").GetProperty("exit").GetProperty("name").GetString() == "WorldChange2", "Zone exits before placeholders");
            var stranded = Ask("{\"to\":\"exit\",\"bearing\":0}", new NavLocation(42, new(5000, 0, -5000)));
            check(!stranded.GetProperty("ok").GetBoolean(), "Off the mesh there is nothing reachable");
        });
        test("Navplan plans to a point with or without a height", () =>
        {
            var flat = Ask("{\"to\":\"point\",\"x\":100,\"z\":900}");
            check(flat.GetProperty("ok").GetBoolean() && flat.GetProperty("complete").GetBoolean() && flat.GetProperty("path").GetArrayLength() == 2, flat.ToString());
            check(Math.Abs(flat.GetProperty("length").GetDouble() - 800) < 1, "Straight open walk");
            var high = Ask("{\"to\":\"point\",\"x\":900,\"y\":0,\"z\":100}");
            check(high.GetProperty("ok").GetBoolean() && high.GetProperty("path").GetArrayLength() >= 3, "Explicit height");
            check(!Ask("{\"to\":\"point\",\"x\":100}").GetProperty("ok").GetBoolean(), "z is required");
        });
        test("Navplan reports bad requests and an unavailable game as ok:false", () =>
        {
            check(Ask("not json").GetProperty("error").GetString()!.StartsWith("Unreadable request"), "Bad JSON");
            check(!Ask("[1]").GetProperty("ok").GetBoolean() && !Ask("{\"to\":\"moon\"}").GetProperty("ok").GetBoolean(), "Wrong shapes");
            check(!Ask("{\"to\":\"exit\"}").GetProperty("ok").GetBoolean(), "Exit needs a name or bearing");
            var down = JsonDocument.Parse(protocol.Answer("{\"to\":\"exits\",\"id\":1}", () => throw new InvalidOperationException("The current sector is unavailable. Finish zoning."))).RootElement;
            check(!down.GetProperty("ok").GetBoolean() && down.GetProperty("id").GetInt32() == 1 && down.GetProperty("error").GetString()!.Contains("zoning"), down.ToString());
            var unknown = Ask("{\"to\":\"exits\"}", new NavLocation(43, start));
            check(unknown.GetProperty("error").GetString()!.Contains("No world asset"), "Unknown world");
            string line = protocol.Answer("{\"to\":\"exits\"}", () => here);
            check(!line.Contains('\n'), "One line per answer");
        });
    }
}
