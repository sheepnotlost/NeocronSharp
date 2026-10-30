using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Travel to any sector (and optionally a place in it): walk to the zone exit that
/// leads toward the target sector, walk through it, wait for the next sector to
/// load, repeat. Sectors are linked only by the worlds' own WorldChange exits, and
/// only where the next sector has an exit back (one-way records are usually
/// apartment doors or lifts that need "use", which a walk cannot do). A blocked
/// exit is remembered and avoided, and every crossing is logged to learn from.
/// </summary>
internal sealed partial class Travel(string install, Func<int, NavWorld> bake, Hud hud, string logDirectory, int pulse, bool run)
{
    /// <summary>The traversal folder (arrows.json, rotations.json, arrows.py); tests point it elsewhere.</summary>
    public static string Home { get; set; } = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, @"..\..\.."));

    public const string Arrive = "arrive";
    public const int Subway = 1000;
    private readonly EnvironmentCatalog _catalog = new(install);
    private readonly Dictionary<int, EnvironmentSummary> _summaries = new();
    private readonly HashSet<(int Sector, string Exit)> _blocked = LoadBlocked(logDirectory);
    private readonly Dictionary<int, List<Arrow>> _arrows = LoadArrows();
    private readonly Dictionary<int, int> _rotations = LoadRotations();

    /// <summary>Map rotations worked out offline by rotations.py (they matched all five compass readings seen live).</summary>
    private static Dictionary<int, int> LoadRotations()
    {
        string file = Path.Combine(Home, "rotations.json");
        var map = new Dictionary<int, int>();
        if (!File.Exists(file)) return map;
        using var doc = JsonDocument.Parse(File.ReadAllText(file));
        foreach (var sector in doc.RootElement.EnumerateObject())
            map[int.Parse(sector.Name)] = sector.Value.GetProperty("rotation").GetInt32();
        return map;
    }

    /// <summary>The live compass rotation, or the pre-solved one for this sector.</summary>
    public int? RotationFor(int sector, int? live) => live ?? (_rotations.TryGetValue(sector, out int r) ? r : null);
    private bool _learnedLoaded;
    private readonly Dictionary<int, List<System.Numerics.Vector3>> _obstacles = LoadObstacles(logDirectory);
    private readonly Dictionary<int, (int Count, NavWorld Nav)> _withObstacles = new();

    /// <summary>The sector's navmesh, with any props found blocking it cut out.</summary>
    private NavWorld Nav(int sector)
    {
        if (!_obstacles.TryGetValue(sector, out var spots) || spots.Count == 0) return bake(sector);
        if (_withObstacles.TryGetValue(sector, out var cached) && cached.Count == spots.Count) return cached.Nav;
        var nav = NavWorld.Bake(install, sector, obstacles: spots);
        Console.WriteLine($"Rebuilt {SectorName(sector)}'s map around {spots.Count} known obstacle(s) in {nav.BakeTime.TotalSeconds:F1}s.");
        _withObstacles[sector] = (spots.Count, nav);
        return nav;
    }

    private readonly Dictionary<(int, int), List<Arrow>> _liveArrows = new();

    /// <summary>
    /// The sector map's arrows at the live map rotation. Each sector's map is rotated its own
    /// way (Pepper Park differs from Plaza), so arrows placed with a fixed rotation land in
    /// the wrong place. Computed by arrows.py (mapplan) and cached in logs/.
    /// </summary>
    private List<Arrow> LiveArrows(int sector, int rotation)
    {
        if (_liveArrows.TryGetValue((sector, rotation), out var known)) return known;
        string cache = Path.Combine(logDirectory, $"arrows-{sector}-{rotation}.json");
        string json = File.Exists(cache) ? File.ReadAllText(cache) : "";
        if (json.Length == 0)
        {
            string traversal = Home;
            var start = new ProcessStartInfo(Path.Combine(traversal, @"..\runtime\python.exe"), $"\"{Path.Combine(traversal, "arrows.py")}\" --one {sector}:{rotation}")
            { RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = traversal };
            try
            {
                using var process = Process.Start(start)!;
                json = process.StandardOutput.ReadToEnd().Trim();
                process.WaitForExit(30000);
                if (json.StartsWith('[')) File.WriteAllText(cache, json);
            }
            catch (Exception e) when (e is System.ComponentModel.Win32Exception or IOException) { json = ""; }
        }
        var list = new List<Arrow>();
        if (json.StartsWith('['))
        {
            using var doc = JsonDocument.Parse(json);
            list = doc.RootElement.EnumerateArray().Select(a => new Arrow(a.GetProperty("label").GetString() ?? "",
                a.GetProperty("x").GetSingle(), a.GetProperty("z").GetSingle(), a.GetProperty("bx").GetSingle(), a.GetProperty("bz").GetSingle())).ToList();
        }
        Console.WriteLine($"  sector map of {SectorName(sector)} at rotation {rotation}: {list.Count} zone-line arrows");
        return _liveArrows[(sector, rotation)] = list;
    }

    private string ObstaclesFile => Path.Combine(logDirectory, "traversal-obstacles.txt");

    private void AddObstacle(int sector, System.Numerics.Vector3 spot)
    {
        if (!_obstacles.TryGetValue(sector, out var spots)) _obstacles[sector] = spots = new();
        spots.Add(spot);
        try { File.AppendAllText(ObstaclesFile, FormattableString.Invariant($"{sector}\t{spot.X:F0}\t{spot.Y:F0}\t{spot.Z:F0}\n")); } catch (IOException) { }
    }

    private static Dictionary<int, List<System.Numerics.Vector3>> LoadObstacles(string directory)
    {
        var map = new Dictionary<int, List<System.Numerics.Vector3>>();
        string file = Path.Combine(directory, "traversal-obstacles.txt");
        if (!File.Exists(file)) return map;
        foreach (var line in File.ReadAllLines(file))
        {
            var p = line.Split('\t');
            if (p.Length < 4 || !int.TryParse(p[0], out int sector)) continue;
            var v = new System.Numerics.Vector3(float.Parse(p[1], System.Globalization.CultureInfo.InvariantCulture),
                float.Parse(p[2], System.Globalization.CultureInfo.InvariantCulture), float.Parse(p[3], System.Globalization.CultureInfo.InvariantCulture));
            if (!map.TryGetValue(sector, out var list)) map[sector] = list = new();
            list.Add(v);
        }
        return map;
    }

    /// <summary>A zone-line arrow from the in-game sector map (traversal/arrows.json, made by arrows.py).</summary>
    public sealed record Arrow(string Label, float X, float Z, float BeyondX, float BeyondZ);

    private static Dictionary<int, List<Arrow>> LoadArrows()
    {
        string file = Path.Combine(Home, "arrows.json");
        var map = new Dictionary<int, List<Arrow>>();
        if (!File.Exists(file)) return map;
        using var doc = JsonDocument.Parse(File.ReadAllText(file));
        foreach (var sector in doc.RootElement.EnumerateObject())
            map[int.Parse(sector.Name)] = sector.Value.EnumerateArray().Select(a => new Arrow(a.GetProperty("label").GetString() ?? "",
                a.GetProperty("x").GetSingle(), a.GetProperty("z").GetSingle(), a.GetProperty("bx").GetSingle(), a.GetProperty("bz").GetSingle())).ToList();
        return map;
    }

    /// <summary>
    /// Where to walk for an exit, and where to push through. A WorldChange's own position is
    /// the arrival spot for people coming the other way, not the line; the nearest arrow on
    /// the sector map marks the line and the way through it. Without a map (interiors), the
    /// exit's own position is used, pushing on past it.
    /// </summary>
    public (System.Numerics.Vector3 Walk, System.Numerics.Vector3? Push, (int, int, int)? Key) LineFor(int sector, EnvironmentFeature exit, int? rotation, int toSector,
        System.Numerics.Vector3? sectorCentre = null, NavWorld? nav = null)
    {
        // Self-learned: where a past walk actually zoned from this sector into that one.
        if (_crossings.TryGetValue((sector, toSector), out var crossed))
        {
            var heading = System.Numerics.Vector3.Normalize(new(crossed.Forward.X, 0, crossed.Forward.Z));
            return (crossed.Position - heading * 120, crossed.Position + heading * 400, null);
        }
        // Down into the subway from a street: the door's record is only where people coming out appear,
        // on the landing of the station stairs. Walk on down to the room at the bottom and press on.
        if (toSector == Subway && sector != Subway && nav != null && SubwayEntrance(nav, exit.Position) is { } stairs)
            return (stairs.Walk, stairs.Push, null);
        // A door (into or out of a building, sewer, club or the subway): sector-map arrows mark
        // only street-to-street lines. Walk to the door itself and on through it (right-clicking
        // it open if it stops the walk: see IsDoorLeg).
        if (IsDoorLeg(sector, toSector)) return (exit.Position, null, null);
        var arrows = rotation is int r ? LiveArrows(sector, r) : _arrows.GetValueOrDefault(sector);
        if (arrows == null || arrows.Count == 0)
        {
            // No readable arrows (interiors; Industrial and Outzone maps are drawn in a style the
            // map reader cannot parse). An exit record marks where people arrive, just inside the
            // sector's edge, so push on outward, away from the sector's centre. A crossing found
            // this way is learned and used directly next time. (Industrial and Outzone maps are
            // wireframe blueprints with no exit arrows at all: there is nothing more to read.)
            if (sectorCentre is not { } c) return (exit.Position, null, null);
            var outward = new System.Numerics.Vector2(exit.Position.X - c.X, exit.Position.Z - c.Z);
            if (outward.LengthSquared() < 1) return (exit.Position, null, null);
            outward = System.Numerics.Vector2.Normalize(outward);
            return (exit.Position, new(exit.Position.X + outward.X * 1500, exit.Position.Y, exit.Position.Z + outward.Y * 1500), null);
        }
        var p = exit.Position;
        // Which sector an arrow leads to is not written anywhere: it is learned from crossings.
        // Known-good arrows first, then untried ones nearest the exit record; never one known
        // to lead elsewhere or to do nothing.
        var best = arrows.Select(a => (Arrow: a, Key: ArrowKey(sector, a)))
            .Where(a => !_deadArrows.Contains(a.Key) && (!_arrowLeadsTo.TryGetValue(a.Key, out int to) || to == toSector))
            .OrderBy(a => _arrowLeadsTo.ContainsKey(a.Key) ? 0 : 1)
            .ThenBy(a => (a.Arrow.X - p.X) * (a.Arrow.X - p.X) + (a.Arrow.Z - p.Z) * (a.Arrow.Z - p.Z))
            .Select(a => ((Arrow, (int, int, int))?)a).FirstOrDefault();
        if (best is not { } chosen) return (default, null, null);   // every arrow ruled out
        var (arrow, key) = chosen;
        var walk = new System.Numerics.Vector3(arrow.X, p.Y, arrow.Z);
        var through = new System.Numerics.Vector2(arrow.BeyondX - arrow.X, arrow.BeyondZ - arrow.Z);
        if (through.LengthSquared() < 1) return (walk, null, key);
        through = System.Numerics.Vector2.Normalize(through);
        // Past the arrow's "beyond" point and on: the halt while the next zone loads stops us anyway.
        var push = new System.Numerics.Vector3(arrow.BeyondX + through.X * 400, p.Y, arrow.BeyondZ + through.Y * 400);
        // Every crossing seen live zoned 50-410 units from that link's exit record. An arrow whose
        // push passes nowhere near one (Plaza 2 -> 1, Pepper Park 2 -> 3 in the morning video)
        // pressed into walls: push on from the exit record along the floor instead. That attempt
        // has its own key, so if it does not zone it is not tried again and the arrow is used.
        if (nav != null && Exits(sector).Where(e => e.To == toSector)
                .All(e => DistanceToSegment(e.Exit.Position, walk, push) > FarFromRecord))
        {
            var recordKey = (sector, (int)MathF.Round(p.X / 100), (int)MathF.Round(p.Z / 100));
            if (!_deadArrows.Contains(recordKey) && PastRecord(nav, p) is { } past)
            {
                _recordKeys.Add(recordKey);
                return (past.Walk, past.Push, recordKey);
            }
        }
        return (walk, push, key);
    }

    private readonly HashSet<(int, int, int)> _recordKeys = new();

    /// <summary>True when LineFor chose the floor past an exit record over a far-off arrow.</summary>
    public bool IsPastRecord((int, int, int)? key) => key is { } k && _recordKeys.Contains(k);

    /// <summary>How far an arrow's push may pass from every exit record before the record is used instead.</summary>
    public const float FarFromRecord = 450;

    /// <summary>
    /// Where the floor leads on past an exit record: of the corridor tips reachable within a
    /// short walk of it, the one nearest the sector's outer edge (zone lines sit at the edge).
    /// </summary>
    public static (System.Numerics.Vector3 Walk, System.Numerics.Vector3 Push)? PastRecord(NavWorld nav, System.Numerics.Vector3 record)
    {
        if (!nav.Snap(record, out _, out var start, wide: true)) return null;
        var verts = nav.World.StaticGeometry.Vertices;
        float minX = verts.Min(v => v.X), maxX = verts.Max(v => v.X), minZ = verts.Min(v => v.Z), maxZ = verts.Max(v => v.Z);
        float ToEdge(System.Numerics.Vector3 v) => Math.Min(Math.Min(v.X - minX, maxX - v.X), Math.Min(v.Z - minZ, maxZ - v.Z));
        List<System.Numerics.Vector3>? best = null; float bestEdge = float.MaxValue;
        for (int i = 0; i < 16; i++)
        {
            float a = i * MathF.PI / 8;
            var corridor = nav.RouteToward(start, start + new System.Numerics.Vector3(MathF.Cos(a), 0, MathF.Sin(a)) * 1500);
            if (corridor.Count < 2) continue;
            float length = new RouteFollower(corridor).Total;
            if (length < 80 || length > 1200) continue;   // a corridor near the record, not the open street
            float edge = ToEdge(corridor[^1]);
            if (edge < bestEdge) { bestEdge = edge; best = corridor; }
        }
        if (best == null) return null;
        var tip = best[^1];
        var on = new System.Numerics.Vector2(tip.X - best[^2].X, tip.Z - best[^2].Z);
        on = on.LengthSquared() < 1 ? System.Numerics.Vector2.Zero : System.Numerics.Vector2.Normalize(on);
        return (start, new(tip.X + on.X * 400, tip.Y, tip.Z + on.Y * 400));
    }

    private static float DistanceToSegment(System.Numerics.Vector3 p, System.Numerics.Vector3 a, System.Numerics.Vector3 b)
    {
        System.Numerics.Vector2 pa = new(p.X - a.X, p.Z - a.Z), ab = new(b.X - a.X, b.Z - a.Z);
        float t = ab.LengthSquared() < 1e-4f ? 0 : Math.Clamp(System.Numerics.Vector2.Dot(pa, ab) / ab.LengthSquared(), 0, 1);
        return (pa - ab * t).Length();
    }

    /// <summary>True when a past trip learned exactly where this crossing zones.</summary>
    public bool HasLearnedCrossing(int from, int to) => _crossings.ContainsKey((from, to));

    /// <summary>Sectors with an in-game sector map: streets. Interiors (arenas, HQs, clubs) have none.</summary>
    public bool HasMap(int sector) => _arrows.ContainsKey(sector);

    private static (int, int, int) ArrowKey(int sector, Arrow a) => (sector, (int)MathF.Round(a.X / 100), (int)MathF.Round(a.Z / 100));

    private readonly Dictionary<(int From, int To), (System.Numerics.Vector3 Position, System.Numerics.Vector3 Forward)> _crossings = new();
    private string CrossingsFile => Path.Combine(logDirectory, "traversal-crossings.txt");

    /// <summary>Remember the exact spot and heading where the zone changed, for next time.</summary>
    private void LearnCrossing(int from, int to, System.Numerics.Vector3 position, System.Numerics.Vector3 forward)
    {
        _crossings[(from, to)] = (position, forward);
        try { File.AppendAllText(CrossingsFile, FormattableString.Invariant($"{from}\t{to}\t{position.X:F0}\t{position.Y:F0}\t{position.Z:F0}\t{forward.X:F3}\t{forward.Z:F3}\n")); } catch (IOException) { }
        Console.WriteLine($"  learned: {SectorName(from)} -> {SectorName(to)} zones at {position.X:F0},{position.Z:F0}");
    }

    private void ForgetCrossing(int from, int to)
    {
        if (!_crossings.Remove((from, to))) return;
        try { File.AppendAllText(CrossingsFile, $"{from}\t{to}\tforget\n"); } catch (IOException) { }
        Console.WriteLine($"  forgot the learned crossing {SectorName(from)} -> {SectorName(to)}: it did not zone this time");
    }

    private void LoadCrossings()
    {
        if (!File.Exists(CrossingsFile)) return;
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        foreach (var line in File.ReadAllLines(CrossingsFile))
        {
            var f = line.Split('\t');
            if (f.Length < 3 || !int.TryParse(f[0], out int from) || !int.TryParse(f[1], out int to)) continue;
            if (f[2] == "forget") { _crossings.Remove((from, to)); continue; }
            if (f.Length < 7) continue;
            _crossings[(from, to)] = (new(float.Parse(f[2], inv), float.Parse(f[3], inv), float.Parse(f[4], inv)), new(float.Parse(f[5], inv), 0, float.Parse(f[6], inv)));
        }
    }

    private readonly Dictionary<(int, int, int), int> _arrowLeadsTo = new();
    private readonly HashSet<(int, int, int)> _deadArrows = new();
    private string ArrowsLearnedFile => Path.Combine(logDirectory, "traversal-arrows.txt");

    private void LearnArrow((int Sector, int X, int Z) key, int to)
    {
        if (to <= 0) _deadArrows.Add(key); else _arrowLeadsTo[key] = to;
        try { File.AppendAllText(ArrowsLearnedFile, $"{key.Sector}\t{key.X}\t{key.Z}\t{to}\n"); } catch (IOException) { }
        Console.WriteLine(to <= 0 ? $"  learned: that zone-line arrow in {SectorName(key.Sector)} does not zone"
                                  : $"  learned: that zone-line arrow in {SectorName(key.Sector)} leads to {SectorName(to)}");
    }

    private void LoadLearnedArrows()
    {
        if (!File.Exists(ArrowsLearnedFile)) return;
        foreach (var line in File.ReadAllLines(ArrowsLearnedFile))
        {
            var f = line.Split('\t');
            if (f.Length < 4 || !int.TryParse(f[0], out int sector) || !int.TryParse(f[1], out int x) || !int.TryParse(f[2], out int z) || !int.TryParse(f[3], out int to)) continue;
            if (to <= 0) _deadArrows.Add((sector, x, z)); else { _arrowLeadsTo[(sector, x, z)] = to; _deadArrows.Remove((sector, x, z)); }
        }
    }

    public string SectorName(int id) => _catalog.Areas.FirstOrDefault(a => a.WorldId == id)?.Name ?? $"sector {id}";
    public IReadOnlyList<EnvironmentArea> Areas => _catalog.Areas;

    private EnvironmentSummary Summary(int id)
    {
        lock (_summaries)
        {
            if (!_summaries.TryGetValue(id, out var summary)) _summaries[id] = summary = _catalog.Load(id).Summary;
            return summary;
        }
    }

    /// <summary>Ground points and exits authored in a sector's world file (no navmesh needed).</summary>
    public IReadOnlyList<EnvironmentFeature> Features(int sector) => Summary(sector).Features;

    /// <summary>Exits leaving <paramref name="sector"/> and the sector each one leads to.</summary>
    // An exit names its arrival point in the next sector (NextLevelStartIndex, matching the
    // Index of the exit you arrive by). Index 0 means none: a placeholder, not a zone line.
    public IEnumerable<(EnvironmentFeature Exit, int To)> Exits(int sector) =>
        Summary(sector).Features.Where(f => f.Kind == "WorldChange" &&
                int.TryParse(f.Properties.GetValueOrDefault("NextLevelStartIndex"), out int start) && start > 0)
            .Select(f => (f, int.TryParse(f.Properties.GetValueOrDefault("NextLevel"), out int to) ? to : 0))
            .Where(e => e.Item2 > 0 && e.Item2 != sector);

    private IEnumerable<(EnvironmentFeature Exit, int To)> SafeExits(int sector)
    {
        try { return Exits(sector).ToList(); }
        catch (Exception e) when (e is IOException or InvalidDataException) { return Array.Empty<(EnvironmentFeature, int)>(); }
    }

    /// <summary>
    /// Every way out of <paramref name="sector"/>: its exits, plus the doors the game routes itself
    /// (sewers, cellars, clubs, apartment blocks have no arrival point on this side). Such a door
    /// is found from the far side: a world whose exit arrives at this door's Index is behind it.
    /// Last, doors that are placed objects in the sector's spawn file (<see cref="ObjectDoors"/>),
    /// to places no WorldChange leads to.
    /// </summary>
    public IEnumerable<(EnvironmentFeature Exit, int To)> Links(int sector)
    {
        var direct = SafeExits(sector).ToList();
        foreach (var link in direct) yield return link;
        var inbound = Inbound();
        var linked = direct.Select(d => d.To).ToHashSet();
        IReadOnlyList<EnvironmentFeature> features;
        try { features = Features(sector); } catch (Exception e) when (e is IOException or InvalidDataException) { features = Array.Empty<EnvironmentFeature>(); }
        foreach (var door in features.Where(f => f.Kind == "WorldChange"))
            if (door.Properties.GetValueOrDefault("Index") is { } index && inbound.TryGetValue((sector, index), out var from))
                foreach (int to in from.Where(t => t != sector && !direct.Any(d => d.Exit.Name == door.Name && d.To == t)))
                {
                    linked.Add(to);
                    yield return (door, to);
                }
        if (ObjectDoors().TryGetValue(sector, out var objects))
            foreach (var (door, to) in objects.Where(o => !linked.Contains(o.To)))
                yield return (door, to);
    }

    /// <summary>Sectors with an exit, game-routed door or door object into <paramref name="world"/> (whether or not they lead back).</summary>
    public IEnumerable<int> DoorsInto(int world) =>
        Inbound().Where(i => i.Key.Sector == world).SelectMany(i => i.Value)
            .Concat(ObjectDoors().Where(d => d.Value.Any(v => v.To == world)).Select(d => d.Key))
            .Where(s => s != world).Distinct();

    /// <summary>Kind of the <see cref="EnvironmentFeature"/>s <see cref="ObjectDoors"/> makes: a door that is a placed object, not a WorldChange.</summary>
    public const string ObjectDoor = "ObjectDoor";

    private Dictionary<int, List<(EnvironmentFeature Door, int To)>>? _objectDoors;

    /// <summary>
    /// Doors that are placed objects (apartment-complex entrances, Outzone side streets, sewers
    /// and storage, Jones mission places, clubs). The game routes them itself: such an object's
    /// pak_worldmodels row (Type 20 "Entrance" or 18 "Sewer entrance") has Value = a pak_appplaces
    /// EntryId, whose ExitWorldId is the world it leads into. Its exit is the next row (EntryId + 1,
    /// "... EXIT"), naming the street you come back out to. Inside, the exit is the object whose
    /// Value is that row; else the "Underground exit" (Type 29, which returns you the way you
    /// came); else the place's one exit object (dungeons copied from the Dome of York keep the
    /// DoY exit in the client's file; the server sends you back by the pair). Built from every
    /// sector's spawn file in about a second; never street to street (those are zone lines).
    /// </summary>
    public Dictionary<int, List<(EnvironmentFeature Door, int To)>> ObjectDoors()
    {
        if (_objectDoors != null) return _objectDoors;
        var doors = new Dictionary<int, List<(EnvironmentFeature Door, int To)>>();
        Dictionary<int, Dictionary<string, string>> models, places;
        try
        {
            models = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_worldmodels.csv")));
            places = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_appplaces.csv")));
        }
        catch (Exception e) when (e is IOException or InvalidDataException or UnauthorizedAccessException) { return _objectDoors = doors; }
        static int Int(Dictionary<string, string> row, string field) => int.TryParse(row.GetValueOrDefault(field), out int n) ? n : 0;
        var worlds = Areas.Select(a => a.WorldId).ToHashSet();
        bool Known(int world) => world > 0 && world != Subway && worlds.Contains(world);
        // Every door object in every sector: (sector, record, model type, appplace, position, name).
        var objects = new WorldObjects(install, this);
        var all = new List<(int World, int Record, int Type, int Place, System.Numerics.Vector3 At, string Name)>();
        foreach (var area in Areas)
        {
            List<(int Record, int Model, System.Numerics.Vector3 At)> placed;
            try { placed = objects.Placed(area.WorldId).ToList(); }
            catch (Exception e) when (e is IOException or InvalidDataException or UnauthorizedAccessException) { continue; }
            foreach (var (record, model, at) in placed)
                if (models.TryGetValue(model, out var row) && Int(row, "Type") is 18 or 20 or 29)
                    all.Add((area.WorldId, record, Int(row, "Type"), Int(row, "Value"), at, (row.GetValueOrDefault("Name") ?? "").Replace("\\n", " ").Replace("\n", " ")));
        }
        EnvironmentFeature Feature((int World, int Record, int Type, int Place, System.Numerics.Vector3 At, string Name) o, int to, string how) =>
            new(ObjectDoor, $"Door{o.Record}", o.At, new Dictionary<string, string>
            {
                ["classname"] = ObjectDoor, ["Label"] = o.Name, ["AppPlace"] = o.Place.ToString(), ["NextLevel"] = to.ToString(), ["How"] = how,
            });
        void Add(int from, EnvironmentFeature door, int to)
        {
            if (!doors.TryGetValue(from, out var list)) doors[from] = list = new();
            if (!list.Any(l => l.Door.Name == door.Name && l.To == to)) list.Add((door, to));
        }
        bool StreetToStreet(int a, int b) => IsStreet(a) && IsStreet(b);
        // Doors whose pak_appplaces row is not the exit back (used to pick an exit by elimination).
        var used = new HashSet<(int World, int Record)>();
        var entrances = new List<(int From, int To, int Exit)>();
        foreach (var o in all.Where(o => o.Type != 29 && places.TryGetValue(o.Place, out var p) && p.GetValueOrDefault("Enabled") != "0"))
        {
            int to = Int(places[o.Place], "ExitWorldId");
            if (to == o.World || !Known(to) || !Known(o.World) || StreetToStreet(o.World, to)) continue;
            // The client's file says where this object leads. Exit objects copied with a dungeon map
            // (a DoY exit inside an Outzone side street) are re-pointed below, from the pair.
            Add(o.World, Feature(o, to, "object"), to);
            // An entrance: its pair (EntryId + 1) is the exit back out to this sector.
            if (places.TryGetValue(o.Place + 1, out var pair) && Int(pair, "ExitWorldId") == o.World && pair.GetValueOrDefault("Enabled") != "0")
                entrances.Add((o.World, to, o.Place + 1));
        }
        foreach (var group in entrances.Distinct().GroupBy(e => e.To))
        {
            var inside = all.Where(o => o.World == group.Key).ToList();
            foreach (var (from, to, exit) in group)
            {
                // Already linked back by an object the client's file points there?
                if (doors.TryGetValue(to, out var back) && back.Any(b => b.To == from)) continue;
                var door = inside.FirstOrDefault(o => o.Place == exit && o.Type != 29);
                if (door.Name == null) door = inside.FirstOrDefault(o => o.Type == 29);
                // The place's one exit object, when this is the only way in that needs one.
                if (door.Name == null && group.Count() == 1)
                {
                    var exits = inside.Where(o => o.Type == 20 && places.TryGetValue(o.Place, out var p) && Int(p, "ExitWorldId") != to
                        && (p.GetValueOrDefault("Description") ?? "").Contains("exit", StringComparison.OrdinalIgnoreCase)).ToList();
                    if (exits.Count == 1)
                    {
                        door = exits[0];
                        // It does not lead where the client's file says: drop that link.
                        int stale = Int(places[door.Place], "ExitWorldId");
                        if (doors.TryGetValue(to, out var copied)) copied.RemoveAll(d => d.Door.Name == $"Door{door.Record}" && d.To == stale);
                    }
                }
                if (door.Name != null) { Add(to, Feature(door, from, door.Place == exit ? "object" : $"pair {exit}"), from); continue; }
                // No exit object in the client's files (Jones mission places, Outzone water
                // treatment: no spawn file at all). You arrive beside the exit, at the place's
                // start point: an approximate door spot, only walked when starting from inside.
                EnvironmentFeature? start = null;
                try { start = Features(to).FirstOrDefault(f => f.Kind == "DeathMatchStart"); }
                catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException) { }
                if (start != null && group.Count() == 1)
                    Add(to, new(ObjectDoor, "ArrivalDoor", start.Position, new Dictionary<string, string>
                    {
                        ["classname"] = ObjectDoor, ["Label"] = "exit (at the arrival point)", ["AppPlace"] = exit.ToString(), ["NextLevel"] = from.ToString(), ["How"] = $"pair {exit}, at the arrival point",
                    }), from);
            }
        }
        return _objectDoors = doors;
    }

    private Dictionary<(int Sector, string Index), List<int>>? _inbound;

    /// <summary>
    /// (sector, door Index) -> the worlds whose exits arrive at that door. Built from every world's
    /// exits (about 20 s), then kept in logs/door-graph.txt until the game's world files change.
    /// </summary>
    private Dictionary<(int Sector, string Index), List<int>> Inbound()
    {
        if (_inbound != null) return _inbound;
        string file = Path.Combine(logDirectory, "door-graph.txt"), stamp = WorldFilesStamp();
        var rows = new List<(int From, int To, string Index)>();
        if (File.Exists(file) && File.ReadLines(file).FirstOrDefault() == stamp)
            foreach (var f in File.ReadLines(file).Skip(1).Select(l => l.Split('\t')).Where(f => f.Length == 3))
                rows.Add((int.Parse(f[0]), int.Parse(f[1]), f[2]));
        else
        {
            foreach (var area in Areas)
                foreach (var (exit, to) in SafeExits(area.WorldId))
                    rows.Add((area.WorldId, to, exit.Properties["NextLevelStartIndex"]));
            try { File.WriteAllLines(file, rows.Select(r => $"{r.From}\t{r.To}\t{r.Index}").Prepend(stamp)); } catch (IOException) { }
        }
        return _inbound = rows.GroupBy(r => (r.To, r.Index)).ToDictionary(g => g.Key, g => g.Select(r => r.From).Distinct().ToList());
    }

    // Size and time of the files the worlds come from: a game update changes it.
    private string WorldFilesStamp()
    {
        var files = new[] { "worlds.pak", Path.Combine("worlds", "pak_worlds.ini"), Path.Combine("definitions", "pak_worldinfo.csv") }
            .Select(f => new FileInfo(Path.Combine(install, f))).Where(f => f.Exists).ToList();
        string worlds = Path.Combine(install, "worlds");
        var loose = Directory.Exists(worlds) ? Directory.EnumerateFiles(worlds, "*.bsp", SearchOption.AllDirectories).Select(f => new FileInfo(f)).ToList() : new();
        return "v3 " + string.Join(" ", files.Select(f => $"{f.Length}:{f.LastWriteTimeUtc.Ticks}")) +
            $" {loose.Count}:{(loose.Count == 0 ? 0 : loose.Max(f => f.LastWriteTimeUtc.Ticks))}";
    }

    /// <summary>True for a street sector (a zone with a sector map, not the subway): the rest are interiors.</summary>
    public bool IsStreet(int sector) => sector != Subway && HasMap(sector);

    /// <summary>A leg that goes through a door rather than a street zone line: either side is an interior.</summary>
    public bool IsDoorLeg(int from, int to) => !IsStreet(from) || !IsStreet(to);

    /// <summary>Walkable links: a way from a to b that is not known blocked, where b has a way back to a.</summary>
    /// Wasteland cells link by their placed doors and across their edges (<see cref="TerrainLinks"/>).
    public IEnumerable<int> Neighbours(int sector) =>
        AllLinks(sector).Where(e => !_blocked.Contains((sector, e.Exit.Name))).Select(e => e.To).Distinct()
            .Where(to => AllLinks(to).Any(back => back.To == sector));

    // How far a trip may pass through buildings, sewers and other interiors to reach a place.
    private const int MaxInteriorHops = 20;

    /// <summary>
    /// Every sector a trip from <paramref name="start"/> can reach, with its zone-line count:
    /// the same reach as <see cref="SectorPath"/>. Streets first (at most 12 lines, never
    /// through the subway); then places only reachable through interiors (doors, sewers).
    /// </summary>
    public Dictionary<int, int> Reach(int start, int maxHops = 12)
    {
        if (_reach.TryGetValue((start, maxHops), out var known)) return new(known);
        var hops = Search(start, maxHops, interiors: false);
        foreach (var (sector, count) in Search(start, MaxInteriorHops, interiors: true)) hops.TryAdd(sector, count);
        // Last, across the wasteland: its cells, and the places whose doors stand in it.
        if (hops.Keys.Any(TouchesWasteland))
            foreach (var (sector, count) in WastelandReach(start, hops)) hops.TryAdd(sector, count);
        _reach[(start, maxHops)] = hops;
        return new(hops);
    }

    private readonly Dictionary<(int Start, int MaxHops), Dictionary<int, int>> _reach = new();

    private Dictionary<int, int> Search(int start, int maxHops, bool interiors)
    {
        var hops = new Dictionary<int, int> { [start] = 0 }; var queue = new Queue<int>(new[] { start });
        while (queue.Count > 0)
        {
            int s0 = queue.Dequeue();
            if (hops[s0] >= maxHops || (s0 != start && !PassesThrough(s0, interiors))) continue;
            foreach (int n in Neighbours(s0)) if (hops.TryAdd(n, hops[s0] + 1)) queue.Enqueue(n);
        }
        return hops;
    }

    // The subway's stations are joined by trains, not floor: never a way through. Interiors
    // (no sector map: buildings, clubs, sewers) only when no street-only way exists.
    // Wasteland cells are planned on their own walking grid (WastelandPath), never by hop count.
    private bool PassesThrough(int sector, bool interiors) => sector != Subway && !IsTerrain(sector) && (interiors || HasMap(sector));

    /// <summary>Street sectors (with a sector map) reachable from <paramref name="start"/>, nearest first; start included.</summary>
    public List<int> Streets(int start) =>
        Reach(start).Where(h => h.Key == start || HasMap(h.Key)).OrderBy(h => h.Value).ThenBy(h => SectorName(h.Key)).Select(h => h.Key).ToList();

    /// <summary>
    /// Sector-to-sector path by breadth-first search over walkable links; empty if none.
    /// Streets only when that works; through interiors (doors, sewers) only when it must.
    /// </summary>
    public List<int> SectorPath(int from, int to, int maxHops = 12) => SectorPath(from, to, maxHops, at: null);

    /// <param name="at">Where you stand in <paramref name="from"/>, when known: in a wasteland cell (cells are big, and split by
    /// mountains), its cell-space position; in the city, it times the walk to each exit (whether the subway is quicker).</param>
    public List<int> SectorPath(int from, int to, int maxHops, System.Numerics.Vector3? at)
    {
        // Out in the wasteland, or the city ways fail: plan across the wasteland's walking grid.
        if (IsTerrain(from)) return WastelandPlan(from, to, at)?.Sectors ?? new();
        var path = SectorPath(from, to, maxHops, interiors: false);
        if (path.Count == 0) path = SectorPath(from, to, MaxInteriorHops, interiors: true);
        if (path.Count == 0) path = WastelandPlan(from, to, at)?.Sectors ?? new();
        else path = PreferSubway(from, to, path, at);   // a long way round may be quicker by train (Subway.cs)
        return path;
    }

    private List<int> SectorPath(int from, int to, int maxHops, bool interiors)
    {
        var previous = new Dictionary<int, int> { [from] = from };
        var frontier = new List<int> { from };
        for (int hop = 0; hop < maxHops && frontier.Count > 0 && !previous.ContainsKey(to); hop++)
        {
            var next = new List<int>();
            foreach (int sector in frontier)
            {
                if (sector != from && !PassesThrough(sector, interiors)) continue;
                foreach (int n in Neighbours(sector))
                    if (previous.TryAdd(n, sector)) next.Add(n);
            }
            frontier = next;
        }
        if (!previous.ContainsKey(to)) return new();
        var path = new List<int> { to };
        while (path[^1] != from) path.Add(previous[path[^1]]);
        path.Reverse();
        return path;
    }

    /// <summary>Go to <paramref name="targetSector"/>; then to <paramref name="targetSpec"/> in it, or stop on arrival for <see cref="Arrive"/>.</summary>
    /// <summary>Load what earlier trips learned (arrows, crossings); Go does this itself.</summary>
    public void LoadLearning()
    {
        if (!_learnedLoaded) { LoadLearnedArrows(); LoadCrossings(); _learnedLoaded = true; }
    }

    public void Go(PlayerReader reader, int targetSector, string targetSpec, string label)
    {
        LoadLearning();
        FocusGame(reader.Window);
        bool first = true;
        int failures = 0;
        LiveSteer.Calibration? calibration = null;
        int obstaclesThisLeg = 0, lastSector = -1;
        // A trip into the wasteland crosses a cell edge every few minutes: allow more legs than a city trip needs.
        for (int leg = 0; leg < 80; leg++)
        {
            var sample = reader.ReadSteady();
            int here = reader.ReadSectorId(sample.World) ?? throw new InvalidOperationException("Still zoning.");
            if (here != lastSector) { obstaclesThisLeg = 0; lastSector = here; }
            if (here == targetSector && targetSpec == Arrive)
            {
                Console.WriteLine($"Arrived in {SectorName(here)}.");
                hud.Post(Hud.Green, $"TRAVERSAL  arrived in {SectorName(here)}", "Done.");
                return;
            }
            var nav = Nav(here);
            string log = Path.Combine(logDirectory, $"steer-{DateTime.UtcNow:yyyyMMdd-HHmmss}-leg{leg + 1}.jsonl");
            if (here == targetSector)
            {
                var (target, _, wide) = nav.Target(targetSpec);
                // A door: any exit here that is not a zone line into another street (buildings,
                // clubs, HQs, the subway, sewers, apartments; many have no arrival point, the game
                // routes them itself). Walk up to it, right-click it open and go in. Done when the
                // game loads the place behind it.
                string? doorName = targetSpec.StartsWith("exit:", StringComparison.Ordinal) ? targetSpec[5..] : null;
                bool streetLine = doorName != null && Exits(here).Any(e => string.Equals(e.Exit.Name, doorName, StringComparison.OrdinalIgnoreCase) && e.To != Subway && HasMap(e.To));
                if (doorName != null && !streetLine)
                {
                    var feature = Features(here).First(f => f.Kind == "WorldChange" && string.Equals(f.Name, doorName, StringComparison.OrdinalIgnoreCase));
                    // With no arrival point (NextLevelStartIndex 0) NextLevel is a placeholder: the game decides.
                    int behind = int.TryParse(feature.Properties.GetValueOrDefault("NextLevelStartIndex"), out int arrival) && arrival > 0
                        && int.TryParse(feature.Properties.GetValueOrDefault("NextLevel"), out int n) && n != here ? n : 0;
                    Console.WriteLine($"In {SectorName(here)}: going in at {label}.");
                    var enter = new LiveSteer(reader, nav, here, target, wide, label, pulse, log, hud, run,
                        zoneExit: true, countdown: first, known: calibration, openDoor: true);
                    enter.Run();
                    if (!enter.Zoned) throw new InvalidOperationException("Reached the door without going in.");
                    int now = WaitForSector(reader, behind);
                    hud.Post(Hud.Green, $"TRAVERSAL  arrived in {SectorName(now)}", "Done.");
                    return;
                }
                Console.WriteLine($"In {SectorName(here)}: going to {label}.");
                // A position (a GenRep, a shop counter, an NPC): end on the nearest floor within
                // 200 units, since many stand behind counters or on furniture.
                if (targetSpec.Count(c => c == ',') == 2)
                {
                    var near = nav.RouteNear(reader.ReadSteady().Position, target, out bool reachable);
                    // RouteNear measures the miss on the ground plane; a CityCom on a balcony is not
                    // reached from the street under it, so check the height too.
                    if (!reachable || MathF.Abs(near[^1].Y - target.Y) > 150)
                        throw new InvalidOperationException($"No floor within 200 units of {label} can be walked to from here.");
                    target = near[^1]; wide = true;
                }
                new LiveSteer(reader, nav, here, target, wide, label, pulse, log, hud, run, countdown: first, known: calibration).Run();
                return;
            }
            // Out in the wasteland: walk to the next cell edge or door on the walking grid (TerrainTravel.cs).
            if (IsTerrain(here))
            {
                if (!WastelandLeg(reader, sample, here, targetSector, nav, log, leg, ref first, ref calibration, ref failures, ref obstaclesThisLeg)) leg--;
                continue;
            }
            // In the subway: ride the train first when the next door is in another station hall (Subway.cs).
            if (here == Subway && SubwayLeg(reader, sample, targetSector, nav, log, ref first, ref calibration)) continue;
            var path = here == Subway ? SubwayPath(sample.Position, targetSector, nav, out _, out _) : SectorPath(here, targetSector, 12, sample.Position);
            if (path.Count < 2) throw new InvalidOperationException($"No walkable chain of zone exits from {SectorName(here)} to {SectorName(targetSector)}.");
            int next = path[1];
            // Of the usable exits into the next sector, take the one with the shortest walk.
            int? rotation = RotationFor(here, reader.ReadMapRotation(sample.World));
            var bounds = nav.World.StaticGeometry.Vertices;
            var centre = new System.Numerics.Vector3((bounds.Min(v => v.X) + bounds.Max(v => v.X)) / 2, 0, (bounds.Min(v => v.Z) + bounds.Max(v => v.Z)) / 2);
            var choice = Links(here).Where(e => e.To == next && !_blocked.Contains((here, e.Exit.Name)))
                .Select(e => (e.Exit, Line: LineFor(here, e.Exit, rotation, next, centre, nav)))
                .Where(e => e.Line.Walk != default)
                .Select(e => (e.Exit, e.Line, Route: nav.RouteNear(sample.Position, e.Line.Walk, out bool ok), Ok: ok))
                .Select(e => (e.Exit, e.Line, Length: e.Route.Count > 1 && e.Ok ? new RouteFollower(e.Route).Total : float.MaxValue))
                .OrderBy(e => e.Length).FirstOrDefault();
            if (choice.Exit == null || choice.Length == float.MaxValue)
            {
                // Nothing walkable from here into that sector: forget those exits and plan around them.
                foreach (var e in Links(here).Where(e => e.To == next)) Block(here, e.Exit.Name, "no walkable route on the navmesh");
                if (++failures > 6) throw new InvalidOperationException($"No walkable route to any exit into {SectorName(next)}.");
                continue;
            }
            Console.WriteLine($"Leg {leg + 1}: {SectorName(here)} -> {SectorName(next)} via {choice.Exit.Name} ({choice.Length:F0} units). Plan: {string.Join(" -> ", path.Select(SectorName))}");
            var clock = Stopwatch.StartNew();
            bool doorLeg = IsDoorLeg(here, next);
            // A subway street entrance is stairs down to the station, not a door: right-click only when a door object stands there.
            bool openDoor = doorLeg && (next != Subway || DoorAt(nav, choice.Exit.Position, choice.Line.Walk));
            Console.WriteLine(next == Subway && choice.Line.Push is { } down
                ? $"  the subway: down the station stairs past the door record to {choice.Line.Walk.X:F0},{choice.Line.Walk.Y:F0},{choice.Line.Walk.Z:F0}, pressing on toward {down.X:F0},{down.Z:F0}{(openDoor ? "" : " (no door here: no right-click)")}"
                : choice.Line.Push is { } push
                ? $"  zone line at {choice.Line.Walk.X:F0},{choice.Line.Walk.Z:F0} ({(IsPastRecord(choice.Line.Key) ? "exit record; its arrow is far off" : "sector map")}), pushing through toward {push.X:F0},{push.Z:F0}"
                : doorLeg ? "  a door: walking to it and through (right-click opens it if it stops the walk)" : "  no sector-map arrow here: using the exit's own position");
            var steer = new LiveSteer(reader, nav, here, choice.Line.Walk, true, $"exit to {SectorName(next)}", pulse, log, hud, run,
                zoneExit: true, countdown: first, known: calibration, pushTo: choice.Line.Push, openDoor: openDoor);
            try { steer.Run(); }
            catch (LiveSteer.BlockedAt blocked) when (!steer.Zoned && obstaclesThisLeg < 5)
            {
                // A prop the level files do not show (box, barrel, crate): remember it just
                // ahead of where we stopped, rebuild this sector's map around it and go again.
                var spot = blocked.Position + System.Numerics.Vector3.Normalize(new(blocked.Forward.X, 0, blocked.Forward.Z)) * 36;
                AddObstacle(here, spot);
                obstaclesThisLeg++;
                Learn(here, choice.Exit.Name, next, false, clock.Elapsed.TotalSeconds, $"obstacle at {spot.X:F0},{spot.Z:F0}");
                Console.WriteLine($"Something is in the way at {spot.X:F0},{spot.Z:F0}; mapping it as an obstacle and going round.");
                first = false;
                calibration ??= steer.Measured;
                leg--;   // same leg again, on the updated map
                continue;
            }
            catch (InvalidOperationException e) when (!steer.Zoned && choice.Line.Key == null && _crossings.ContainsKey((here, next)) && e.Message.StartsWith("Walked through the exit", StringComparison.Ordinal))
            {
                ForgetCrossing(here, next);
                first = false;
                calibration ??= steer.Measured;
                leg--;
                continue;
            }
            catch (InvalidOperationException e) when (!steer.Zoned && choice.Line.Key is { } deadKey && e.Message.StartsWith("Walked through the exit", StringComparison.Ordinal))
            {
                // Pushed through this arrow and nothing happened: it is not this exit's line.
                LearnArrow(deadKey, 0);
                Learn(here, choice.Exit.Name, next, false, clock.Elapsed.TotalSeconds, "arrow did not zone");
                if (++failures > 8) throw;
                first = false;
                calibration ??= steer.Measured;
                leg--;
                continue;
            }
            catch (InvalidOperationException e) when (!steer.Zoned && IsRouteProblem(e.Message))
            {
                // Blocked door, lift or prop: avoid this exit and try another way.
                Learn(here, choice.Exit.Name, next, false, clock.Elapsed.TotalSeconds, e.Message);
                Block(here, choice.Exit.Name, e.Message);
                if (++failures > 6) throw;
                Console.WriteLine($"That exit failed ({e.Message}); trying another way.");
                first = false;
                calibration ??= steer.Measured;
                continue;
            }
            finally { calibration ??= steer.Measured; }
            if (!steer.Zoned) throw new InvalidOperationException("Reached the exit without zoning.");
            first = false;
            int arrived = WaitForSector(reader, next);
            Learn(here, choice.Exit.Name, arrived, arrived == next, clock.Elapsed.TotalSeconds, arrived == next ? null : $"arrived in {SectorName(arrived)}");
            if (arrived == next) Unblock(here, choice.Exit.Name);
            if (choice.Line.Key is { } usedKey && arrived != here) LearnArrow(usedKey, arrived);
            if (arrived != here && steer.CrossedAt is { } crossedAt) LearnCrossing(here, arrived, crossedAt.Position, crossedAt.Forward);
            if (arrived == here)
            {
                // Still in the same sector: the "zoning" was a misread (a stall or a lost
                // reading), not this exit leading back here. Never blame the exit for it.
                if (++failures > 6) throw new InvalidOperationException("Kept detecting a zone change that did not happen.");
                Console.WriteLine("No zone change happened after all; carrying on.");
            }
            else if (arrived != next && choice.Line.Key == null) Block(here, choice.Exit.Name, $"leads to {SectorName(arrived)}, not {SectorName(next)}");
        }
        throw new InvalidOperationException("Too many sector changes; stopped.");
    }

    // Only failures that say something about the way itself mark an exit as blocked;
    // focus loss, a closed game or a stop request say nothing about the exit.
    private static bool IsRouteProblem(string message) =>
        message.StartsWith("Blocked", StringComparison.Ordinal) || message.StartsWith("Kept leaving", StringComparison.Ordinal) ||
        message.StartsWith("Replanning found no route", StringComparison.Ordinal) || message.StartsWith("No complete route", StringComparison.Ordinal) ||
        message.StartsWith("Walked through the exit", StringComparison.Ordinal) || message.StartsWith("Steering exceeded", StringComparison.Ordinal);

    // ---- learning: crossings and blocked exits persist between runs ----

    private string LinksFile => Path.Combine(logDirectory, "traversal-links.jsonl");

    private void Learn(int from, string exit, int to, bool ok, double seconds, string? error)
    {
        try
        {
            File.AppendAllText(LinksFile, JsonSerializer.Serialize(new { timeUtc = DateTimeOffset.UtcNow, from, fromName = SectorName(from), exit, to, toName = SectorName(to), ok, seconds, error }) + "\n");
        }
        catch (IOException) { }
    }

    // One failed leg (a prop, a slow detour) says little about the exit itself: it is avoided for
    // the rest of this trip, but only kept out of later trips after BlockAfter failures in a row
    // with no success in between. An exit that leads somewhere else is kept out at once.
    private const int BlockAfter = 3;
    private const string Passed = "ok";

    private void Block(int sector, string exit, string why)
    {
        if (!_blocked.Add((sector, exit))) return;
        Console.WriteLine($"Avoiding {SectorName(sector)} {exit} for this trip: {why}");
        try { File.AppendAllText(Path.Combine(logDirectory, "traversal-blocked.txt"), $"{sector}\t{exit}\t{why}\n"); } catch (IOException) { }
    }

    /// <summary>Record that a walk got through this exit, which clears its failure count.</summary>
    private void Unblock(int sector, string exit)
    {
        try { File.AppendAllText(Path.Combine(logDirectory, "traversal-blocked.txt"), $"{sector}\t{exit}\t{Passed}\n"); } catch (IOException) { }
    }

    private static HashSet<(int, string)> LoadBlocked(string directory)
    {
        var failures = new Dictionary<(int, string), int>();
        string file = Path.Combine(directory, "traversal-blocked.txt");
        if (!File.Exists(file)) return new();
        foreach (var line in File.ReadAllLines(file))
        {
            var parts = line.Split('\t');
            if (parts.Length < 2 || !int.TryParse(parts[0], out int sector)) continue;
            var key = (sector, parts[1]);
            string why = parts.Length > 2 ? parts[2] : "";
            failures[key] = why == Passed ? 0 : why.StartsWith("leads to", StringComparison.Ordinal) ? BlockAfter : failures.GetValueOrDefault(key) + 1;
        }
        return failures.Where(f => f.Value >= BlockAfter).Select(f => f.Key).ToHashSet();
    }

    // After walking into an exit the client unloads the old world and loads the next;
    // wait until the player reads back valid and standing still, then report the sector.
    private int WaitForSector(PlayerReader reader, int expected)
    {
        hud.Post(Hud.Cyan, "TRAVERSAL  zoning", expected > 0 ? $"Loading {SectorName(expected)}..." : "Loading...");
        var clock = Stopwatch.StartNew();
        PlayerSample? last = null; long stillSince = 0; int? lastSector = null;
        while (clock.Elapsed.TotalSeconds < 90)
        {
            if ((Native.GetAsyncKeyState(0x77) & 0x8000) != 0) throw new OperationCanceledException("F8 stop pressed.");
            Thread.Sleep(250);
            PlayerSample s; int? sector;
            try { s = reader.ReadSample(); sector = reader.ReadSectorId(s.World); }
            catch (InvalidOperationException) { last = null; continue; }
            if (sector == null) { last = null; continue; }
            if (last == null || sector != lastSector || System.Numerics.Vector3.Distance(last.Position, s.Position) > 0.5f)
            { last = s; lastSector = sector; stillSince = clock.ElapsedMilliseconds; continue; }
            // Settled. A different sector than planned is reported, not hidden.
            if (clock.ElapsedMilliseconds - stillSince > 1500)
            {
                Console.WriteLine(sector == expected || expected == 0 ? $"Arrived in {SectorName(sector.Value)}." : $"Landed in {SectorName(sector.Value)} instead of {SectorName(expected)}.");
                return sector.Value;
            }
        }
        throw new InvalidOperationException($"{(expected > 0 ? SectorName(expected) : "The next place")} did not finish loading within 90 s.");
    }

    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(nint window);
    [DllImport("user32.dll")] private static extern bool ShowWindow(nint window, int command);
    [DllImport("user32.dll")] private static extern bool IsIconic(nint window);
    [DllImport("user32.dll")] private static extern void keybd_event(byte key, byte scan, uint flags, nuint extra);

    /// <summary>Bring the game window to the front (a synthetic Alt tap lifts Windows' focus lock).</summary>
    public static void FocusGame(nint window)
    {
        if (IsIconic(window)) ShowWindow(window, 9);   // SW_RESTORE
        keybd_event(0x12, 0, 0, 0); keybd_event(0x12, 0, 2, 0);
        SetForegroundWindow(window);
    }
}
