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
    public const float MinDistance = 40, MaxDistance = 6000, DefaultDistance = 150;

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

/// <summary>
/// When Shift may stay down. It runs at about 300 units/s until stamina empties, then crawls at 35 (live, 1 Nov), and the
/// game's stamina is not read, so a run gone slow is the sign. Then it rests with W alone. Not yet set live.
/// </summary>
internal sealed class SprintGuard
{
    public const float CrawlBelow = 100;
    public const double WindowSeconds = 1, RestSeconds = 15;
    private Vector3? _from;
    private double _at, _restUntil = double.MinValue;

    /// <summary>Call every tick. <paramref name="running"/> is whether Shift and W are both down now.</summary>
    public bool MayRun(double now, Vector3 position, bool running)
    {
        if (now < _restUntil) return false;
        if (!running || _from == null || now - _at > WindowSeconds * 3) { _from = running ? position : null; _at = now; return true; }
        if (now - _at < WindowSeconds) return true;
        bool crawling = PointNavigation.Distance(position, _from.Value) / (now - _at) < CrawlBelow;
        _from = position; _at = now;
        if (!crawling) return true;
        _from = null;
        _restUntil = now + RestSeconds;
        return false;
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

/// <summary>The healer's walk: after the target when it gets further than the distance, and back only when it is right on top of you.</summary>
internal sealed class HoldDistance(float distance)
{
    public const float MinDistance = 40, MaxDistance = 400, StartOff = 14, StopOff = 6, CastBeyond = 60,
        RunBeyond = 250;   // Shift sprints and burns stamina, and with none left it crawls at 35 units/s (live, 1 Nov): only to catch up
    /// <summary>Facing further off than this, W would walk past the target.</summary>
    public const float MaxYawToWalk = 0.35f;
    /// <summary>The other client's position against the same character in this client's list, which arrives late.</summary>
    public const float SameSpot = 60;

    public float Distance { get; } = Math.Clamp(distance, MinDistance, MaxDistance);
    private int _forward;

    /// <summary>Which way to walk (-1, 0, 1) and whether to run. A key once down stays down until nearly there, so it does not chatter.</summary>
    public (int Forward, bool Run) Keys(float away, float yawError)
    {
        float off = away - Distance;
        _forward = away < MinDistance ? -1 : off >= StartOff ? 1 : off < StopOff ? 0 : Math.Max(_forward, 0);
        if (_forward > 0 && MathF.Abs(yawError) > MaxYawToWalk) _forward = 0;
        return (_forward, off > RunBeyond);
    }

    public bool InReach(float away) => away - Distance < CastBeyond;

    /// <summary>Only your own second client is healed: these are that client's position and the target's, in one sector.</summary>
    public static bool SameCharacter(Vector3 otherClient, int? otherSector, Vector3 target, int? sector) =>
        otherSector == sector && sector != null && PointNavigation.Distance(otherClient, target) <= SameSpot;
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
    public const float Deadband = 0.006f, FineDeadband = 0.0025f, AimWithin = 15, FarAbove = 0.35f, FarShare = 0.5f, NearShare = 0.3f, MaxNearTurn = 0.1f;

    /// <summary>The turn for this tick: part of the error, so the camera settles on the target instead of swinging past it.
    /// Given the range, the deadband narrows to stay on the body: 0.006 radians is 36 units at 6,000, more than half a mob's width.</summary>
    public static float Turn(float error, float away = 0)
    {
        float size = MathF.Abs(error);
        if (size < (away > 0 ? Math.Clamp(AimWithin / away, FineDeadband, Deadband) : Deadband)) return 0;
        return size > FarAbove ? error * FarShare : Math.Clamp(error * NearShare, -MaxNearTurn, MaxNearTurn);
    }

    /// <summary>A turn in mouse pixels. Never rounded away to nothing, or a small error at long range is never corrected.</summary>
    public static int Pixels(float turn, float gain)
    {
        int pixels = (int)MathF.Round(turn / gain);
        return pixels == 0 && turn != 0 ? MathF.Sign(turn / gain) : pixels;
    }

    /// <summary>A position is at the feet (seen live: aiming there shot at a mob's feet and sometimes missed): this is about the middle of a standing character. The list gives no height, so small mobs get the same.</summary>
    public const float BodyMiddle = 50;
    /// <summary>Where shots go, above a mob's feet. At 50 the crosshair sat on its lower legs (screenshot, 1 Nov). Not yet tried live.</summary>
    public const float ShotHeight = 75;
    public const double CastEverySeconds = 30, CastHoldSeconds = 1.5;

    /// <summary>The first aim must land before the left button goes down: the test moves leave the camera well off the target.</summary>
    public const float OnTargetWithin = 0.035f;   // 2 degrees

    public static bool OnTarget(float yawError, float pitchError) =>
        MathF.Abs(yawError) < OnTargetWithin && MathF.Abs(pitchError) < OnTargetWithin;

    /// <summary>The left button is held on NPCs only: on a real player it would be an aimbot.</summary>
    public static bool MayHold(EntityKind kind) => kind == EntityKind.Npc;

    /// <summary>A player gets one click every 30 s, and only the fighter the user named. No other client can vouch for it from inside a VM.</summary>
    public static bool IsFighter(string? named, string name, EntityKind kind) =>
        kind == EntityKind.Player && string.Equals(named?.Trim(), name.Trim(), StringComparison.OrdinalIgnoreCase);

    /// <summary>The shortest turn between two headings.</summary>
    public static float Between(float from, float to) => MathF.Atan2(MathF.Sin(to - from), MathF.Cos(to - from));

    /// <summary>The flat direction of a heading.</summary>
    public static Vector3 Facing(float yaw) => new(MathF.Cos(yaw), 0, MathF.Sin(yaw));

    /// <summary>Radians above level of the target, from the eye, within what the game allows.</summary>
    public static float PitchTo(Vector3 from, Vector3 target) =>
        Math.Clamp(MathF.Atan2(target.Y - (from.Y + EyeHeight), Math.Max(1, PointNavigation.Distance(from, target))), -MaxPitch, MaxPitch);
}

/// <summary>Has the game's target bar been up lately? It flickers as a shot throws the crosshair, so one gap proves nothing.</summary>
internal sealed class SightWatch(double holdSeconds = 1)
{
    public double SeenAt { get; private set; } = double.NegativeInfinity;
    public bool Showing { get; private set; }

    public void Update(double now, bool showing)
    {
        Showing = showing;
        if (showing) SeenAt = now;
    }

    public bool Seen(double now) => now - SeenAt <= holdSeconds;
}

/// <summary>Back away from a mob with the crosshair on it until the game stops targeting it, then forward until it targets it again.</summary>
internal sealed class BackOff(bool wanted)
{
    public enum Phase { Waiting, Backing, Returning, Done }
    /// <summary>S is slow, about 30 units/s, so 180 s is about 5,400 units: nothing is fired until this ends, for a safe distance first.</summary>
    public const double MostSeconds = 180, ReturnSeconds = 5, StuckSeconds = 3;
    /// <summary>A mob this much closer than when backing began has noticed you: shoot it.</summary>
    public const float MobCloser = 60, StuckBelow = 10;
    private double _from, _stuckAt;
    private float _startAway;
    private Vector3 _stuckFrom;

    public Phase Now { get; private set; } = wanted ? Phase.Waiting : Phase.Done;
    public float? Limit { get; private set; }

    public void Update(double now, bool seen, bool showing, float away, Vector3 at)
    {
        switch (Now)
        {
            case Phase.Waiting:
                if (seen) { Now = Phase.Backing; _from = _stuckAt = now; _startAway = away; _stuckFrom = at; }
                break;
            case Phase.Backing:
                if (!seen) { Limit = away; Now = Phase.Returning; _from = now; }
                else if (now - _from > MostSeconds || away < _startAway - MobCloser) Now = Phase.Done;
                else if (now - _stuckAt >= StuckSeconds)
                {
                    if (PointNavigation.Distance(at, _stuckFrom) < StuckBelow) Now = Phase.Done;
                    _stuckAt = now; _stuckFrom = at;
                }
                break;
            case Phase.Returning:
                if (showing || now - _from > ReturnSeconds) Now = Phase.Done;
                break;
        }
    }
}

/// <summary>What a healer casts next: the heal in slot 1 every 30 s and the shields in slots 2 and 3 every 120 s, on the fighter and on itself.</summary>
internal sealed class CastCycle
{
    public const double HealEvery = 30, ShieldEvery = 120, SlotWait = 2, BetweenCasts = 0.5;
    /// <summary>Radians above level: nobody is up there, so the spell lands on the caster.</summary>
    public const float SkyPitch = 0.65f;

    public sealed class Cast(int slot, bool onFighter, double every)
    {
        public int Slot { get; } = slot;
        public bool OnFighter { get; } = onFighter;
        public double Every { get; } = every;
        public double Next { get; set; }
    }

    private readonly Cast[] _casts =
    [
        new(1, true, HealEvery), new(1, false, HealEvery),
        new(2, true, ShieldEvery), new(3, true, ShieldEvery), new(2, false, ShieldEvery), new(3, false, ShieldEvery),
    ];

    /// <summary>The first cast due, heals before shields. Null until one is.</summary>
    public Cast? Due(double now) => _casts.FirstOrDefault(c => now >= c.Next);

    public void Done(Cast cast, double now) => cast.Next = now + cast.Every;

    /// <summary>
    /// The slot key to press to get a cast's slot in hand. A slot's own key puts it away, and a new run can't know what is
    /// out, so it first presses another slot: that ends with the right one out whichever was.
    /// </summary>
    public static int KeyFor(int slot, int? inHand) => inHand == null ? (slot == 1 ? 2 : 1) : slot;
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
