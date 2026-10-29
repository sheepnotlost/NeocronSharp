using System.Numerics;
using NavmeshPrototype;

/// <summary>
/// Offline tests for the place list: objects and NPCs from a sector's spawn file
/// (<see cref="WorldObjects"/>) and the Nav-Ray menus placed on the street map
/// (<see cref="NavRayCatalog"/>). Read-only; the world tests need the local install.
/// </summary>
internal static class PlaceTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    public static void Run(Action<string, Action> test, string install)
    {
        // ---- the spawn-file reader on bad bytes: never throws, never loops ----
        test("A malformed spawn file ends the record list instead of throwing", () =>
        {
            static byte[] Bytes(params uint[] words) => words.SelectMany(BitConverter.GetBytes).ToArray();
            var samples = new[]
            {
                Array.Empty<byte>(),
                new byte[] { 1, 2 },
                Bytes(0xFFFFFFF0),                                  // first offset past the end
                Bytes(0, 0, 0, 2, 100),                             // header size 0: would loop forever
                Bytes(0, 12, 0, 2, 0xFFFFFFFF),                     // section bigger than the file
                Bytes(0, 0xFFFFFFF0, 0, 2, 16, 0, 0, 0, 0),         // header size past the end
                Bytes(0, 12, 0, 2, 16, 0xFFFFFFFC, 0, 1000003, 0),  // record header "size -4": would loop forever
                Bytes(0, 12, 0, 2, 16, 12, 0, 1000003, 0x7FFFFFFF), // record bigger than its section
            };
            foreach (var bytes in samples)
            {
                var task = Task.Run(() => WorldObjects.Elements(bytes).Take(1000).ToList());
                Check(task.Wait(TimeSpan.FromSeconds(5)), $"stops ({bytes.Length} bytes)");
                Check(task.Result.Count == 0, $"no records from {bytes.Length} bad bytes");
            }
            // A good one: one section-2 record of type 1000003 with 4 bytes of data.
            var good = Bytes(0, 12, 0, 2, 20, 12, 0, 1000003, 4, 0xABCD);
            var records = WorldObjects.Elements(good).ToList();
            Check(records.Count == 1 && records[0].Type == 1000003 && BitConverter.ToUInt32(records[0].Data) == 0xABCD, "reads a well-formed record");
        });

        if (!Directory.Exists(install)) return;

        // One Travel for all: the door graph takes ~20 s to build; reuse the engine's cached one.
        string logs = Path.Combine(Path.GetTempPath(), "traversal-placetests-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(logs);
        string cached = Path.Combine(Travel.Home, "logs", "door-graph.txt");
        if (File.Exists(cached)) File.Copy(cached, Path.Combine(logs, "door-graph.txt"));
        var travel = new Travel(install, id => throw new NotSupportedException("no baking in place tests"), new Hud(), logs, 12, true);
        var objects = new WorldObjects(install, travel);
        List<WorldObjects.Place>? plaza1 = null;
        List<WorldObjects.Place> Plaza1() => plaza1 ??= objects.In(1);
        List<NavRayCatalog.Entry>? navRay = null;
        List<NavRayCatalog.Entry> NavRay() => navRay ??= NavRayCatalog.Read(install, travel, travel.Streets(1));

        static string Near(IEnumerable<WorldObjects.Place> places, Vector3 at) =>
            string.Join("; ", places.OrderBy(p => Vector3.Distance(p.Position, at)).Take(3).Select(p => $"{p.Kind} '{p.Name}' at {p.Position.X:F0},{p.Position.Y:F0},{p.Position.Z:F0}"));

        test("Plaza 1's spawn file has a GenRep at -2061,-224,484", () =>
        {
            var at = new Vector3(-2061, -224, 484);
            var genRep = Plaza1().Where(p => p.Kind == "GenRep").OrderBy(p => Vector3.Distance(p.Position, at)).FirstOrDefault();
            Check(genRep != null && Vector3.Distance(genRep.Position, at) < 30, $"a GenRep within 30 units (nearest: {Near(Plaza1(), at)})");
            Check(genRep!.World == 1 && genRep.Name == "GENE REPLICATOR", $"named from pak_worldmodels (got '{genRep.Name}')");
            Check(Plaza1().Count(p => p.Kind == "GenRep") >= 2, "Plaza 1 has more than one GenRep");
        });

        test("Plaza 1's spawn file has the Venture Warp at -2164,81,1163", () =>
        {
            var at = new Vector3(-2164, 81, 1163);
            var warp = Plaza1().Where(p => p.Kind == "Venture Warp").OrderBy(p => Vector3.Distance(p.Position, at)).FirstOrDefault();
            Check(warp != null && Vector3.Distance(warp.Position, at) < 30, $"a Venture Warp within 30 units (nearest: {Near(Plaza1(), at)})");
        });

        test("Plaza 1's places are named and grouped", () =>
        {
            var places = Plaza1();
            Check(places.All(p => p.Name.Length > 0 && p.Labels.Count > 0), "every place has a name and labels");
            Check(places.All(p => !p.Name.Contains('\n') && !p.Name.Contains("---")), "names are cleaned (no line breaks, no ---)");
            Check(places.Any(p => p.Kind == "Trader") && places.Any(p => p.Kind == "CityCom") && places.Any(p => p.Kind == "GoGuardian"), "traders, CityComs and GoGuardians");
            // Grouping: no two places of one kind and name within 400 units of each other.
            foreach (var g in places.GroupBy(p => (p.Kind, p.Name)))
                foreach (var a in g) foreach (var b in g)
                    Check(ReferenceEquals(a, b) || Vector3.Distance(a.Position, b.Position) >= 400,
                        $"{g.Key.Kind} '{g.Key.Name}' split into two places {Vector3.Distance(a.Position, b.Position):F0} units apart");
        });

        test("A sector with no spawn file fails with a file error, not a crash", () =>
        {
            try { objects.In(-12345); Check(false, "expected an error"); }
            catch (InvalidDataException) { }
            catch (IOException) { }
        });

        test("Nav-Ray: PEPPER PARK / ZEPHRON COURT / ENTER B is Pepper Park 2's WorldChange19", () =>
        {
            var entry = NavRay().FirstOrDefault(e => e.Name == "PEPPER PARK / ZEPHRON COURT / ENTER B");
            Check(entry != null, "listed in the Nav-Ray menus");
            Check(entry!.Zone == 6 && entry.Target == "exit:WorldChange19", $"placed at Pepper Park 2 exit:WorldChange19 (got {entry.Zone} {entry.Target} {entry.Why})");
            Check(entry.Kind == "Apartment door" && entry.Why == null, $"an apartment door (got {entry.Kind})");
        });

        test("Nav-Ray: a street is a zone, the subway a door, nearest entries are left to the object list", () =>
        {
            var list = NavRay();
            Check(list.Any(e => e.Kind == "Zone" && e.Zone == 1 && e.Target == Travel.Arrive), "Plaza 1 is a zone entry");
            var subway = list.FirstOrDefault(e => e.Name == "NEOCRON SUBWAY");
            Check(subway is { Kind: "Entrance", Target: not null } && subway.Target.StartsWith("exit:"), $"the subway is a door (got {subway?.Kind} {subway?.Target})");
            var genRep = list.FirstOrDefault(e => e.Type == NavRayCatalog.GenRep);
            Check(genRep is { Target: null, Why: not null }, "\"nearest GenRep\" has no fixed target");
            Check(list.All(e => (e.Target == null) == (e.Why != null)), "an entry has a target or a reason, never both or neither");
            // On a street, or inside a building/sewer that a trip can reach through doors.
            var reach = travel.Reach(1);
            Check(list.Where(e => e.Target != null).All(e => travel.IsStreet(e.Zone) || reach.ContainsKey(e.Zone)), "placed entries are on a street or reachable through doors");
            Check(list.Where(e => e.Target != null && !travel.IsStreet(e.Zone)).All(e => e.Kind != "Zone"), "an entry inside a building is not shown as a street zone");
        });
    }
}
