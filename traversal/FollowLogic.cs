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

/// <summary>Sudden moves of your character: one is the game correcting it, several close together are not.</summary>
internal sealed class PositionJumps
{
    public const int Limit = 3;
    public const double WithinSeconds = 10;
    private readonly Queue<double> _at = new();

    /// <summary>Count a jump at this time; true when it makes too many.</summary>
    public bool TooMany(double now)
    {
        while (_at.Count > 0 && now - _at.Peek() > WithinSeconds) _at.Dequeue();
        _at.Enqueue(now);
        return _at.Count >= Limit;
    }
}

/// <summary>
/// Walking in a formation with the camera fixed: where a place beside the target is, in the camera's own forward and
/// right, and which keys reach it. Right is measured live: D moves along (-forward.Z, forward.X).
/// </summary>
internal sealed class Formation
{
    public const float StartOff = 14, StopOff = 6, RunBeyond = 90;
    /// <summary>A cast needs the target under the crosshair: this far off sideways misses a body, further along the view does not.</summary>
    public const float AimRight = 14, AimForward = 40;

    private static (float Forward, float Right) Split(Vector3 facing, Vector3 offset) =>
        (offset.X * facing.X + offset.Z * facing.Z, -offset.X * facing.Z + offset.Z * facing.X);

    /// <summary>Where the target is from you, in the camera's terms.</summary>
    public static (float Forward, float Right) Place(Vector3 facing, Vector3 you, Vector3 target) => Split(facing, target - you);

    /// <summary>How far you are from that place now: positive forward and right mean walk that way.</summary>
    public static (float Forward, float Right) Error(Vector3 facing, Vector3 you, Vector3 target, (float Forward, float Right) place)
    {
        var now = Split(facing, target - you);
        return (now.Forward - place.Forward, now.Right - place.Right);
    }

    /// <summary>The place is only worth keeping with the target about under the crosshair: nothing here can turn the camera.</summary>
    public static bool Ahead((float Forward, float Right) place) => place.Forward > 0 && MathF.Abs(place.Right) < place.Forward / 4;

    public static bool InPlace((float Forward, float Right) error) => MathF.Abs(error.Right) < AimRight && MathF.Abs(error.Forward) < AimForward;

    private int _forward, _right;

    private static int Axis(float error, int was) =>
        MathF.Abs(error) >= StartOff ? Math.Sign(error) : MathF.Abs(error) < StopOff ? 0 : was;

    /// <summary>Which way to go on each axis (-1, 0, 1) and whether to run. A key once down stays down until nearly there, so it does not chatter.</summary>
    public (int Forward, int Right, bool Run) Keys((float Forward, float Right) error)
    {
        _forward = Axis(error.Forward, _forward);
        _right = Axis(error.Right, _right);
        return (_forward, _right, MathF.Max(MathF.Abs(error.Forward), MathF.Abs(error.Right)) > RunBeyond);
    }
}

/// <summary>How the camera turns to keep facing a target, left and right and up and down.</summary>
internal static class CameraAim
{
    /// <summary>
    /// How far above your position the crosshair's line runs (the view sits behind and above you in third
    /// person, so it passes over your head): set live on 31 Oct until the game's own target label named the
    /// spider being followed. The game stops the view at <see cref="MaxPitch"/> up or down.
    /// </summary>
    public const float EyeHeight = 82, MaxPitch = 43 * MathF.PI / 180;
    public const float Deadband = 0.006f, FarAbove = 0.35f, FarShare = 0.5f, NearShare = 0.3f, MaxNearTurn = 0.1f;

    /// <summary>The turn for this tick: part of the error, so the camera settles on the target instead of swinging past it.</summary>
    public static float Turn(float error)
    {
        float size = MathF.Abs(error);
        if (size < Deadband) return 0;
        return size > FarAbove ? error * FarShare : Math.Clamp(error * NearShare, -MaxNearTurn, MaxNearTurn);
    }

    /// <summary>The first aim must land before the left button goes down: the test moves leave the camera well off the target.</summary>
    public const float OnTargetWithin = 0.035f;   // 2 degrees

    public static bool OnTarget(float yawError, float pitchError) =>
        MathF.Abs(yawError) < OnTargetWithin && MathF.Abs(pitchError) < OnTargetWithin;

    /// <summary>The left button is held on NPCs only: on a real player it would be an aimbot.</summary>
    public static bool MayHold(EntityKind kind) => kind == EntityKind.Npc;

    /// <summary>The flat direction of a heading.</summary>
    public static Vector3 Facing(float yaw) => new(MathF.Cos(yaw), 0, MathF.Sin(yaw));

    /// <summary>Radians above level of the target, from the eye, within what the game allows.</summary>
    public static float PitchTo(Vector3 from, Vector3 target) =>
        Math.Clamp(MathF.Atan2(target.Y - (from.Y + EyeHeight), Math.Max(1, PointNavigation.Distance(from, target))), -MaxPitch, MaxPitch);
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
