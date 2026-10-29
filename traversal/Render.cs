using System.Globalization;
using System.Numerics;
using System.Text;

namespace NavmeshPrototype;

internal static class Render
{
    /// <summary>Top-down SVG: navmesh shaded by height, yellow route, red ground points, blue trail, white player.</summary>
    public static string Svg(NavWorld nav, IReadOnlyList<Vector3> route, IEnumerable<Vector3> ground, IReadOnlyList<Vector3> trail, Vector3? player = null)
    {
        var src = nav.World.StaticGeometry; var polys = nav.Polygons();
        float x0 = src.Vertices.Min(p => p.X), x1 = src.Vertices.Max(p => p.X), z0 = src.Vertices.Min(p => p.Z), z1 = src.Vertices.Max(p => p.Z);
        float y0 = polys.Count > 0 ? polys.Min(p => p.Min(q => q.Y)) : 0, y1 = polys.Count > 0 ? polys.Max(p => p.Max(q => q.Y)) : 1;
        string F(float f) => f.ToString("0.#", CultureInfo.InvariantCulture);
        // Top-down: X right, Z down (flip to taste once compared with the sector map).
        string P(Vector3 p) => $"{F(p.X - x0)},{F(p.Z - z0)}";
        var sb = new StringBuilder();
        sb.AppendLine($"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"-20 -60 {F(x1 - x0 + 40)} {F(z1 - z0 + 80)}\" style=\"background:#111\">");
        sb.AppendLine($"<text x=\"0\" y=\"-20\" fill=\"#ddd\" font-size=\"48\" font-family=\"sans-serif\">{System.Security.SecurityElement.Escape(nav.World.Summary.Name)} — {polys.Count} navmesh polygons (shade = height)</text>");
        foreach (var poly in polys.OrderBy(p => p.Average(q => q.Y)))
        {
            float h = (poly.Average(q => q.Y) - y0) / Math.Max(1, y1 - y0);
            int g = (int)(70 + 150 * h);
            sb.AppendLine($"<polygon points=\"{string.Join(" ", poly.Select(P))}\" fill=\"rgb(30,{g},{g / 2 + 40})\" stroke=\"#0a0a0a\" stroke-width=\"1\"/>");
        }
        if (trail.Count > 1) sb.AppendLine($"<polyline points=\"{string.Join(" ", trail.Select(P))}\" fill=\"none\" stroke=\"#4af\" stroke-width=\"4\" opacity=\"0.8\"/>");
        if (route.Count > 1) sb.AppendLine($"<polyline points=\"{string.Join(" ", route.Select(P))}\" fill=\"none\" stroke=\"#fc3\" stroke-width=\"10\"/>");
        foreach (var g in ground) sb.AppendLine($"<circle cx=\"{F(g.X - x0)}\" cy=\"{F(g.Z - z0)}\" r=\"14\" fill=\"#f44\"/>");
        if (player is { } me) sb.AppendLine($"<circle cx=\"{F(me.X - x0)}\" cy=\"{F(me.Z - z0)}\" r=\"30\" fill=\"none\" stroke=\"#fff\" stroke-width=\"8\"/>");
        sb.AppendLine("</svg>");
        return sb.ToString();
    }
}
