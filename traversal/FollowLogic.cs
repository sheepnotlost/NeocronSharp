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
    public const float CrawlBelow = 50;   // Out of stamina is about 35. A faction headquarters' full run is only 80 to 100 (2 Nov).
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

/// <summary>When to act on someone: the proof, or the crosshair having been on them this long since the first look.</summary>
internal sealed class SteadyAim(long ms)
{
    private long? since;

    public bool Ready(long now, bool proof)
    {
        since ??= now;
        return proof || now - since >= ms;
    }
}

/// <summary>The view onto a point in one go: the whole turn at once, then a look once it has landed (a turn shows late), rather than part of it every tick.</summary>
internal sealed class SnapAim
{
    public const float Within = 0.012f, Still = 0.002f;
    public const long LandMs = 600;   // the turn sweeps for up to 350 ms of it
    private const int SteadyReads = 2;
    private float _yaw, _pitch, _sentYaw, _sentPitch;
    private long _sentAt;
    private bool _landing, _read;
    private int _steady;
    public bool Done { get; private set; }

    /// <summary>The turn to send now, nothing while one lands.</summary>
    public (float Yaw, float Pitch) Step(long now, float yawError, float pitchError)
    {
        bool still = _read && MathF.Abs(yawError - _yaw) < Still && MathF.Abs(pitchError - _pitch) < Still;
        (_yaw, _pitch, _read) = (yawError, pitchError, true);
        if (Done) return (0, 0);
        if (_landing)
        {
            bool shown = MathF.Abs(yawError - _sentYaw) >= Still || MathF.Abs(pitchError - _sentPitch) >= Still;
            if (!(shown && still) && now - _sentAt < LandMs) return (0, 0);
            _landing = false;
        }
        if (MathF.Abs(yawError) < Within && MathF.Abs(pitchError) < Within)
        {
            Done = ++_steady >= SteadyReads;
            return (0, 0);
        }
        _steady = 0;
        (_landing, _sentAt, _sentYaw, _sentPitch) = (true, now, yawError, pitchError);
        return (yawError, pitchError);
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

/// <summary>
/// Is a prop from the zone's spawn file in the line of fire? A cactus doesn't always drop the game's target bar, and the
/// shots then only hit it (screenshot, 1 Nov), so the line is checked against the map as well.
/// </summary>
internal sealed class ShotLine(IEnumerable<SectorObjects.Prop> props)
{
    private const float SideStep = 40, FarthestStep = 320;
    private readonly (SectorObjects.Prop Prop, float Radius)[] _props =
        props.Select(p => (p, p.Footprint.Select(c => Vector2.Distance(c, new Vector2(p.Position.X, p.Position.Z))).DefaultIfEmpty().Max())).ToArray();

    /// <summary>The name of the first prop between these points, or null. Nothing behind or beyond them counts.</summary>
    public string? Blocker(Vector3 from, Vector3 to)
    {
        var line = new Vector2(to.X - from.X, to.Z - from.Z);
        float length = line.LengthSquared();
        if (length < 1) return null;
        foreach (var (prop, radius) in _props)
        {
            var offset = new Vector2(prop.Position.X - from.X, prop.Position.Z - from.Z);
            float along = Vector2.Dot(offset, line) / length;
            if (along <= 0 || along >= 1 || Vector2.Distance(offset, line * along) > radius) continue;
            float height = from.Y + (to.Y - from.Y) * along;
            if (height >= prop.Bottom && height <= prop.Top) return prop.Name;
        }
        return null;
    }

    /// <summary>The shortest step to the right (or left, negative) that clears the line, or null if nothing near does.</summary>
    public float? ClearSide(Vector3 from, Vector3 to)
    {
        var right = Vector3.Normalize(new Vector3(to.Z - from.Z, 0, from.X - to.X));
        for (float step = SideStep; step <= FarthestStep; step += SideStep)
            foreach (float side in new[] { step, -step })
                if (Blocker(from + right * side, to) == null) return side;
        return null;
    }
}

/// <summary>
/// The aim on a mob, put right by what the screen shows. Memory gives where its feet are, and in third person the
/// crosshair's line starts above and behind you, so aiming at a height above them missed small mobs: a Genotoxic Parasite
/// was passed over, under, and never met (videos, 6 Nov). The game marks a mob near the crosshair with its health box and
/// red corner brackets round the body (<see cref="TargetLock"/>), so each look learns how far the body is drawn from the
/// memory point, and the aim keeps that correction while memory follows the mob as it moves. With no mark seen for a moment
/// it looks round the point in small steps until one shows. Shots go only while the crosshair is inside the brackets.
/// </summary>
internal sealed class ScreenAim
{
    /// <summary>Above the feet in memory: the rough aim the screen puts right.</summary>
    public const float MemoryHeight = 30;
    /// <summary>Pixels per unit of tangent, of the client height: 90 degrees across at 16:9. Only how fast a correction lands depends on it.</summary>
    public const float Focal = .89f;
    /// <summary>Of each new correction, the share taken; the rest is what was learned before.</summary>
    public const float Smooth = .5f;
    /// <summary>Radians: the least step of the search, and the most a correction may be (anything further is another mob's mark).</summary>
    public const float SearchStep = .02f, MostSearchStep = .06f, MostOffset = .35f;   // .06: at 50 units, 30/away swung the view 35 degrees a step (7 Nov)
    /// <summary>Of the client height: how far into the brackets' margin still counts as inside them.</summary>
    public const float Margin = .005f;
    public const double SearchAfter = .4, SearchDwell = .25, FireSeconds = .5, SeenSeconds = 1;
    private static readonly (int Yaw, int Pitch)[] Pattern =
        { (0, 0), (0, 1), (0, -1), (1, 0), (-1, 0), (0, 2), (0, -2), (2, 0), (-2, 0), (1, 1), (-1, 1), (1, -1), (-1, -1), (0, 3), (0, -3) };

    private int _step;
    private double _stepAt = -1;
    public (float Yaw, float Pitch) Offset { get; private set; }
    public double SeenAt { get; private set; } = double.NegativeInfinity;
    public double InsideAt { get; private set; } = double.NegativeInfinity;
    public TargetMark? Mark { get; private set; }
    // The brackets' size times the range, from the last look that found all their corners: a mob drawn this big keeps
    // its size when the corners are lost on a red floor, and the label's corner alone would put the aim at its edge.
    private (float Width, float Height)? _sizeAtRange;

    /// <param name="sizeAtRange">The brackets' size times the range, as learned in earlier fights with this mob.</param>
    public ScreenAim((float Width, float Height)? sizeAtRange = null) => _sizeAtRange = sizeAtRange;

    public (float Width, float Height)? SizeAtRange => _sizeAtRange;

    public bool Seen(double now) => now - SeenAt <= SeenSeconds;
    public bool Locked(double now) => now - InsideAt <= FireSeconds;
    public bool Searching(double now) => now - SeenAt > SearchAfter;

    /// <summary>
    /// Units: this close, a mob's health box is drawn above the top of the screen, so no mark shows; but its body is too wide
    /// for the memory point to miss. In first person a Genotoxic Slugger up close went 10 s with no mark, no shot, and the
    /// fight was given up as out of sight (7 Nov).
    /// </summary>
    public const float PointBlank = 110;

    /// <summary>Units over the feet aimed at point blank with no mark: low enough for a parasite flat on the floor.</summary>
    public const float PointBlankHeight = 20;

    /// <summary>Shoot now? Inside the brackets, or point blank.</summary>
    public bool Firing(double now, float away) => Locked(now) || away < PointBlank;

    /// <summary>The error to turn by now, given the error to the memory point (yaw as the mouse gain counts it, pitch up).</summary>
    public (float Yaw, float Pitch) Error(double now, float yawToMemory, float pitchToMemory, float away)
    {
        // Point blank with no mark: the memory point itself, no search. A correction learned further out is an angle that no longer fits.
        if (away < PointBlank && !Seen(now)) { _stepAt = -1; return (yawToMemory, pitchToMemory); }
        float yaw = yawToMemory + Offset.Yaw, pitch = pitchToMemory + Offset.Pitch;
        if (!Searching(now)) { _stepAt = -1; return (yaw, pitch); }
        if (_stepAt < 0) { _stepAt = now; _step = 0; }
        else if (now - _stepAt >= SearchDwell) { _stepAt = now; _step = (_step + 1) % Pattern.Length; }
        float step = Math.Clamp(30 / Math.Max(away, 1), SearchStep, MostSearchStep);
        return (yaw + Pattern[_step].Yaw * step, pitch + Pattern[_step].Pitch * step);
    }

    /// <summary>
    /// A look at the screen: the marks found, and the error to the memory point when it was taken. yawSign is the sign of
    /// the yaw gain: which way a turn to the right counts. True when a mark was taken for the mob.
    /// </summary>
    public bool See(double now, IReadOnlyList<TargetMark> marks, float yawToMemory, float pitchToMemory, int clientHeight, float yawSign, float away = 0)
    {
        if (marks.Count == 0 || clientHeight <= 0) return false;
        float focal = Focal * clientHeight;
        float Across(float yaw) => focal * MathF.Tan(Math.Clamp(yawSign * yaw, -1.2f, 1.2f));
        float Down(float pitch) => -focal * MathF.Tan(Math.Clamp(pitch, -1.2f, 1.2f));
        float ex = Across(yawToMemory + Offset.Yaw), ey = Down(pitchToMemory + Offset.Pitch);
        var mark = marks.MinBy(m => (m.X - ex) * (m.X - ex) + (m.Y - ey) * (m.Y - ey));
        if (away > 0 && mark.Measured) _sizeAtRange = ((mark.Right - mark.Left) * away, (mark.Bottom - mark.Top) * away);
        else if (away > 0 && _sizeAtRange is { } size)
            mark = mark with { Right = mark.Left + size.Width / away, Bottom = mark.Top + size.Height / away };
        var learned = (Yaw: yawSign * MathF.Atan(mark.X / focal) - yawToMemory, Pitch: MathF.Atan(-mark.Y / focal) - pitchToMemory);
        if (MathF.Abs(learned.Yaw) > MostOffset || MathF.Abs(learned.Pitch) > MostOffset) return false;
        Offset = Seen(now) ? (Offset.Yaw + Smooth * (learned.Yaw - Offset.Yaw), Offset.Pitch + Smooth * (learned.Pitch - Offset.Pitch)) : learned;
        SeenAt = now;
        Mark = mark;
        float margin = Margin * clientHeight;
        if (MathF.Abs(mark.X) <= mark.HalfWidth + margin && MathF.Abs(mark.Y) <= mark.HalfHeight + margin) InsideAt = now;
        return true;
    }
}

/// <summary>Has the game's target bar been up lately? It flickers as a shot throws the crosshair, so one gap proves nothing.</summary>
internal sealed class SightWatch(double holdSeconds = 1)
{
    private const double FireSeconds = 0.4;
    public double SeenAt { get; private set; } = double.NegativeInfinity;
    public bool Showing { get; private set; }

    public void Update(double now, bool showing)
    {
        Showing = showing;
        if (showing) SeenAt = now;
    }

    public bool Seen(double now) => now - SeenAt <= holdSeconds;

    /// <summary>Clear to fire: much stricter than <see cref="Seen"/>, as a shot with the bar down hits the scenery.</summary>
    public bool ClearToFire(double now) => now - SeenAt <= FireSeconds;
}

/// <summary>
/// Back away from a mob with the crosshair on it to a safe distance. Stops sooner where the game stops targeting it, then
/// goes forward until it targets it again. Going all the way to the target limit was far too far: over 6,000, and slow (1 Nov).
/// </summary>
internal sealed class BackOff(float until)
{
    public enum Phase { Waiting, Backing, Returning, Done }
    /// <summary>S is slow, about 30 units/s. Nothing is fired until this ends.</summary>
    public const double MostSeconds = 180, ReturnSeconds = 5, StuckSeconds = 3;
    /// <summary>A mob this much closer than when backing began has noticed you: shoot it.</summary>
    public const float MobCloser = 60, StuckBelow = 10;
    private double _from, _stuckAt;
    private float _startAway;
    private Vector3 _stuckFrom;

    public Phase Now { get; private set; } = until > 0 ? Phase.Waiting : Phase.Done;
    public float? Limit { get; private set; }

    public void Update(double now, bool seen, bool showing, float away, Vector3 at)
    {
        switch (Now)
        {
            case Phase.Waiting:
                if (away >= until) Now = Phase.Done;
                else if (seen) { Now = Phase.Backing; _from = _stuckAt = now; _startAway = away; _stuckFrom = at; }
                break;
            case Phase.Backing:
                if (away >= until) Now = Phase.Done;
                else if (!seen) { Limit = away; Now = Phase.Returning; _from = now; }
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

/// <summary>
/// Where a healer stands: beside or behind the fighter, never in front, where it was in the way (7 Nov). The fighter's
/// front is the way they are walking, or, standing, the way to the nearest mob they would be shooting; the game keeps no
/// facing for other characters where it keeps yours. In front, or fallen behind, the healer walks to a spot at the side it
/// is on, swung round to at least 110 degrees from the front, and stops there once it is clear of the front half.
/// </summary>
internal sealed class HealerPlace
{
    public const float FrontHalf = MathF.PI / 2, Clear = 105 * MathF.PI / 180, SideAngle = 115 * MathF.PI / 180;
    public const float Moved = 40, MobRange = 2500, Fighting = 600;
    public const double MovedWithin = 1.5;
    private readonly Queue<(double At, Vector3 Where)> _trail = new();
    private bool _moving;

    /// <summary>The fighter's front on the flat, once known.</summary>
    public Vector3? Front { get; private set; }

    public void Observe(double now, Vector3 fighter, Vector3? nearestMob)
    {
        _trail.Enqueue((now, fighter));
        while (_trail.Count > 0 && now - _trail.Peek().At > MovedWithin) _trail.Dequeue();
        var walked = fighter - _trail.Peek().Where; walked.Y = 0;
        float d = nearestMob is { } m ? PointNavigation.Distance(fighter, m) : float.PositiveInfinity;
        var toMob = nearestMob is { } mob ? mob - fighter : Vector3.Zero; toMob.Y = 0;
        // A mob in a fight's range is the front, whichever way they walk: backing away from one, their walk points away
        // from it, and the healer took the mob's side for their back (7 Nov).
        if (d > 1 && d <= Fighting) Front = Vector3.Normalize(toMob);
        else if (walked.Length() >= Moved) Front = Vector3.Normalize(walked);
        else if (d > 1 && d <= MobRange) Front = Vector3.Normalize(toMob);
    }

    /// <summary>How far round from the fighter's front you are, either way (0 dead ahead, pi behind); null with no front known.</summary>
    public float? Bearing(Vector3 healer, Vector3 fighter)
    {
        var from = healer - fighter; from.Y = 0;
        return Front is { } front && from.Length() > 1 ? MathF.Abs(PointNavigation.SignedAngle(front, from)) : null;
    }

    /// <summary>The spot to walk to, this far from the fighter on your side of them, and never nearer the front than the side.</summary>
    public Vector3 Station(Vector3 healer, Vector3 fighter, float distance)
    {
        var from = healer - fighter; from.Y = 0;
        if (Front is not { } front)
            return from.Length() > 1 ? fighter + Vector3.Normalize(from) * distance : fighter;
        float angle = from.Length() > 1 ? PointNavigation.SignedAngle(front, from) : MathF.PI;
        if (MathF.Abs(angle) < SideAngle) angle = (angle >= 0 ? 1 : -1) * SideAngle;
        float cos = MathF.Cos(angle), sin = MathF.Sin(angle);
        return fighter + new Vector3(front.X * cos - front.Z * sin, 0, front.X * sin + front.Z * cos) * distance;
    }

    /// <summary>Walk now? Sets off when the fighter is past resume or you are in their front half; stops within distance and clear of it.</summary>
    public bool Update(Vector3 healer, Vector3 fighter, float distance, float resume)
    {
        float gap = PointNavigation.Distance(healer, fighter);
        float? bearing = Bearing(healer, fighter);
        if (!_moving) _moving = gap > resume || bearing < FrontHalf;
        else if (gap <= distance && !(bearing < Clear)) _moving = false;
        return _moving;
    }
}

/// <summary>
/// A healer's rounds over a team (the user's ask, 7 Nov): each ally and the healer itself have a clock per spell, and the
/// next cast is whichever is most overdue, so nobody's heal or buff lapses and nobody waits while another is cast on twice.
/// A cast restarts its clock; a reading of the buff timer in an ally's health bar (<see cref="Seen"/>) corrects it, and a
/// reading with the buff gone makes it due now. Ties go to whoever was cast on longest ago, so the order is a round.
/// </summary>
internal sealed class TeamRounds
{
    public const string Self = "";

    public sealed record Spell(int Slot, double Every, bool Heal);

    public sealed class Due(string who, Spell spell, double over)
    {
        public string Who { get; } = who;
        public Spell Spell { get; } = spell;
        /// <summary>Seconds past its time (a spell never cast: a very large number).</summary>
        public double Over { get; } = over;
    }

    private readonly List<string> _who;
    private readonly Spell[] _spells;
    private readonly Dictionary<(string, int), double> _runsOut = [];
    private readonly Dictionary<string, double> _lastCast = [];
    /// <summary>Seconds a spell may have left before it is cast again, so it is renewed before it runs out.</summary>
    public double Margin { get; init; } = 3;

    /// <param name="allies">The team in the order of the first round, without the healer, who comes last.</param>
    public TeamRounds(IEnumerable<string> allies, IEnumerable<Spell> spells)
    {
        _who = allies.Where(a => a != Self).Distinct().Append(Self).ToList();
        _spells = spells.ToArray();
        foreach (var w in _who) _lastCast[w] = double.NegativeInfinity;
    }

    public IReadOnlyList<string> Who => _who;

    private double RunsOut(string who, Spell spell) => _runsOut.TryGetValue((who, spell.Slot), out var t) ? t : double.NegativeInfinity;

    /// <summary>The most overdue cast at <paramref name="now"/>, heals before buffs when equally overdue; null while all are running.</summary>
    public Due? Next(double now)
    {
        Due? best = null;
        foreach (var who in _who)
            foreach (var spell in _spells)
            {
                double left = RunsOut(who, spell) - now;
                if (left > Margin) continue;
                double over = double.IsNegativeInfinity(left) ? double.MaxValue : -left;
                if (best == null || Better(who, spell, over, best)) best = new Due(who, spell, over);
            }
        return best;
    }

    private bool Better(string who, Spell spell, double over, Due best)
    {
        if (over != best.Over) return over > best.Over;
        if (spell.Heal != best.Spell.Heal) return spell.Heal;
        return _lastCast[who] < _lastCast[best.Who];
    }

    /// <summary>A cast went off: its clock restarts and the member goes to the back of the round.</summary>
    public void Cast(string who, Spell spell, double now)
    {
        _runsOut[(who, spell.Slot)] = now + spell.Every;
        _lastCast[who] = now;
    }

    /// <summary>The buff timer read in the member's health bar: seconds left, or null when the buff is not there.</summary>
    public void Seen(string who, Spell spell, double? secondsLeft, double now) =>
        _runsOut[(who, spell.Slot)] = secondsLeft is { } left ? now + left : double.NegativeInfinity;
}

/// <summary>Where a healer waits among a team: behind the middle of the group, away from the mobs, close but not crowding.</summary>
internal static class TeamStation
{
    public const float Close = 160, Crowd = 90;

    /// <summary>
    /// A point <paramref name="distance"/> behind the group's centre (the side away from <paramref name="mob"/>; with no
    /// mob, the healer's own side of the centre), then moved out from any ally nearer than <see cref="Crowd"/>.
    /// </summary>
    public static Vector3 Spot(Vector3 healer, IReadOnlyList<Vector3> allies, Vector3? mob, float distance = Close)
    {
        var centre = Vector3.Zero;
        foreach (var a in allies) centre += a;
        centre /= allies.Count;
        var away = mob is { } m ? centre - m : healer - centre;
        away.Y = 0;
        var direction = away.Length() < 1 ? Vector3.UnitX : Vector3.Normalize(away);
        var spot = centre + direction * distance;
        for (int i = 0; i < 4; i++)
        {
            Vector3? near = null; float nearest = Crowd;
            foreach (var a in allies)
            {
                var d = spot - a; d.Y = 0;
                if (d.Length() < nearest) { nearest = d.Length(); near = a; }
            }
            if (near is not { } crowded) break;
            var push = spot - crowded; push.Y = 0;
            spot = crowded + (push.Length() < 1 ? direction : Vector3.Normalize(push)) * Crowd;
        }
        return spot;
    }
}
