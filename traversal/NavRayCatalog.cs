using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// The in-game Nav-Ray's destination list, read from the game's own tables
/// (definitions\pak_routemenus.csv, pak_routesubmenus.csv, pak_appplaces.csv), and placed
/// on the street map: a zone, the door into a building or dungeon, or an apartment door.
/// </summary>
internal static class NavRayCatalog
{
    /// <summary>One Nav-Ray entry. Zone/Target are null when it cannot be walked to from a street.</summary>
    public sealed record Entry(string Category, string Name, int Type, int Aux, int Zone, string? Target, string Kind, string? Why);

    // pak_routesubmenus DestinationType: 1 and 2 name a world (sector, building, dungeon),
    // 5 an apartment door (via pak_appplaces); 3 GenRep, 4 GoGuardian, 7 CityCom, 8 trader kind
    // mean "the nearest one", which needs object positions the tables do not give. 12 is a Hacknet
    // login (DestinationAuxType = the pak_appplaces EntryId its pak_worldmodels Value names).
    private const int World = 1, Sector = 2, Apartment = 5, Hacknet = 12;
    public const int GenRep = 3, GoGuardian = 4, CityCom = 7, Trader = 8;

    /// <summary>For "nearest trader of kind X" (type 8): words in the trader's shown name, by DestinationAuxType.</summary>
    public static readonly Dictionary<int, string[]> TraderWords = new()
    {
        [-2] = new[] { "Allbuyer", "All Buyer" }, [1] = new[] { "Weapon" }, [2] = new[] { "Ammo", "Ammunition" }, [3] = new[] { "Armor", "Armour" },
        [4] = new[] { "Tool" }, [5] = new[] { "Psi", "PSI" }, [10] = new[] { "Chemical" }, [11] = new[] { "Parts" },
        [12] = new[] { "Implant" }, [13] = new[] { "Bone" }, [20] = new[] { "Bar", "Refreshment", "Diner", "Food" },
        [21] = new[] { "Drug" }, [22] = new[] { "Medic" }, [23] = new[] { "Real Estate", "Estate" }, [24] = new[] { "Vehicle" },
    };

    /// <param name="streets">Street zones you can walk to, nearest first.</param>
    public static List<Entry> Read(string install, Travel travel, IReadOnlyList<int> streets)
    {
        var isStreet = streets.ToHashSet();
        // Everything a trip can reach, through buildings and sewers too (streets[0] is where you are).
        var reachable = travel.Reach(streets.Count > 0 ? streets[0] : 1);
        Dictionary<int, Dictionary<string, string>> Table(string name) =>
            NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", $"pak_{name}.csv")));
        var menus = Table("routemenus"); var items = Table("routesubmenus"); var apartments = Table("appplaces");

        // Which street door leads into each world (in the nearest zone that has one).
        var doorInto = new Dictionary<int, (int Zone, string Exit)>();
        foreach (int zone in streets)
            foreach (var (exit, to) in SafeExits(travel, zone))
                doorInto.TryAdd(to, (zone, exit.Name));

        var list = new List<Entry>();
        // Rows with a blank or missing field are skipped, never fatal (game updates change tables).
        static int? Number(Dictionary<string, string> row, string field) => int.TryParse(row.GetValueOrDefault(field), out int n) ? n : null;
        foreach (var menu in menus.OrderBy(m => m.Key).Select(m => m.Value).Where(m => m.GetValueOrDefault("Enabled") == "1"))
        {
            if (menu.GetValueOrDefault("Description") is not { Length: > 0 } category || Number(menu, "IdStart") is not int first || Number(menu, "IdEnd") is not int last) continue;
            // Target 1: the ids are apartment places themselves (pak_appplaces), not menu items.
            bool direct = menu.GetValueOrDefault("Target") == "1";
            var source = direct
                ? apartments.Where(a => a.Key >= first && a.Key <= last).Select(a => (a.Key, Name: a.Value.GetValueOrDefault("Description"), Type: (int?)Apartment, Aux: (int?)a.Key, Enabled: a.Value.GetValueOrDefault("Enabled")))
                : items.Where(i => i.Key >= first && i.Key <= last).Select(i => (i.Key, Name: i.Value.GetValueOrDefault("Description"), Type: Number(i.Value, "DestinationType"), Aux: Number(i.Value, "DestinationAuxType"), Enabled: i.Value.GetValueOrDefault("Enabled")));
            foreach (var (_, shown, typeRead, auxRead, enabled) in source.Where(i => i.Enabled == "1").OrderBy(i => i.Key))
            {
                if (shown is not { Length: > 0 } name || typeRead is not int type || auxRead is not int aux) continue;
                Entry Unplaced(string why) => new(category, name, type, aux, 0, null, "", why);
                if (type is World or Sector)
                {
                    if (isStreet.Contains(aux)) list.Add(new(category, name, type, aux, aux, Travel.Arrive, "Zone", null));
                    else if ((doorInto.TryGetValue(aux, out var known) ? known : DoorFromInside(travel, aux, streets)) is { } door)
                        list.Add(new(category, name, type, aux, door.Zone, "exit:" + door.Exit, "Entrance", null));
                    // Behind more than one door (a building inside a building, a sewer level): go there.
                    else if (reachable.ContainsKey(aux)) list.Add(new(category, name, type, aux, aux, Travel.Arrive, "Entrance", null));
                    else list.Add(Unplaced(Unreachable(travel, aux, reachable)));
                }
                else if (type == Apartment)
                {
                    if (!apartments.TryGetValue(aux, out var place)) { list.Add(Unplaced("your own apartment: which one is not in the game files")); continue; }
                    if (Number(place, "ExitWorldId") is not int zone || place.GetValueOrDefault("ExitWorldEntity") is not { Length: > 0 } index) { list.Add(Unplaced("its door is missing from the game files")); continue; }
                    if (!isStreet.Contains(zone) && !reachable.ContainsKey(zone)) { list.Add(Unplaced($"inside {travel.SectorName(zone)}: {Unreachable(travel, zone, reachable)}")); continue; }
                    var exit = SafeFeatures(travel, zone).FirstOrDefault(f => f.Kind == "WorldChange" && f.Properties.GetValueOrDefault("Index") == index);
                    list.Add(exit == null ? Unplaced($"door {index} not found in {travel.SectorName(zone)}")
                        : new(category, name, type, aux, zone, "exit:" + exit.Name, "Apartment door", null));
                }
                else if (type == Hacknet)
                    list.Add(HacknetLogin(install, travel, streets, aux) is { } login
                        ? new(category, name, type, aux, login.Zone, login.Spot, "Hacknet login", null)
                        : Unplaced($"no Hacknet login for pak_appplaces {aux} in the spawn file of any street the walker reaches"));
                else list.Add(Unplaced("\"nearest\" entries need object positions"));
            }
        }
        return list;
    }

    /// <summary>
    /// Sewers, cellars and clubs are entered by street doors the game routes itself (no arrival
    /// point on the street side). Their own exits name the street door you come out of:
    /// NextLevelStartIndex is that door's Index. Nearest street first.
    /// </summary>
    private static (int Zone, string Exit)? DoorFromInside(Travel travel, int world, IReadOnlyList<int> streets)
    {
        var back = SafeFeatures(travel, world).Where(f => f.Kind == "WorldChange")
            .Select(f => (Zone: int.TryParse(f.Properties.GetValueOrDefault("NextLevel"), out int z) ? z : 0, Index: f.Properties.GetValueOrDefault("NextLevelStartIndex")))
            .ToList();
        foreach (int zone in streets)
            foreach (var (_, index) in back.Where(b => b.Zone == zone && b.Index is { } i && i != "0"))
                if (SafeFeatures(travel, zone).FirstOrDefault(f => f.Kind == "WorldChange" && f.Properties.GetValueOrDefault("Index") == index) is { } door)
                    return (zone, door.Name);
        return null;
    }

    /// <summary>
    /// A Hacknet login (pak_worldmodels Type 33) whose Value is <paramref name="place"/>, in the
    /// nearest street that has one: its position as a walk target ("x,y,z").
    /// </summary>
    private static (int Zone, string Spot)? HacknetLogin(string install, Travel travel, IReadOnlyList<int> streets, int place)
    {
        var models = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_worldmodels.csv")));
        var objects = new WorldObjects(install, travel);
        foreach (int zone in streets)
        {
            List<(int Record, int Model, System.Numerics.Vector3 At)> placed;
            try { placed = objects.Placed(zone).ToList(); }
            catch (Exception e) when (e is IOException or InvalidDataException) { continue; }
            foreach (var (_, model, at) in placed)
                if (models.TryGetValue(model, out var row) && row.GetValueOrDefault("Type") == "33" && row.GetValueOrDefault("Value") == place.ToString())
                    return (zone, string.Create(System.Globalization.CultureInfo.InvariantCulture, $"{at.X:F0},{at.Y:F0},{at.Z:F0}"));
        }
        return null;
    }

    // Why a world cannot be walked to, from the doors the files show into and out of it.
    private static string Unreachable(Travel travel, int world, IReadOnlyDictionary<int, int> reachable)
    {
        string name = travel.SectorName(world);
        var into = travel.DoorsInto(world).ToList();
        var links = travel.Links(world).Select(l => l.To).Distinct().ToList();
        static bool Wasteland(string sector) => System.Text.RegularExpressions.Regex.IsMatch(sector, @"^[A-Z] \d\d - ");
        string Names(IEnumerable<int> sectors) => string.Join(", ", sectors.Select(travel.SectorName).Distinct().Take(3));
        if (into.Count == 0 && links.Count == 0)
            return $"{name}: no door into it in the client's files (no WorldChange or door object leads there; the server routes it)";
        if (links.Count > 0 && links.All(l => l == Travel.Subway)) return $"{name} is only reached by subway train";
        if (into.Where(reachable.ContainsKey).ToList() is { Count: > 0 } reached && !links.Any(reached.Contains))
            return $"{name}: a door in {Names(reached)} leads in, but the files give no way back out";
        var waste = into.Concat(links).Where(s => Wasteland(travel.SectorName(s))).ToList();
        // The walker crosses the wasteland now (TerrainTravel): what is left there has no walkable way in.
        if (Wasteland(name)) return $"{name} is out in the wasteland, in a part no walkable way reaches";
        if (waste.Count > 0) return $"{name} is out in the wasteland (its door is in {Names(waste)}), but no walkable way to that door was found";
        if (into.Count == 0) return $"{name}: no door into it in the client's files (its own exits lead to {Names(links)})";
        return $"{name}: its only door{(into.Count > 1 ? "s are" : " is")} in {Names(into)}, which the walker does not reach";
    }

    private static IEnumerable<(EnvironmentFeature Exit, int To)> SafeExits(Travel travel, int zone)
    {
        try { return travel.Exits(zone).ToList(); }
        catch (Exception e) when (e is IOException or InvalidDataException) { return Array.Empty<(EnvironmentFeature, int)>(); }
    }

    private static IReadOnlyList<EnvironmentFeature> SafeFeatures(Travel travel, int zone)
    {
        try { return travel.Features(zone); }
        catch (Exception e) when (e is IOException or InvalidDataException) { return Array.Empty<EnvironmentFeature>(); }
    }
}
