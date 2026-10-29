using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;
using NeocronSharp.Core;

namespace NeocronSharp.Navigation;

/// <summary>Where the player is: world (sector) id and position (Y = feet).</summary>
public sealed record NavLocation(int World, Vector3 Position);

/// <summary>Source of baked worlds for the protocol (the app uses <see cref="NavMeshStore"/>).</summary>
public interface INavWorlds
{
    NavWorld Get(int worldId);
    string? WorldName(int worldId);
    /// <summary>"memory", "cache" or "bake" for the last <see cref="Get"/>.</summary>
    string LastSource { get; }
}

/// <summary>
/// The --navplan line protocol: one JSON request in, one JSON answer out, both a single line.
/// Requests (an optional "id" of any JSON value is echoed back):
///   {"to":"exits"}                                  every WorldChange in the current world, with its route from here
///   {"to":"exit","name":"WorldChange3"}             path to that exit (name is case-insensitive)
///   {"to":"exit","bearing":135}                     path to the reachable zone exit whose direction from here is closest
///                                                   to that bearing (0 = -Z, 90 = +X, as telemetry heading)
///   {"to":"point","x":..,"z":..[,"y":..]}           path to a point; without y the floor nearest the player's height is used
/// Answers: {"ok":true,"world":id,"worldName":..,"mesh":"memory|cache|bake","from":[x,y,z],"path":[[x,y,z],..],
///   "complete":bool,"length":units,"exit":{..}} or {"ok":false,"error":".."}. "path" is the Detour straight path
///   (corners, first = the player's snapped position); "complete" is false when the target cannot be reached on the
///   mesh and the path stops at the nearest reachable point. "exits" answers carry "exits":[..] instead of a path.
/// Exit objects: name, position [x,y,z], index, nextLevel (destination world id), nextLevelName, nextLevelStartIndex
///   (arrival point in the destination; 0 = none), destinationKnown (nextLevel &gt; 0 and an arrival point is set),
///   bearing and distance (straight line from the player); in "exits" also pathLength (null when unroutable) and complete.
/// </summary>
public sealed class NavPlanProtocol
{
    private readonly INavWorlds _worlds;
    public NavPlanProtocol(INavWorlds worlds) => _worlds = worlds;

    private sealed record Exit(EnvironmentFeature Feature, int? Index, int? NextLevel, int? StartIndex)
    {
        public bool DestinationKnown => NextLevel > 0 && StartIndex > 0;
    }

    public string Answer(string line, Func<NavLocation> locate)
    {
        JsonElement? id = null;
        try
        {
            using var doc = JsonDocument.Parse(line);
            var request = doc.RootElement;
            if (request.ValueKind != JsonValueKind.Object) return Error(null, "The request must be a JSON object.");
            if (request.TryGetProperty("id", out var rawId)) id = rawId.Clone();
            string to = request.TryGetProperty("to", out var kind) && kind.ValueKind == JsonValueKind.String ? kind.GetString()!.ToLowerInvariant() : "";
            if (to is not ("exits" or "exit" or "point")) return Error(id, "\"to\" must be \"exits\", \"exit\" or \"point\".");

            NavLocation here;
            NavWorld nav;
            try { here = locate(); nav = _worlds.Get(here.World); }
            catch (Exception error) when (error is not OutOfMemoryException) { return Error(id, error.Message); }
            var exits = nav.World.Summary.Features.Where(f => f.Kind.Equals("WorldChange", StringComparison.OrdinalIgnoreCase))
                .Select(f => new Exit(f, Int(f, "Index"), Int(f, "NextLevel"), Int(f, "NextLevelStartIndex"))).ToList();

            if (to == "exits")
                return Write(id, here, nav, json =>
                {
                    json.WriteStartArray("exits");
                    foreach (var exit in exits.OrderBy(e => NaturalKey(e.Feature.Name)))
                    {
                        var path = nav.Route(here.Position, exit.Feature.Position, out bool complete, wideTarget: true);
                        json.WriteStartObject();
                        WriteExitFields(json, exit, here);
                        if (path.Count > 0) json.WriteNumber("pathLength", Round(NavWorld.Length(path))); else json.WriteNull("pathLength");
                        json.WriteBoolean("complete", path.Count > 0 && complete);
                        json.WriteEndObject();
                    }
                    json.WriteEndArray();
                });

            if (to == "exit")
            {
                Exit chosen;
                List<Vector3> path; bool complete;
                if (request.TryGetProperty("name", out var nameValue) && nameValue.ValueKind == JsonValueKind.String)
                {
                    string name = nameValue.GetString()!;
                    var found = exits.FirstOrDefault(e => e.Feature.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
                    if (found == null)
                        return Error(id, $"No exit named '{name}' in {nav.World.Summary.Name}. Known: {string.Join(", ", exits.Select(e => e.Feature.Name).OrderBy(NaturalKey))}.");
                    chosen = found;
                    path = nav.Route(here.Position, chosen.Feature.Position, out complete, wideTarget: true);
                }
                else if (request.TryGetProperty("bearing", out var bearingValue) && bearingValue.ValueKind == JsonValueKind.Number)
                {
                    double bearing = bearingValue.GetDouble();
                    if (!double.IsFinite(bearing)) return Error(id, "\"bearing\" must be a finite number of degrees.");
                    var candidates = exits.Select(e => (Exit: e, Path: nav.Route(here.Position, e.Feature.Position, out bool ok, wideTarget: true), Complete: ok))
                        .Where(c => c.Path.Count > 1 && c.Complete).ToList();
                    // Prefer real zone exits (a known destination other than this world) over lifts and placeholders.
                    var zoneExits = candidates.Where(c => c.Exit.DestinationKnown && c.Exit.NextLevel != here.World).ToList();
                    if (zoneExits.Count > 0) candidates = zoneExits;
                    if (candidates.Count == 0) return Error(id, $"No exit in {nav.World.Summary.Name} is reachable on the navmesh from here.");
                    var best = candidates.MinBy(c => AngleBetween(bearing, BearingTo(here.Position, c.Exit.Feature.Position)));
                    (chosen, path, complete) = best;
                }
                else return Error(id, "An exit request needs \"name\" (string) or \"bearing\" (degrees).");
                if (path.Count == 0) return Error(id, $"No route to {chosen.Feature.Name}: the player or the exit is off the navmesh.");
                return Write(id, here, nav, json =>
                {
                    WritePath(json, path, complete);
                    json.WriteStartObject("exit"); WriteExitFields(json, chosen, here); json.WriteEndObject();
                });
            }

            // point
            if (!Number(request, "x", out double x) || !Number(request, "z", out double z)) return Error(id, "A point request needs numeric \"x\" and \"z\".");
            bool hasY = Number(request, "y", out double y);
            var target = new Vector3((float)x, hasY ? (float)y : here.Position.Y, (float)z);
            // Without a height, search a tall box so the floor nearest the player's height wins.
            var route = nav.Route(here.Position, target, hasY ? NavWorld.WideExtents : new Vector3(96, 2048, 96), out bool reached);
            if (route.Count == 0) return Error(id, "No route: the player or the point is off the navmesh.");
            return Write(id, here, nav, json => WritePath(json, route, reached));
        }
        catch (JsonException error) { return Error(id, "Unreadable request: " + error.Message); }
    }

    private void WriteExitFields(Utf8JsonWriter json, Exit exit, NavLocation here)
    {
        var p = exit.Feature.Position;
        json.WriteString("name", exit.Feature.Name);
        WritePoint(json, "position", p);
        WriteNullable(json, "index", exit.Index);
        WriteNullable(json, "nextLevel", exit.NextLevel);
        if (exit.NextLevel is int next && _worlds.WorldName(next) is string name) json.WriteString("nextLevelName", name); else json.WriteNull("nextLevelName");
        WriteNullable(json, "nextLevelStartIndex", exit.StartIndex);
        json.WriteBoolean("destinationKnown", exit.DestinationKnown);
        json.WriteNumber("bearing", Round(BearingTo(here.Position, p)));
        json.WriteNumber("distance", Round(PointNavigation.Distance(here.Position, p)));
    }

    private static void WritePath(Utf8JsonWriter json, IReadOnlyList<Vector3> path, bool complete)
    {
        json.WriteStartArray("path");
        foreach (var c in path) { json.WriteStartArray(); json.WriteNumberValue(Round(c.X)); json.WriteNumberValue(Round(c.Y)); json.WriteNumberValue(Round(c.Z)); json.WriteEndArray(); }
        json.WriteEndArray();
        json.WriteBoolean("complete", complete);
        json.WriteNumber("length", Round(NavWorld.Length(path)));
    }

    private string Write(JsonElement? id, NavLocation here, NavWorld nav, Action<Utf8JsonWriter> body) => Line(json =>
    {
        json.WriteBoolean("ok", true);
        if (id is { } value) { json.WritePropertyName("id"); value.WriteTo(json); }
        json.WriteNumber("world", here.World);
        json.WriteString("worldName", nav.World.Summary.Name);
        json.WriteString("mesh", _worlds.LastSource);
        WritePoint(json, "from", here.Position);
        body(json);
    });

    public static string Error(JsonElement? id, string message) => Line(json =>
    {
        json.WriteBoolean("ok", false);
        if (id is { } value) { json.WritePropertyName("id"); value.WriteTo(json); }
        json.WriteString("error", string.IsNullOrWhiteSpace(message) ? "Unknown error." : message);
    });

    private static string Line(Action<Utf8JsonWriter> body)
    {
        using var stream = new MemoryStream(1024);
        using (var json = new Utf8JsonWriter(stream)) { json.WriteStartObject(); body(json); json.WriteEndObject(); }
        return Encoding.UTF8.GetString(stream.GetBuffer(), 0, (int)stream.Length);
    }

    private static void WritePoint(Utf8JsonWriter json, string name, Vector3 p)
    {
        json.WriteStartArray(name); json.WriteNumberValue(Round(p.X)); json.WriteNumberValue(Round(p.Y)); json.WriteNumberValue(Round(p.Z)); json.WriteEndArray();
    }

    private static void WriteNullable(Utf8JsonWriter json, string name, int? value)
    { if (value is int v) json.WriteNumber(name, v); else json.WriteNull(name); }

    private static double Round(float value) => Math.Round(value + 0.0, 2) + 0.0;   // + 0.0 turns -0 into 0
    private static double Round(double value) => Math.Round(value, 2) + 0.0;

    private static int? Int(EnvironmentFeature feature, string key) =>
        feature.Properties.TryGetValue(key, out var text) && int.TryParse(text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int value) ? value : null;

    private static bool Number(JsonElement request, string name, out double value)
    {
        value = 0;
        return request.TryGetProperty(name, out var element) && element.ValueKind == JsonValueKind.Number && element.TryGetDouble(out value) && double.IsFinite(value);
    }

    /// <summary>Ground bearing from one point to another: 0 = -Z, 90 = +X (the telemetry heading convention).</summary>
    public static float BearingTo(Vector3 from, Vector3 to) => CoordinateRecording.HeadingDegrees(new Vector3(to.X - from.X, 0, to.Z - from.Z));

    public static double AngleBetween(double a, double b) { double d = Math.Abs(((a - b) % 360 + 540) % 360 - 180); return d; }

    private static (string, int) NaturalKey(string name)
    {
        int digits = name.Length; while (digits > 0 && char.IsDigit(name[digits - 1])) digits--;
        return (name[..digits].ToLowerInvariant(), int.TryParse(name[digits..], out int n) ? n : -1);
    }
}
