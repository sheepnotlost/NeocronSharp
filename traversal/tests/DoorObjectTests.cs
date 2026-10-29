using System.Numerics;
using NavmeshPrototype;
using NeocronSharp.Core;

/// <summary>
/// Offline tests for the doors the game routes itself: a placed object in a sector's spawn file
/// whose pak_worldmodels Value is a pak_appplaces EntryId (<see cref="Travel.ObjectDoors"/>), and
/// the Nav-Ray entries they place. Read-only; needs the local install.
/// </summary>
internal static class DoorObjectTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    public static void Run(Action<string, Action> test, string install)
    {
        if (!Directory.Exists(install)) return;
        string logs = Path.Combine(Path.GetTempPath(), "traversal-doortests-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(logs);
        string cached = Path.Combine(Travel.Home, "logs", "door-graph.txt");
        if (File.Exists(cached)) File.Copy(cached, Path.Combine(logs, "door-graph.txt"));
        var travel = new Travel(install, id => throw new NotSupportedException("no baking in door tests"), new Hud(), logs, 12, true);
        List<NavRayCatalog.Entry>? navRay = null;
        List<NavRayCatalog.Entry> NavRay() => navRay ??= NavRayCatalog.Read(install, travel, travel.Streets(1));
        var places = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_appplaces.csv")));

        (EnvironmentFeature Door, int To) DoorNear(int sector, Vector3 at, int to, float within = 30)
        {
            var doors = travel.ObjectDoors().GetValueOrDefault(sector) ?? new();
            var door = doors.Where(d => d.To == to).OrderBy(d => Vector3.Distance(d.Door.Position, at)).FirstOrDefault();
            Check(door.Door != null && Vector3.Distance(door.Door.Position, at) < within,
                $"a door object within {within} of {at.X},{at.Z} into {travel.SectorName(to)} (has: {string.Join("; ", doors.Select(d => $"{d.Door.Position.X:F0},{d.Door.Position.Z:F0}->{d.To}"))})");
            return door;
        }

        test("The mechanism on known doors: a sewer object's appplace is the street door's Index", () =>
        {
            // Plaza 1's three sewer doors were placed before from inside (WorldChange Index 52, 54, 56).
            // Each sits on a door object whose pak_worldmodels Value is that same pak_appplaces EntryId,
            // and the row's ExitWorldId is the sewer the WorldChange leads to.
            foreach (var (index, sewer) in new[] { ("52", 920), ("54", 921), ("56", 922) })
            {
                var wc = travel.Features(1).Single(f => f.Kind == "WorldChange" && f.Properties.GetValueOrDefault("Index") == index);
                var door = DoorNear(1, wc.Position, sewer, within: 100);   // the door model stands beside the WorldChange
                Check(door.Door.Properties["AppPlace"] == index, $"door object at WorldChange Index {index} names appplace {door.Door.Properties["AppPlace"]}");
                Check(places[int.Parse(index)]["ExitWorldId"] == sewer.ToString(), $"appplace {index} leads to {sewer}");
            }
            // The apartment doors placed via pak_appplaces: EntryId 281 exits at Pepper Park 2's Index 281 (WorldChange19).
            Check(places[281]["ExitWorldId"] == "6" && places[281]["ExitWorldEntity"] == "281", "Zephron Court Enter B exits at Pepper Park 2 Index 281");
        });

        test("Pepper Park 1's door object leads into Apartment Complex 1, and its exit object back", () =>
        {
            var door = DoorNear(5, new Vector3(1503, -703, -106), 616);
            Check(door.Door.Kind == Travel.ObjectDoor && door.Door.Properties["AppPlace"] == "5700", $"appplace 5700 (got {door.Door.Properties["AppPlace"]})");
            Check(travel.Links(5).Any(l => l.To == 616), "a link from Pepper Park 1 to the complex");
            var back = travel.Links(616).Where(l => l.To == 5).ToList();
            Check(back.Count == 1 && Vector3.Distance(back[0].Exit.Position, new Vector3(-319, 1, 65)) < 30, "the complex's exit object leads back to Pepper Park 1");
            Check(travel.Neighbours(5).Contains(616), "walkable both ways");
            var path = travel.SectorPath(1, 616);
            Check(path.Count >= 2 && path[^2] == 5 && path[^1] == 616, $"Plaza 1 to the complex goes in from Pepper Park 1 ({string.Join(" > ", path.Select(travel.SectorName))})");
        });

        test("A dungeon copied from the Dome of York leads back where pak_appplaces pairs it, not to the DoY", () =>
        {
            // Outzone Side Street 1: entered from Outzone 1 by appplace 4500; 4501 exits to Outzone 1.
            // The client's file still has the DoY side street's exit object (appplace 4525, to DoY sector 4).
            DoorNear(9, new Vector3(-1122, 0, -1103), 1300);
            var out1 = travel.Links(1300).ToList();
            Check(out1.Any(l => l.To == 9) && out1.All(l => l.To != 1104), $"Side Street 1 leads back to Outzone 1 only (got {string.Join(", ", out1.Select(l => l.To))})");
            Check(travel.Reach(1).ContainsKey(1300), "reached from Plaza 1");
        });

        test("Door objects never join two streets, and none lead nowhere", () =>
        {
            foreach (var (sector, doors) in travel.ObjectDoors())
                foreach (var (door, to) in doors)
                {
                    Check(!(travel.IsStreet(sector) && travel.IsStreet(to)), $"{travel.SectorName(sector)} {door.Name} -> {travel.SectorName(to)} is street to street");
                    Check(to != sector && to != Travel.Subway && travel.Areas.Any(a => a.WorldId == to), $"{travel.SectorName(sector)} {door.Name} -> {to}");
                }
        });

        test("Nav-Ray: the apartment complexes, Outzone dungeons and Jones places are placed", () =>
        {
            var list = NavRay();
            NavRayCatalog.Entry Named(string name) => list.FirstOrDefault(e => e.Name == name) ?? throw new Exception($"'{name}' not in the Nav-Ray menus");
            var a = Named("PEPPER PARK / APARTMENT COMPLEX 1 / ENTER A");
            Check(a.Zone == 616 && a.Target == "exit:WorldChange12" && a.Why == null, $"Complex 1 Enter A is door 5 inside the complex (got {a.Zone} {a.Target} {a.Why})");
            foreach (var name in new[] { "Outzone 1 - Side Street 1 (hard)", "Outzone 2 - Storage Halls 2 (hard)", "GHOST DISTRICT", "SMUGGLERS CAVE", "TIKI TORNADO CLUB", "ELECTRIC VIBES CLUB", "Plaza 3 - The Pit" })
            {
                var e = Named(name);
                Check(e.Target == Travel.Arrive && e.Kind == "Entrance" && e.Why == null, $"{name} is walkable (got {e.Target} {e.Why})");
            }
            var login = Named("LOW SEC LOGIN PP1");
            Check(login.Zone == 5 && login.Target is { } spot && spot.Count(c => c == ',') == 2, $"the Pepper Park 1 Hacknet login is a spot in Pepper Park 1 (got {login.Zone} {login.Target} {login.Why})");
        });

        test("Nav-Ray: what is left says exactly why", () =>
        {
            var list = NavRay();
            var sec7 = list.First(e => e.Name == "Outzone 3 - Water Cleaning Sec 7 (hard)");
            Check(sec7.Why is { } w7 && w7.Contains("no door into it"), $"Sec 7: {sec7.Why}");
            var sec8 = list.First(e => e.Name == "Outzone 3 - Water Cleaning Sec 8 (hard)");
            // Its door is in BATTLEFIELD DOY SECTOR 8, whose own door stands in wasteland cell K 16: placed now the walker crosses the wasteland.
            Check(sec8.Why == null && sec8.Target != null, $"Sec 8 is reached across the wasteland, through the DoY sector its door is in: {sec8.Zone} {sec8.Target} {sec8.Why}");
            var cave = list.First(e => e.Name == "E12 - Canyon Cave");
            Check(cave.Why is { } wc && wc.Contains("E 12 - CANYONS") && wc.Contains("wasteland"), $"the canyon cave names the wasteland cell its door is in: {cave.Why}");
            Check(list.Where(e => e.Why != null).All(e => !e.Why!.Contains("the files do not say where it is")), "no entry is left with the old vague reason");
        });
    }
}
