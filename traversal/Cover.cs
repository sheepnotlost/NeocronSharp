using System.Numerics;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>Where to run when hurt: a spot on the ground no mob can see, because a hill or a prop is in the way, and the nearest such.</summary>
internal sealed class Cover(float[]? heights, ShotLine shots)
{
    public const float NearestSpot = 600, FarthestSpot = 2400, Ring = 300, SafeFrom = 1200, LooksThisFar = 6000, MostRun = 3500;
    private const int Bearings = 16;
    private const float EdgeOfCell = 300, Clearance = 10;
    private static readonly Vector3 Eye = new(0, CameraAim.EyeHeight, 0);

    /// <summary>Does a hill or a prop stand between a mob and this spot?</summary>
    public bool Hidden(Vector3 mob, Vector3 spot)
    {
        Vector3 from = mob + Eye, to = spot + Eye;
        if (shots.Blocker(from, to) != null) return true;
        if (heights == null) return false;
        int steps = (int)(PointNavigation.Distance(from, to) / TerrainCell.Spacing);
        for (int i = 1; i < steps; i++)
        {
            var point = Vector3.Lerp(from, to, (float)i / steps);
            if (TerrainCell.Sample(heights, point.X, point.Z) > point.Y + Clearance) return true;
        }
        return false;
    }

    /// <summary>Spots around you, best first: seen by the fewest mobs, then far enough from them, then the shortest run.</summary>
    public IEnumerable<Vector3> Spots(Vector3 me, IReadOnlyList<Vector3> mobs, Func<Vector3, Vector3?> ground)
    {
        float Nearest(Vector3 p) => mobs.Count == 0 ? float.MaxValue : mobs.Min(m => PointNavigation.Distance(m, p));
        float away = Math.Min(SafeFrom, Nearest(me));
        var found = new List<(Vector3 Spot, int Seen, bool Near, float Run)>();
        for (float radius = NearestSpot; radius <= FarthestSpot; radius += Ring)
            for (int i = 0; i < Bearings; i++)
            {
                float angle = i * MathF.Tau / Bearings;
                var wanted = me + new Vector3(MathF.Cos(angle), 0, MathF.Sin(angle)) * radius;
                if (MathF.Abs(wanted.X) > TerrainCell.Half - EdgeOfCell || MathF.Abs(wanted.Z) > TerrainCell.Half - EdgeOfCell) continue;   // Over the edge is another zone.
                if (ground(wanted) is not { } spot || Nearest(spot) < away) continue;
                found.Add((spot, mobs.Count(m => PointNavigation.Distance(m, spot) <= LooksThisFar && !Hidden(m, spot)), Nearest(spot) < SafeFrom, radius));
            }
        return found.OrderBy(f => f.Seen).ThenBy(f => f.Near).ThenBy(f => f.Run).Select(f => f.Spot);
    }
}
