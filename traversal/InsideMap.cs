using System.Globalization;
using System.Numerics;
using System.Text;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// The inside of a place (a cave, a dungeon) as a top-down map: its walkable floor, the part you can reach
/// from where you arrive, the doors out, the arrival spots and the supply boxes. Offline; reads the
/// world's level and spawn files only. Written for Outdoor Cave 3 (the Dangerous Canyon Cave behind F 12), 5 Nov.
/// </summary>
internal static class InsideMap
{
    /// <summary>A marked spot: what it is, where, and its colour on the map.</summary>
    public sealed record Mark(string Kind, string Name, Vector3 Position, string Colour);

    /// <summary>What the map shows, with the counts the command prints.</summary>
    public sealed record Result(NavWorld Nav, List<Mark> Marks, HashSet<long> Island, int Polygons, int Reached, List<(Mark Door, List<Vector3> Route, bool Complete)> Routes);

    // pak_worldmodels types: 20 entrance/exit door, 18 sewer entrance, 29 underground exit, 21 arrival spot ("no9").
    private static readonly HashSet<int> DoorTypes = new() { 18, 20, 29 };
    private const int ArrivalType = 21;

    public static Result Build(string install, NavWorld nav, Travel travel)
    {
        int world = nav.World.Summary.WorldId;
        var models = NpcDefinitions.Parse(File.ReadAllBytes(Path.Combine(install, "definitions", "pak_worldmodels.csv")));
        static int Int(Dictionary<string, string> row, string field) => int.TryParse(row.GetValueOrDefault(field), out int n) ? n : 0;
        var marks = new List<Mark>();
        foreach (var (_, model, at) in new WorldObjects(install, travel).Placed(world))
        {
            if (!models.TryGetValue(model, out var row)) continue;
            string name = string.Join(' ', (row.GetValueOrDefault("Name") ?? "").Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
            int type = Int(row, "Type");
            if (DoorTypes.Contains(type)) marks.Add(new("door", name, at, "#f44"));
            else if (type == ArrivalType) marks.Add(new("arrival", $"arrival {Int(row, "Value")}", at, "#fff"));
            else if (name.Contains("SUPPLY", StringComparison.OrdinalIgnoreCase)) marks.Add(new("box", name, at, "#fc3"));
        }
        var polys = nav.Polygons();
        var arrival = marks.FirstOrDefault(m => m.Kind == "arrival") ?? marks.FirstOrDefault(m => m.Kind == "door");
        var island = arrival == null ? new HashSet<long>() : nav.Island(arrival.Position);
        int reached = polys.Count(p => nav.OnIsland(p.Aggregate(Vector3.Zero, (a, b) => a + b) / p.Length, island, reach: 8));
        var routes = new List<(Mark, List<Vector3>, bool)>();
        if (arrival != null)
            foreach (var door in marks.Where(m => m.Kind is "door" or "box"))
            {
                var route = nav.RouteNear(arrival.Position, door.Position, out bool complete);
                routes.Add((door, route, complete));
            }
        return new(nav, marks, island, polys.Count, reached, routes);
    }

    /// <summary>Top-down SVG: reachable floor green (lighter is higher), floor you cannot reach from the arrival grey, the marks on top.</summary>
    public static string Svg(Result r)
    {
        var polys = r.Nav.Polygons();
        var all = polys.SelectMany(p => p).Concat(r.Marks.Select(m => m.Position)).ToList();
        float x0 = all.Min(p => p.X), x1 = all.Max(p => p.X), z0 = all.Min(p => p.Z), z1 = all.Max(p => p.Z);
        float y0 = polys.Count > 0 ? polys.Min(p => p.Min(q => q.Y)) : 0, y1 = polys.Count > 0 ? polys.Max(p => p.Max(q => q.Y)) : 1;
        static string F(float f) => f.ToString("0.#", CultureInfo.InvariantCulture);
        // Seen from above with north up: x to the right, z up (as the game's map).
        string P(Vector3 p) => $"{F(p.X - x0)},{F(z1 - p.Z)}";
        float w = x1 - x0, h = z1 - z0;
        var sb = new StringBuilder();
        sb.AppendLine($"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"-60 -160 {F(w + 760)} {F(h + 260)}\" style=\"background:#111\">");
        string title = $"{r.Nav.World.Summary.Name} (world {r.Nav.World.Summary.WorldId}): {r.Reached} of {r.Polygons} floor pieces reachable from the arrival";
        sb.AppendLine($"<text x=\"0\" y=\"-90\" fill=\"#ddd\" font-size=\"56\" font-family=\"sans-serif\">{System.Security.SecurityElement.Escape(title)}</text>");
        sb.AppendLine("<text x=\"0\" y=\"-30\" fill=\"#aaa\" font-size=\"40\" font-family=\"sans-serif\">green: walkable from the arrival (lighter = higher) · grey: not reached · red: doors · white: arrival · yellow: supply boxes and routes</text>");
        foreach (var poly in polys.OrderBy(p => p.Average(q => q.Y)))
        {
            var centre = poly.Aggregate(Vector3.Zero, (a, b) => a + b) / poly.Length;
            bool on = r.Nav.OnIsland(centre, r.Island, reach: 8);
            float t = (poly.Average(q => q.Y) - y0) / Math.Max(1, y1 - y0);
            int g = (int)(80 + 150 * t);
            string fill = on ? $"rgb(30,{g},{g / 2 + 40})" : $"rgb({g / 3 + 40},{g / 3 + 40},{g / 3 + 40})";
            sb.AppendLine($"<polygon points=\"{string.Join(" ", poly.Select(P))}\" fill=\"{fill}\" stroke=\"#0a0a0a\" stroke-width=\"1\"/>");
        }
        foreach (var (_, route, complete) in r.Routes.Where(x => x.Route.Count > 1))
            sb.AppendLine($"<polyline points=\"{string.Join(" ", route.Select(P))}\" fill=\"none\" stroke=\"#fc3\" stroke-width=\"8\" opacity=\"{(complete ? "0.7" : "0.3")}\"{(complete ? "" : " stroke-dasharray=\"30 20\"")}/>");
        foreach (var m in r.Marks)
        {
            float cx = m.Position.X - x0, cy = z1 - m.Position.Z;
            sb.AppendLine($"<circle cx=\"{F(cx)}\" cy=\"{F(cy)}\" r=\"{(m.Kind == "box" ? 22 : 34)}\" fill=\"{m.Colour}\" stroke=\"#000\" stroke-width=\"4\"/>");
            sb.AppendLine($"<text x=\"{F(cx + 44)}\" y=\"{F(cy + 14)}\" fill=\"{m.Colour}\" font-size=\"44\" font-family=\"sans-serif\" stroke=\"#000\" stroke-width=\"8\" paint-order=\"stroke\">{System.Security.SecurityElement.Escape(m.Name)}</text>");
        }
        sb.AppendLine("</svg>");
        return sb.ToString();
    }
}
