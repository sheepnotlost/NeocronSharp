using System.Numerics;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// When to walk after a followed actor and when to stand: stop once within
/// <see cref="Distance"/>, and only set off again once the gap has grown past
/// <see cref="Resume"/>, so a target shuffling on the spot does not make the walker twitch.
/// </summary>
internal sealed class FollowBand
{
    public const float MinDistance = 40, MaxDistance = 2000, DefaultDistance = 150;

    public float Distance { get; }
    public float Resume { get; }
    public bool Moving { get; private set; }

    public FollowBand(float distance)
    {
        Distance = Math.Clamp(float.IsFinite(distance) ? distance : DefaultDistance, MinDistance, MaxDistance);
        Resume = Distance + Math.Max(50, Distance / 3);
    }

    /// <summary>The first reading: walk if the target is any farther than the distance.</summary>
    public bool Start(float gap) => Moving = gap > Distance;

    /// <summary>The next reading; returns whether to walk.</summary>
    public bool Update(float gap)
    {
        if (Moving) { if (gap <= Distance) Moving = false; }
        else if (gap > Resume) Moving = true;
        return Moving;
    }
}

/// <summary>Why the follow route is planned again (None: keep the current one).</summary>
internal enum FollowReplan { None, First, OffRoute, TargetMoved, NearRouteEnd, Refresh }

internal static class FollowLogic
{
    /// <summary>Target-moved replans are at least this far apart (off-route ones are not held back).</summary>
    public const double MinReplanSeconds = 0.4;
    /// <summary>A plan older than this is renewed if the target moved at all.</summary>
    public const double RefreshSeconds = 3;
    /// <summary>Moves smaller than this never count (the game jitters other actors' positions).</summary>
    public const float Jitter = 8;

    /// <summary>
    /// How far the walker still is from the target: the walk left on the route, or the straight
    /// distance less the part no route can cover (<paramref name="miss"/>: from the route's end,
    /// the nearest floor, to the target standing off the mesh, say behind a counter), whichever is more.
    /// With no route it is the straight distance.
    /// </summary>
    /// <summary>
    /// The straight distance to the target on the flat, plus any height difference beyond one floor:
    /// a target on the floor above (reached by a gravity lift) is not "within 150 units".
    /// </summary>
    public static float Straight(Vector3 from, Vector3 to) =>
        PointNavigation.Distance(from, to) + Math.Max(0, MathF.Abs(to.Y - from.Y) - Simulator.SameFloor);

    public static float Gap(float straight, float? remaining, float miss) =>
        remaining is { } r ? Math.Max(r, Math.Max(0, straight - Math.Max(0, miss))) : straight;

    /// <summary>How far the target may move from where the route was planned to before the route is renewed: a quarter of the gap, 32-250 units.</summary>
    public static float MoveThreshold(float gap) => Math.Clamp(gap * 0.25f, 32, 250);

    /// <param name="hasPlan">A route is being followed.</param>
    /// <param name="targetShift">Planar distance the target has moved since the route was planned.</param>
    /// <param name="gap">Current <see cref="Gap"/>.</param>
    /// <param name="offRoute">Planar distance of the walker off the route.</param>
    /// <param name="remaining">Walk left on the route.</param>
    /// <param name="sincePlan">Seconds since the route was planned.</param>
    public static FollowReplan Decide(bool hasPlan, float targetShift, float gap, float offRoute, float remaining, double sincePlan)
    {
        if (!hasPlan) return FollowReplan.First;
        if (offRoute > Simulator.OffRouteLimit) return FollowReplan.OffRoute;
        if (sincePlan < MinReplanSeconds || targetShift <= Jitter) return FollowReplan.None;
        if (targetShift > MoveThreshold(gap)) return FollowReplan.TargetMoved;
        // About to run out of route while the target is elsewhere: renew before stopping short.
        if (remaining < 40) return FollowReplan.NearRouteEnd;
        return sincePlan > RefreshSeconds ? FollowReplan.Refresh : FollowReplan.None;
    }

    /// <summary>
    /// A target that vanished near a zone exit most likely crossed it. Returns the nearest exit
    /// (arrival record) within <paramref name="within"/> units of where it was last seen, if any.
    /// </summary>
    public static (Vector3 Position, int To)? NearestExit(Vector3 lastSeen, IEnumerable<(Vector3 Position, int To)> exits, float within = 500) =>
        exits.Where(e => PointNavigation.Distance(e.Position, lastSeen) <= within)
            .OrderBy(e => PointNavigation.Distance(e.Position, lastSeen))
            .Select(e => ((Vector3, int)?)e).FirstOrDefault();
}
