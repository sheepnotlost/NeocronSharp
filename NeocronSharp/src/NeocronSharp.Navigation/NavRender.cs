using System.Globalization;
using System.Numerics;
using System.Text;

namespace NeocronSharp.Navigation;

/// <summary>Top-down SVG of a navmesh for checking plans by eye: polygons shaded by height, yellow paths,
/// labelled red markers (e.g. exits) and a white ring for the player. X right, Z down.</summary>
public static class NavRender
{
    public static string Svg(NavWorld nav, IEnumerable<IReadOnlyList<Vector3>> paths, IEnumerable<(Vector3 At, string Label)> markers, Vector3? player = null)
    {
        var src = nav.World.StaticGeometry; var polys = nav.Polygons();
        float x0 = src.Vertices.Min(p => p.X), x1 = src.Vertices.Max(p => p.X), z0 = src.Vertices.Min(p => p.Z), z1 = src.Vertices.Max(p => p.Z);
        float y0 = polys.Count > 0 ? polys.Min(p => p.Min(q => q.Y)) : 0, y1 = polys.Count > 0 ? polys.Max(p => p.Max(q => q.Y)) : 1;
        string F(float f) => f.ToString("0.#", CultureInfo.InvariantCulture);
        string P(Vector3 p) => $"{F(p.X - x0)},{F(p.Z - z0)}";
        string Escape(string text) => System.Security.SecurityElement.Escape(text) ?? "";
        var sb = new StringBuilder();
        sb.AppendLine($"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"-20 -60 {F(x1 - x0 + 40)} {F(z1 - z0 + 80)}\" style=\"background:#111\">");
        sb.AppendLine($"<text x=\"0\" y=\"-20\" fill=\"#ddd\" font-size=\"48\" font-family=\"sans-serif\">{Escape(nav.World.Summary.Name)} - {polys.Count} navmesh polygons (shade = height; X right, Z down)</text>");
        foreach (var poly in polys.OrderBy(p => p.Average(q => q.Y)))
        {
            float h = (poly.Average(q => q.Y) - y0) / Math.Max(1, y1 - y0);
            int g = (int)(70 + 150 * h);
            sb.AppendLine($"<polygon points=\"{string.Join(" ", poly.Select(P))}\" fill=\"rgb(30,{g},{g / 2 + 40})\" stroke=\"#0a0a0a\" stroke-width=\"1\"/>");
        }
        foreach (var route in paths.Where(r => r.Count > 1))
        {
            sb.AppendLine($"<polyline points=\"{string.Join(" ", route.Select(P))}\" fill=\"none\" stroke=\"#fc3\" stroke-width=\"10\"/>");
            foreach (var c in route) sb.AppendLine($"<circle cx=\"{F(c.X - x0)}\" cy=\"{F(c.Z - z0)}\" r=\"9\" fill=\"#fc3\"/>");
        }
        foreach (var (at, label) in markers)
        {
            sb.AppendLine($"<circle cx=\"{F(at.X - x0)}\" cy=\"{F(at.Z - z0)}\" r=\"18\" fill=\"#f44\"/>");
            sb.AppendLine($"<text x=\"{F(at.X - x0 + 24)}\" y=\"{F(at.Z - z0 + 12)}\" fill=\"#fff\" font-size=\"40\" font-family=\"sans-serif\">{Escape(label)}</text>");
        }
        if (player is { } me) sb.AppendLine($"<circle cx=\"{F(me.X - x0)}\" cy=\"{F(me.Z - z0)}\" r=\"30\" fill=\"none\" stroke=\"#fff\" stroke-width=\"8\"/>");
        sb.AppendLine("</svg>");
        return sb.ToString();
    }
}
