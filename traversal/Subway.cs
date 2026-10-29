using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// The Neocron City subway (world 1000), from its own files:
/// - One world holds four station halls: Plaza (Plaza 1 and 2), Pepper Park (1 and 2), Via Rosso 3 and
///   Outzone (Outzone 1 and Outzone Station, whose far door opens on wasteland cell A 08). Each hall is
///   its own floor: inside one you walk between its doors; between halls there is only the track.
/// - The track is one line, Plaza - Via Rosso - Pepper Park - Outzone, with turning loops at both ends.
///   Eleven SubwayTrain entities start 30 s apart (StartTime 0..300); all follow one motion path. A train
///   is vehicle 200 "Subway" (pak_vehicles, which has no speed for it): four passenger seats that hide
///   you (ShowPlayer 0) and put you back 220 units to the side when you leave (LeavePosition).
/// - The motion path is in the subway's spawn file (pak_subway.dat, section 4: "MTNB"): a 133,000-unit
///   loop driven in 329 s, with eight timed stops (STOP / OPEN / CLOSE / START events), two per hall.
///   Between stops a train runs 300-680 u/s on average (peaks about 1,280); each stop lasts 8-13 s.
///   That is the timetable plans use (<see cref="Timetable"/>).
/// - So a ride is: walk to the platform edge, face the track, "use" the train when it stands there,
///   stay seated until it stands at the platform you want, "use" again to step off (SubwayRide.cs).
/// Planning treats each hall as its own node (<see cref="SubwayNode"/>): halls join by train. Plan costs
/// are seconds: walking, plus a wait for the train, plus the ride by the timetable.
/// </summary>
internal sealed partial class Travel
{
    /// <summary>A station hall of the subway: its name, where to wait for the train, and where its platform runs.</summary>
    public sealed record SubwayPlatform(int Index, string Name, Vector3 Board, Vector3 Track, IReadOnlyList<Vector3> Edge);

    /// <summary>A way out of the subway: its door (world 1000's WorldChange), the station it leads to and the hall it is in.</summary>
    public sealed record SubwayStop(string Exit, int To, int Platform, Vector3 Position);

    /// <summary>The halls, their doors and the track length between each pair of halls (0 on the diagonal; -1: no track).</summary>
    public sealed record SubwayData(IReadOnlyList<SubwayPlatform> Platforms, IReadOnlyList<SubwayStop> Stops, float[][] Track);

    /// <summary>Plan node of a subway hall: below every sector id. Never a real sector; plans name it <see cref="Subway"/>.</summary>
    public static int SubwayNode(int platform) => -2000 - platform;
    public static bool IsSubwayNode(int node) => node is <= -2000 and > -2100;
    private static int PlatformOfNode(int node) => -2000 - node;

    /// <summary>Seconds between trains: their StartTimes are 30 s apart, and eleven fill the 329 s loop.</summary>
    public const float Headway = 30;

    /// <summary>Getting aboard once a train stands at the platform (SubwayRide presses "use" every 3 s).</summary>
    public const float BoardSeconds = 5;

    /// <summary>Waiting at the platform: on average half the headway, plus boarding.</summary>
    public const float WaitSeconds = Headway / 2 + BoardSeconds;

    /// <summary>Stepping off once the train stands at the platform wanted (it waits 1.5 s still, then "use").</summary>
    public const float StepOffSeconds = 5;

    /// <summary>Without the timetable (no spawn file): the train's average between stops, and each stop on the way.</summary>
    public const float TrainSpeed = 550, StopSeconds = 10;

    /// <summary>The walk from a street's subway door record down the station stairs to the room at the bottom (about 1,000 units in Plaza 1 and Pepper Park 1).</summary>
    public const float StationStairs = 1000;

    /// <summary>One timed stop of the trains' loop: when it stands still, when it leaves, and where.</summary>
    public sealed record TrainStop(float Stop, float Start, Vector3 At);

    /// <summary>The trains' loop from the subway's spawn file: its length in seconds and units, and its stops in order.</summary>
    public sealed record SubwayTimetable(float Period, float Length, IReadOnlyList<TrainStop> Stops);

    private SubwayTimetable? _timetable;
    private bool _timetableTried;

    /// <summary>The trains' timetable (null when the spawn file is missing or unreadable).</summary>
    public SubwayTimetable? Timetable()
    {
        lock (_isTerrain)
        {
            if (_timetableTried) return _timetable;
            _timetableTried = true;
            try
            {
                var area = Areas.FirstOrDefault(a => a.WorldId == Subway);
                string path = area == null ? "" : SectorObjects.DatPath(install, area.AssetPath);
                if (!File.Exists(path)) return null;
                byte[] bytes = File.ReadAllBytes(path);
                try { bytes = NpcDefinitions.DecodeBytes(bytes); } catch (InvalidDataException) { }
                _timetable = ReadTimetable(bytes);
            }
            catch (Exception e) when (e is IOException or InvalidDataException or ArgumentException) { _timetable = null; }
            return _timetable;
        }
    }

    /// <summary>
    /// Read the trains' motion from a decoded subway spawn file. Section 4 holds "MTNB" motion blocks; the
    /// first is the trains': a "TKEB" list of named events (START, STOP, OPEN, CLOSE) with their times, and
    /// an "SBKB" spline: a count of keys, their times (0 to the loop's period), then their positions.
    /// </summary>
    public static SubwayTimetable? ReadTimetable(byte[] dat)
    {
        if (dat.Length < 8) return null;
        int p = 4 + (int)U(dat, 0);
        byte[]? motion = null;
        while (p + 16 <= dat.Length)
        {
            uint header = U(dat, p), section = U(dat, p + 8), size = U(dat, p + 12);
            if (header < 12) break;
            p += 4 + (int)header;
            if (p + size > dat.Length) break;
            if (section == 4) { motion = dat.AsSpan(p, (int)size).ToArray(); break; }
            p += (int)size;
        }
        if (motion == null) return null;
        int events = Find(motion, "TKEB"u8, 0), spline = Find(motion, "SBKB"u8, 0);
        if (events < 0 || spline < events) return null;
        // TKEB: tag, u32, u32 length of the names, the names (zero-terminated), u32 count, u32, count x (f32 time, u32 name offset).
        int namesLength = (int)U(motion, events + 8), names = events + 12, at = names + namesLength;
        if (at + 8 > motion.Length) return null;
        int count = (int)U(motion, at); at += 8;
        if (count is < 2 or > 1000 || at + count * 8 > motion.Length) return null;
        string Name(int offset)
        {
            int start = names + offset, end = Array.IndexOf(motion, (byte)0, start);
            return end < 0 || offset >= namesLength ? "" : System.Text.Encoding.Latin1.GetString(motion, start, end - start);
        }
        var timed = Enumerable.Range(0, count).Select(i => (Time: BitConverter.ToSingle(motion, at + i * 8), Name: Name((int)U(motion, at + i * 8 + 4)))).ToList();
        // SBKB: the key count is the first u32 followed by that many rising times from 0, then the positions.
        for (int k = spline + 8; k < Math.Min(motion.Length - 8, spline + 400); k += 1)
        {
            int keys = (int)U(motion, k);
            if (keys is < 8 or > 5000 || k + 4 + keys * 16 > motion.Length) continue;
            var times = Enumerable.Range(0, keys).Select(i => BitConverter.ToSingle(motion, k + 4 + i * 4)).ToArray();
            if (times[0] != 0 || times[^1] < 10 || times.Zip(times.Skip(1)).Any(t => !(t.Second >= t.First))) continue;
            int at3 = k + 4 + keys * 4;
            var points = Enumerable.Range(0, keys).Select(i => new Vector3(BitConverter.ToSingle(motion, at3 + i * 12), BitConverter.ToSingle(motion, at3 + i * 12 + 4), BitConverter.ToSingle(motion, at3 + i * 12 + 8))).ToArray();
            if (points.Any(v => !float.IsFinite(v.X) || !float.IsFinite(v.Y) || !float.IsFinite(v.Z) || MathF.Abs(v.X) > 1e6f || MathF.Abs(v.Z) > 1e6f)) continue;
            float period = times[^1], length = 0;
            for (int i = 1; i < keys; i++) length += Vector3.Distance(points[i - 1], points[i]);
            Vector3 PositionAt(float t)
            {
                int i = Array.FindIndex(times, x => x >= t);
                if (i <= 0) return points[Math.Max(i, 0)];
                float f = times[i] > times[i - 1] ? (t - times[i - 1]) / (times[i] - times[i - 1]) : 0;
                return Vector3.Lerp(points[i - 1], points[i], f);
            }
            var starts = timed.Where(e => e.Name == "START").Select(e => e.Time).OrderBy(t => t).ToList();
            var stops = new List<TrainStop>();
            foreach (float stop in timed.Where(e => e.Name == "STOP").Select(e => e.Time).OrderBy(t => t))
            {
                // Leaves at the next START, which for the loop's last stop is the first one of the next lap.
                float start = starts.FirstOrDefault(s => s > stop, starts.Count > 0 ? starts[0] + period : stop);
                stops.Add(new(stop, start, PositionAt(stop)));
            }
            return stops.Count >= 2 ? new(period, length, stops) : null;
        }
        return null;
    }

    private static uint U(byte[] b, int at) => System.Buffers.Binary.BinaryPrimitives.ReadUInt32LittleEndian(b.AsSpan(at, 4));
    private static int Find(byte[] b, ReadOnlySpan<byte> tag, int from) { int i = b.AsSpan(from).IndexOf(tag); return i < 0 ? -1 : from + i; }

    /// <summary>The hall a train stop is in (its position beside that hall's platform edge), or -1.</summary>
    private static int HallOfStop(SubwayData data, TrainStop stop)
    {
        var near = data.Platforms.Where(p => p.Edge.Count > 0)
            .Select(p => (p.Index, Distance: p.Edge.Min(e => Vector2.Distance(new(e.X, e.Z), new(stop.At.X, stop.At.Z)))))
            .OrderBy(p => p.Distance).FirstOrDefault();
        return near.Distance < 600 ? near.Index : -1;
    }

    /// <summary>
    /// Seconds on the train from the platform at <paramref name="from"/>'s boarding spot to the first stop at
    /// <paramref name="to"/>'s platform, by the timetable: trains run one way round the loop, so a ride may pass
    /// other stops (8-13 s each). Without a timetable, estimated from the track's length. Null: no track.
    /// </summary>
    public float? RideSeconds(int from, int to)
    {
        if (Subways() is not { } data || from == to) return from == to ? 0 : null;
        float length = data.Track[from][to];
        if (length < 0) return null;
        if (Timetable() is { } table && data.Platforms[from].Edge.Count > 0)
        {
            var board = data.Platforms[from].Track;
            int i = Enumerable.Range(0, table.Stops.Count).MinBy(k => Vector2.Distance(new(table.Stops[k].At.X, table.Stops[k].At.Z), new(board.X, board.Z)));
            if (HallOfStop(data, table.Stops[i]) == from)
                for (int k = 1; k < table.Stops.Count; k++)
                {
                    var stop = table.Stops[(i + k) % table.Stops.Count];
                    if (HallOfStop(data, stop) != to) continue;
                    float ride = stop.Stop - table.Stops[i].Start;
                    while (ride <= 0) ride += table.Period;
                    return ride;
                }
        }
        // The halls between, as stops on the way.
        int between = data.Platforms.Count(p => p.Index != from && p.Index != to && data.Track[from][p.Index] > 0 && data.Track[p.Index][to] > 0
            && data.Track[from][p.Index] + data.Track[p.Index][to] < length * 1.05f);
        return length / TrainSpeed + between * StopSeconds;
    }

    private SubwayData? _subway;
    private bool _subwayTried;

    /// <summary>The subway's halls and doors: from subway.json (made by "traversal subway"), else worked out from its navmesh.</summary>
    public SubwayData? Subways()
    {
        lock (_isTerrain)
        {
            if (_subwayTried) return _subway;
            _subwayTried = true;
            string file = Path.Combine(Home, "subway.json"), stamp = WorldFilesStamp();
            try
            {
                if (File.Exists(file) && LoadSubway(File.ReadAllText(file), stamp) is { } cached) return _subway = cached;
            }
            catch (Exception e) when (e is IOException or JsonException or KeyNotFoundException or InvalidOperationException or FormatException) { }
            try
            {
                _subway = ComputeSubway(bake(Subway));
                try { File.WriteAllText(file, SaveSubway(_subway, stamp)); } catch (IOException) { }
            }
            // No navmesh here (offline tools that never bake): plans simply never ride.
            catch (Exception e) when (e is NotSupportedException or IOException or InvalidDataException or InvalidOperationException) { _subway = null; }
            return _subway;
        }
    }

    /// <summary>Work the halls out from the subway's navmesh: its floors, which doors stand on each, and the track between them.</summary>
    public SubwayData ComputeSubway(NavWorld nav)
    {
        var exits = Exits(Subway).ToList();
        var islands = new List<HashSet<long>>();
        var stops = new List<SubwayStop>();
        foreach (var (exit, to) in exits)
        {
            if (!nav.Snap(exit.Position, out long poly, out var on, wide: true)) continue;
            int piece = islands.FindIndex(i => i.Contains(poly));
            if (piece < 0) { islands.Add(nav.Island(on)); piece = islands.Count - 1; }
            stops.Add(new(exit.Name, to, piece, on));
        }
        // The track: the biggest floor that holds no door (it runs under and beside every hall).
        var all = AllPolygons(nav);
        var used = new HashSet<long>(islands.SelectMany(i => i));
        HashSet<long> track = new();
        foreach (long poly in all.Keys)
        {
            if (used.Contains(poly)) continue;
            var piece = Flood(nav, poly);
            used.UnionWith(piece);
            if (piece.Count > track.Count) track = piece;
        }
        var trackPoints = track.SelectMany(p => all[p]).ToList();
        var platforms = new List<SubwayPlatform>();
        for (int i = 0; i < islands.Count; i++)
        {
            // The platform edge: hall floor a little above the track (the train's floor is 50 above the rail,
            // and you step off 220 units to its side) with track right beside it.
            var floor = islands[i].Where(all.ContainsKey).SelectMany(p => all[p]).Distinct().ToList();
            var edge = new List<Vector3>();
            foreach (var v in floor)
            {
                if (trackPoints.Any(t => v.Y - t.Y is > 25 and < 90 && PointNavigation.Distance(t, v) < 110)) edge.Add(v);
            }
            string name = StationName(stops.Where(s => s.Platform == i).Select(s => s.To));
            if (edge.Count == 0) { platforms.Add(new(i, name, default, default, edge)); continue; }
            var middle = new Vector3(edge.Average(e => e.X), edge.Average(e => e.Y), edge.Average(e => e.Z));
            // Stand at the middle of the platform edge; the train stops along it.
            var board = edge.MinBy(e => PointNavigation.Distance(e, middle));
            // Face the track: toward the rail bed beside the spot, out to where a train's middle runs
            // (you are put down 220 units from it).
            var rail = trackPoints.Where(t => board.Y - t.Y is > 25 and < 90 && PointNavigation.Distance(t, board) < 250).ToList();
            var toward = rail.Count == 0 ? Vector3.Zero : new Vector3(rail.Average(t => t.X) - board.X, 0, rail.Average(t => t.Z) - board.Z);
            var near = toward.LengthSquared() < 1 ? trackPoints.MinBy(t => PointNavigation.Distance(t, board))
                : new Vector3(board.X, rail.Average(t => t.Y), board.Z) + Vector3.Normalize(toward) * 220;
            if (nav.Snap(board, out _, out var snapped)) board = snapped;
            platforms.Add(new(i, name, board, near, Thin(edge, 120)));
        }
        var lengths = new float[platforms.Count][];
        for (int a = 0; a < platforms.Count; a++)
        {
            lengths[a] = new float[platforms.Count];
            for (int b = 0; b < platforms.Count; b++)
            {
                if (a == b) continue;
                var route = platforms[a].Edge.Count == 0 || platforms[b].Edge.Count == 0 ? new() : nav.Route(platforms[a].Track, platforms[b].Track, out bool ok) is var r && ok ? r : new();
                lengths[a][b] = route.Count > 1 ? new RouteFollower(route).Total : -1;
            }
        }
        return new(platforms, stops, lengths);
    }

    // A hall is named for the streets its doors open on: "PLAZA", "PEPPER PARK", "VIAROSSO", "OUTZONE".
    private string StationName(IEnumerable<int> sectors)
    {
        var names = sectors.Select(SectorName).ToList();
        string? street = names.FirstOrDefault(n => n.Contains(" SEC-", StringComparison.Ordinal));
        return street != null ? street[..street.IndexOf(" SEC-", StringComparison.Ordinal)] : names.FirstOrDefault() ?? "?";
    }

    private static List<Vector3> Thin(List<Vector3> points, float spacing)
    {
        var kept = new List<Vector3>();
        foreach (var p in points.OrderBy(p => p.X).ThenBy(p => p.Z))
            if (kept.All(k => Vector3.Distance(k, p) >= spacing)) kept.Add(p);
        return kept;
    }

    // The polygons joined to `start` (as NavWorld.Island, from a polygon rather than a point).
    private static HashSet<long> Flood(NavWorld nav, long start)
    {
        var seen = new HashSet<long> { start };
        var stack = new Stack<long>(); stack.Push(start);
        while (stack.Count > 0)
        {
            nav.Mesh.GetTileAndPolyByRefUnsafe(stack.Pop(), out var tile, out var poly);
            for (int link = poly.firstLink; link >= 0 && link < tile.links.Length; link = tile.links[link].next)
            {
                long next = tile.links[link].refs;
                if (next != 0 && seen.Add(next)) stack.Push(next);
            }
        }
        return seen;
    }

    // Every ground polygon of the navmesh, with its corners.
    private static Dictionary<long, List<Vector3>> AllPolygons(NavWorld nav)
    {
        var map = new Dictionary<long, List<Vector3>>();
        for (int t = 0; t < nav.Mesh.GetMaxTiles(); t++)
        {
            var tile = nav.Mesh.GetTile(t);
            if (tile?.data?.header == null) continue;
            long baseRef = nav.Mesh.GetPolyRefBase(tile);
            for (int j = 0; j < tile.data.header.polyCount; j++)
            {
                var poly = tile.data.polys[j];
                if (poly.GetPolyType() != DotRecast.Detour.DtPolyTypes.DT_POLYTYPE_GROUND) continue;
                var corners = new List<Vector3>();
                for (int k = 0; k < poly.vertCount; k++) { int v = poly.verts[k] * 3; corners.Add(new(tile.data.verts[v], tile.data.verts[v + 1], tile.data.verts[v + 2])); }
                map[baseRef | (long)j] = corners;
            }
        }
        return map;
    }

    private static float[] Arr(Vector3 v) => new[] { MathF.Round(v.X), MathF.Round(v.Y), MathF.Round(v.Z) };
    private static Vector3 Vec(JsonElement e) => new(e[0].GetSingle(), e[1].GetSingle(), e[2].GetSingle());

    private static string SaveSubway(SubwayData data, string stamp) => JsonSerializer.Serialize(new
    {
        stamp,
        platforms = data.Platforms.Select(p => new { p.Index, p.Name, board = Arr(p.Board), track = Arr(p.Track), edge = p.Edge.Select(Arr) }),
        stops = data.Stops.Select(s => new { s.Exit, s.To, s.Platform, position = Arr(s.Position) }),
        track = data.Track,
    }, new JsonSerializerOptions { WriteIndented = true });

    private static SubwayData? LoadSubway(string json, string stamp)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.GetProperty("stamp").GetString() != stamp) return null;
        var platforms = root.GetProperty("platforms").EnumerateArray().Select(p => new SubwayPlatform(p.GetProperty("Index").GetInt32(), p.GetProperty("Name").GetString() ?? "",
            Vec(p.GetProperty("board")), Vec(p.GetProperty("track")), p.GetProperty("edge").EnumerateArray().Select(Vec).ToList())).ToList();
        var stops = root.GetProperty("stops").EnumerateArray().Select(s => new SubwayStop(s.GetProperty("Exit").GetString() ?? "", s.GetProperty("To").GetInt32(),
            s.GetProperty("Platform").GetInt32(), Vec(s.GetProperty("position")))).ToList();
        var track = root.GetProperty("track").EnumerateArray().Select(r => r.EnumerateArray().Select(v => v.GetSingle()).ToArray()).ToArray();
        return new(platforms, stops, track);
    }

    /// <summary>
    /// Seconds from standing at one hall's boarding spot to standing on another hall's platform: the wait for
    /// a train, the ride by the timetable and stepping off. Null when no track joins them.
    /// </summary>
    public float? RideCost(int from, int to)
    {
        if (from == to) return 0;
        return RideSeconds(from, to) is { } ride ? WaitSeconds + ride + StepOffSeconds : null;
    }

    // Plan steps through the subway (used by the cost search in TerrainTravel.Steps), in seconds: from a
    // station street down into its hall, and from a hall (standing at `at`, else its boarding spot) to any
    // station: walking to its door in this hall, or walking to the platform, waiting, riding and walking on.
    private IEnumerable<Step> SubwaySteps(int node, Vector3? at)
    {
        if (Subways() is not { } data) yield break;
        if (IsSubwayNode(node))
        {
            int platform = PlatformOfNode(node);
            var hall = data.Platforms[platform];
            var here = at ?? hall.Board;
            foreach (var stop in data.Stops)
            {
                if (Avoided(Subway, stop.Exit) || !SafeLinks(stop.To).Any(back => back.To == Subway)) continue;
                float seconds;
                if (stop.Platform == platform) seconds = WalkSeconds(here, stop.Position);
                else if (RideCost(platform, stop.Platform) is { } ride && hall.Edge.Count > 0)
                    seconds = WalkSeconds(here, hall.Board) + ride + WalkSeconds(data.Platforms[stop.Platform].Board, stop.Position);
                else continue;
                var door = SafeLinks(Subway).FirstOrDefault(l => l.Exit.Name == stop.Exit).Exit;
                yield return new(stop.To, seconds + ZoneSeconds, null, door == null ? null : Arrival(stop.To, door));
            }
            yield break;
        }
        var from = at ?? Middle(node);
        foreach (var (exit, to) in SafeLinks(node))
        {
            if (to != Subway || Avoided(node, exit.Name)) continue;
            // The door's arrival point names the subway door you come out by, and so the hall.
            string arrival = exit.Properties.GetValueOrDefault("NextLevelStartIndex") ?? "";
            var into = SafeLinks(Subway).FirstOrDefault(l => l.To == node && l.Exit.Properties.GetValueOrDefault("Index") == arrival);
            var stop = into.Exit == null ? null : data.Stops.FirstOrDefault(s => s.Exit == into.Exit.Name);
            if (stop != null) yield return new(SubwayNode(stop.Platform), WalkSeconds(from, exit.Position) + StationStairs / WalkPace + ZoneSeconds, null, stop.Position);
        }
    }

    /// <summary>
    /// A city path found by hop count, or the cost search's way through the subway when that is quicker
    /// (both timed the same way, from <paramref name="at"/> when known). Quick paths are kept as they are:
    /// no subway trip takes less than <see cref="MinSubwayTrip"/>.
    /// </summary>
    private List<int> PreferSubway(int from, int to, List<int> path, Vector3? at)
    {
        if (from == Subway || to == Subway || Subways() == null) return path;
        float seconds = PathSeconds(path, at);
        if (seconds <= MinSubwayTrip) return path;
        var plan = WastelandPlan(from, to, at);
        return plan != null && plan.Sectors.Contains(Subway) && plan.Cost < seconds ? plan.Sectors : path;
    }

    /// <summary>In and out of the subway, a wait and a short ride: no trip by train takes less.</summary>
    private const float MinSubwayTrip = 2 * ZoneSeconds + WaitSeconds + 40;

    private static readonly Dictionary<(NavWorld, Vector3), (Vector3 Walk, Vector3 Push)?> _entrances = new();

    /// <summary>
    /// Where a street's subway entrance is, from the level geometry. The door's record (where people coming
    /// out of the subway appear) is on the landing of the station stairs: in Plaza 1 and Pepper Park 1 the
    /// street ramps 128 units down to it, and a second ramp goes on down another 128 to a closed room. The
    /// game puts you through somewhere down there; the floor beyond the record (the push corridor) is street.
    /// So: of the floor reachable from the record by only going down (never back above it), the lowest, and
    /// on it the far end of the walk; the push carries on the same way into the room's far wall.
    /// Null when no floor lies below the record within a short walk (keep to the record then).
    /// </summary>
    public static (Vector3 Walk, Vector3 Push)? SubwayEntrance(NavWorld nav, Vector3 record)
    {
        lock (_entrances)
            if (_entrances.TryGetValue((nav, record), out var known)) return known;
        (Vector3, Vector3)? found = null;
        if (nav.Snap(record, out _, out var start, wide: true))
        {
            List<Vector3>? best = null; float bestLevel = float.MaxValue, bestLength = 0;
            foreach (var corners in AllPolygons(nav).Values)
            {
                var centre = corners.Aggregate(Vector3.Zero, (a, b) => a + b) / corners.Count;
                if (centre.Y > start.Y - 80 || Vector2.Distance(new(centre.X, centre.Z), new(start.X, start.Z)) > EntranceReach) continue;
                var route = nav.Route(start, centre, out bool ok);
                if (!ok || route.Count < 2 || route.Any(p => p.Y > start.Y + 40)) continue;   // only down, never back up to the street
                float length = new RouteFollower(route).Total;
                if (length > EntranceReach) continue;
                // Lowest floor first (32-unit steps), then the far end of it.
                float level = MathF.Round(centre.Y / 32);
                if (level < bestLevel || (level == bestLevel && length > bestLength)) { best = route; bestLevel = level; bestLength = length; }
            }
            if (best != null)
            {
                var end = best[^1];
                var on = new Vector2(end.X - best[^2].X, end.Z - best[^2].Z);
                on = on.LengthSquared() < 1 ? Vector2.Zero : Vector2.Normalize(on);
                found = (end, new Vector3(end.X + on.X * 300, end.Y, end.Z + on.Y * 300));
            }
        }
        lock (_entrances) _entrances[(nav, record)] = found;
        return found;
    }

    /// <summary>How far down from a subway door's record its station room may be (Plaza 1 and Pepper Park 1: about 1,000 units of walk).</summary>
    public const float EntranceReach = 1600;

    /// <summary>True when a door object (from the sector's spawn file) stands at a subway entrance: by its record or on the stairs' end.</summary>
    public static bool DoorAt(NavWorld nav, Vector3 record, Vector3 walk) =>
        nav.Doors.Any(d => new[] { record, walk }.Any(p => Vector2.Distance(new(d.Position.X, d.Position.Z), new(p.X, p.Z)) < 400 && MathF.Abs(d.Position.Y - p.Y) < 250));

    /// <summary>The hall you stand in (world 1000), or -1 when the floor under you is none of them (the track, a train).</summary>
    public int PlatformAt(NavWorld nav, Vector3 position)
    {
        if (Subways() is not { } data || !nav.Snap(position, out long poly, out var on) || MathF.Abs(on.Y - position.Y) > 60) return -1;
        foreach (var platform in data.Platforms)
            if (HallIsland(nav, platform).Contains(poly)) return platform.Index;
        return -1;
    }

    private readonly Dictionary<(NavWorld, int), HashSet<long>> _halls = new();

    private HashSet<long> HallIsland(NavWorld nav, SubwayPlatform platform)
    {
        if (_halls.TryGetValue((nav, platform.Index), out var island)) return island;
        var door = Subways()!.Stops.First(s => s.Platform == platform.Index);
        return _halls[(nav, platform.Index)] = nav.Island(door.Position);
    }

    /// <summary>
    /// The way on from inside the subway, standing at <paramref name="at"/>: the sectors (starting with the
    /// subway), the hall you are in, and the door the plan leaves by (in another hall when a ride comes first).
    /// </summary>
    public List<int> SubwayPath(Vector3 at, int to, NavWorld nav, out int platform, out SubwayStop? stop)
    {
        platform = PlatformAt(nav, at); stop = null;
        if (platform < 0) return SectorPath(Subway, to);
        var plan = WastelandPlan(SubwayNode(platform), to, at);
        if (plan == null || plan.Sectors.Count < 2) return new();
        int next = plan.Sectors[1], here = platform;
        stop = Subways()!.Stops.Where(s => s.To == next && !Avoided(Subway, s.Exit))
            .OrderBy(s => RideCost(here, s.Platform) ?? float.MaxValue).FirstOrDefault();
        return plan.Sectors;
    }

    /// <summary>
    /// Offline (PlanTrip): when the plan from the hall at <paramref name="at"/> leaves by a door in another
    /// hall, add the walk to the platform and the train ride as one leg; returns where you step off.
    /// </summary>
    private Vector3? SubwayPlanLeg(Vector3 at, int to, NavWorld nav, List<PlannedLeg> legs)
    {
        SubwayPath(at, to, nav, out int platform, out var stop);
        if (stop == null || platform < 0 || stop.Platform == platform || Subways() is not { } data) return null;
        if (legs.Count(l => l.Method == "train") >= 3) return null;
        var a = data.Platforms[platform]; var b = data.Platforms[stop.Platform];
        var walk = nav.Route(at, a.Board, out bool walked);
        float track = data.Track[a.Index][b.Index];
        bool ok = walked && walk.Count > 1 && a.Edge.Count > 0 && b.Edge.Count > 0 && track > 0;
        legs.Add(new(Subway, Subway, "train", track, ok, ok
            ? $"walk {new RouteFollower(walk).Total:F0} to the {a.Name} platform, ride to the {b.Name} platform (wait about {WaitSeconds:F0} s, ride {RideSeconds(a.Index, b.Index):F0} s)"
            : $"no way onto a train from the {a.Name} platform to the {b.Name} platform"));
        return ok ? b.Board : null;
    }

    private int _rides;

    /// <summary>
    /// In the subway (from Go): when the plan leaves by a door in another hall, ride the train there and
    /// return true (the trip then carries on from the new hall). False when the door is in this hall.
    /// </summary>
    private bool SubwayLeg(PlayerReader reader, PlayerSample sample, int targetSector, NavWorld nav, string log, ref bool first, ref LiveSteer.Calibration? calibration)
    {
        SubwayPath(sample.Position, targetSector, nav, out int platform, out var stop);
        if (stop == null || platform < 0 || stop.Platform == platform || Subways() is not { } data) return false;
        if (++_rides > 4) throw new InvalidOperationException("Rode the subway four times on one trip without getting there; stopped.");
        var from = data.Platforms[platform]; var to = data.Platforms[stop.Platform];
        if (from.Edge.Count == 0 || to.Edge.Count == 0) throw new InvalidOperationException($"The subway's {from.Name} or {to.Name} platform edge is not on the map; cannot ride.");
        Console.WriteLine($"Subway: from the {from.Name} platform to the {to.Name} platform by train ({data.Track[from.Index][to.Index]:F0} units of track, about {RideSeconds(from.Index, to.Index):F0} s aboard), for {SectorName(stop.To)}.");
        var ride = new SubwayRide(reader, nav, this, from, to, pulse, log, hud, run, calibration, first);
        try { ride.Run(); }
        finally { calibration ??= ride.Measured; first = false; }
        return true;
    }

    /// <summary>Diagnostics ("traversal subway"): the halls, their doors, platforms and the track between them; rewrites subway.json.</summary>
    public void SubwayReport(NavWorld nav)
    {
        var data = ComputeSubway(nav);
        try { File.WriteAllText(Path.Combine(Home, "subway.json"), SaveSubway(data, WorldFilesStamp())); } catch (IOException) { }
        _subway = data; _subwayTried = true;
        foreach (var p in data.Platforms)
        {
            Console.WriteLine($"{p.Name} hall (platform {p.Index}): doors to {string.Join(", ", data.Stops.Where(s => s.Platform == p.Index).Select(s => $"{SectorName(s.To)} ({s.Exit})"))}");
            Console.WriteLine(p.Edge.Count == 0 ? "  no platform edge beside the track"
                : $"  wait for the train at {p.Board.X:F0},{p.Board.Y:F0},{p.Board.Z:F0} facing the track at {p.Track.X:F0},{p.Track.Y:F0},{p.Track.Z:F0}; platform edge {p.Edge.Count} points");
            foreach (var q in data.Platforms.Where(q => q.Index != p.Index))
                Console.WriteLine($"  to {q.Name}: {(data.Track[p.Index][q.Index] < 0 ? "no track" : $"{data.Track[p.Index][q.Index]:F0} units of track, {RideSeconds(p.Index, q.Index):F0} s aboard, {RideCost(p.Index, q.Index):F0} s with the wait")}");
        }
        if (Timetable() is { } table)
        {
            Console.WriteLine($"Trains: one loop of {table.Length:F0} units in {table.Period:F0} s ({table.Length / table.Period:F0} u/s overall), a train every {Headway:F0} s; stops:");
            for (int i = 0; i < table.Stops.Count; i++)
            {
                var s = table.Stops[i]; var next = table.Stops[(i + 1) % table.Stops.Count];
                int hall = HallOfStop(data, s);
                Console.WriteLine($"  {s.Stop,5:F0}-{s.Start,5:F0} s at {s.At.X:F0},{s.At.Z:F0} ({(hall < 0 ? "no hall" : data.Platforms[hall].Name)}), then {(next.Stop - s.Start + (next.Stop < s.Start ? table.Period : 0)):F0} s to the next stop");
            }
        }
        else Console.WriteLine("Trains: no timetable (the subway's spawn file is missing); rides are estimated from the track's length.");
    }
}
