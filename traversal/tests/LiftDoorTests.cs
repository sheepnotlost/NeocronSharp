using System.Numerics;
using NavmeshPrototype;
using NeocronSharp.Core;

/// <summary>
/// Offline tests for the walkable ways the level geometry lacks: gravity lifts (AntiGravParticle
/// beams, baked as off-mesh links), doors inside a sector and solid props (both from the sector's
/// spawn file). Read-only; needs the local install.
/// </summary>
internal static class LiftDoorTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    public static void Run(Action<string, Action> test, string install)
    {
        test("Door rule: only a door ahead within 150 units, two tries per door", () =>
        {
            var door = new SectorObjects.Door("DOOR2", new Vector3(100, 0, 0));
            var opener = new DoorOpener(new[] { door });
            Check(opener.Ahead(new Vector3(0, 0, 0), new Vector3(1, 0, 0)) == door, "facing it from 100 units");
            Check(opener.Ahead(new Vector3(0, 0, 0), new Vector3(-1, 0, 0)) == null, "not when facing away");
            Check(opener.Ahead(new Vector3(-100, 0, 0), new Vector3(1, 0, 0)) == null, "not from 200 units");
            Check(opener.Ahead(new Vector3(0, 400, 0), new Vector3(1, 0, 0)) == null, "not from the floor above");
            Check(opener.Try(door) && opener.Try(door) && !opener.Try(door), "two tries, then it counts as shut");
        });

        test("A followed target on the floor above is not 'within reach'", () =>
        {
            Check(FollowLogic.Straight(Vector3.Zero, new Vector3(50, 40, 0)) == 50, "a step's height does not count");
            Check(FollowLogic.Straight(Vector3.Zero, new Vector3(50, 600, 0)) > 500, "a floor 600 above counts");
        });

        if (!Directory.Exists(install)) return;
        var bakes = new Dictionary<int, NavWorld>();
        NavWorld Bake(int id) => bakes.TryGetValue(id, out var n) ? n : bakes[id] = NavWorld.Bake(install, id);

        test("Plaza 1's gravity lifts are links from the street to the upper floors and back", () =>
        {
            var nav = Bake(1);
            var beams = Lifts.Beams(nav.World);
            Check(beams.Count == 4 && beams.Count(b => b.Up) == 2, $"two up and two down beams (got {beams.Count})");
            // The lift by Archer & Wesson's upper floor and the showrooms: its foot at -2136,-242,-272.
            var up = nav.Lifts.Where(l => l.Up && Vector3.Distance(l.Start, new Vector3(-2136, -242, -272)) < 20).ToList();
            Check(up.Any(l => MathF.Abs(l.End.Y - 418) < 20), "up to the y 418 floor (Archer & Wesson's)");
            Check(up.Any(l => MathF.Abs(l.End.Y - 706) < 20), "up to the y 706 floor (the showrooms)");
            Check(nav.Lifts.Any(l => !l.Up && MathF.Abs(l.Start.Y - 706) < 20 && MathF.Abs(l.End.Y + 242) < 20), "and down again by the other beam");
            Check(nav.Lifts.All(l => l.Up == l.End.Y > l.Start.Y), "up beams only go up, down beams only down");
        });

        test("Routes between Plaza 1's floors take a lift, and the simulated walk rides it", () =>
        {
            var nav = Bake(1);
            var street = new Vector3(-2900, -255, -400);
            var showroom = new Vector3(-1566, 705, -25);        // Showroom: Plaza Level I
            var armour = new Vector3(212, 513, 104);            // Archer & Wesson / Basic Armor
            foreach (var (from, to, what) in new[] { (street, showroom, "street to the showrooms"), (street, armour, "street to Archer & Wesson upstairs"), (armour, street, "back down to the street") })
            {
                var route = nav.Route(from, to, out bool complete, wideTarget: true);
                Check(complete && route.Count > 2, $"{what}: a complete route");
                int lifts = Enumerable.Range(0, route.Count - 1).Count(i => nav.LinkAt(route[i], route[i + 1]) != null);
                Check(lifts >= 1, $"{what}: uses a lift ({lifts})");
                Check(MathF.Abs(route[^1].Y - to.Y) < 30, $"{what}: ends on the target's floor (y {route[^1].Y:F0})");
            }
            var ride = Simulator.Run(nav, street, showroom, 280, 0.0024f, 1.3f, 24, new Random(5));
            Check(ride.Arrived && ride.Lifts >= 1, $"the simulation arrives upstairs by lift ({ride.Reason}, {ride.Lifts} lifts)");
        });

        test("Door objects are found where Plaza 1's doors are", () =>
        {
            var nav = Bake(1);
            Check(nav.Doors.Count >= 5, $"several doors (got {nav.Doors.Count})");
            // The BSP's own door models: "splitdoor r/l" at -1926,-170,794/870, and models 302/303 at -2140/-2068,-176,3484.
            foreach (var at in new[] { new Vector3(-1926, -170, 832), new Vector3(-2104, -176, 3484) })
            {
                var near = nav.Doors.OrderBy(d => Vector3.Distance(d.Position, at)).First();
                Check(Vector3.Distance(near.Position, at) < 40, $"a door within 40 units of {at.X},{at.Z} (nearest {Vector3.Distance(near.Position, at):F0})");
            }
            var opener = new DoorOpener(nav.Doors);
            Check(opener.Ahead(new Vector3(-1924, -174, 700), new Vector3(0, 0, 1)) != null, "walking north up to the split door, it is ahead");
        });

        test("Solid props are cut out of the navmesh; doors and entrances are not", () =>
        {
            var nav = Bake(5);   // Pepper Park 1: barrels and crates stopped a live walk there
            var contents = SectorObjects.Read(install, nav.World.Summary.Source);
            var barrels = contents.Props.Where(p => p.Name.StartsWith("barrel", StringComparison.OrdinalIgnoreCase)).ToList();
            Check(barrels.Count >= 10 && contents.Props.Any(p => p.Name == "ROTTEN BOX"), $"barrels and boxes found ({barrels.Count} barrels)");
            Check(nav.PropCount == contents.Props.Count, "every prop is cut");
            Check(!contents.Props.Any(p => SectorObjects.IsDoorName(p.Name) || p.Name.Contains("ENTRANCE", StringComparison.OrdinalIgnoreCase) || p.Name.Contains("SEWER", StringComparison.OrdinalIgnoreCase)),
                "no doors, entrances or sewers among the props");
            int clear = barrels.Count(b => !nav.Snap(b.Position, out _, out var on) || PointNavigation.Distance(on, b.Position) >= 20);
            Check(clear >= barrels.Count * 0.9, $"no floor under the barrels ({clear} of {barrels.Count})");
        });
    }
}
