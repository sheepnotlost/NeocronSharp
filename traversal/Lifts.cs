using System.Globalization;
using System.Numerics;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// One way through a gravity lift: step in at <see cref="Start"/>, ride, step off at <see cref="End"/>.
/// <see cref="Axis"/> is the beam's foot (its BSP entity Origin); the beam runs straight up from it.
/// </summary>
internal sealed record LiftLink(Vector3 Start, Vector3 End, Vector3 Axis, bool Up, string Beam)
{
    public float Rise => End.Y - Start.Y;
}

/// <summary>
/// Gravity lifts ("Polarized Gravity Fields": the blue beams between floors). Each beam is an
/// <c>AntiGravParticle</c> entity in the sector's BSP: Origin = the beam's foot (about 10 units over
/// the floor), Length = how high it goes, Dir = 1 for a beam that carries you up, -1 for one that
/// lowers you. They come in pairs about 100 units apart (Plaza 1 has two pairs). The floors you step
/// off onto are found on the navmesh: the floor nearest the beam at each height it passes, within
/// <see cref="Reach"/>. They become one-way off-mesh links (up beams upward, down beams downward).
/// </summary>
internal static class Lifts
{
    public const float LinkRadius = 24, Reach = 128, MinRise = 48;
    /// <summary>A landing's floor must be a real piece of floor, with room to step on past its edge (a railing top or ledge is not).</summary>
    public const int MinPiece = 8;
    public const float StepOn = 40;

    public sealed record BeamInfo(string Name, Vector3 Origin, bool Up, float Length);

    public static List<BeamInfo> Beams(EnvironmentWorld world) =>
        world.Summary.Features.Where(f => f.Kind == "AntiGravParticle")
            .Select(f => (f, Dir: Num(f.Properties.GetValueOrDefault("Dir")), Length: Num(f.Properties.GetValueOrDefault("Length"))))
            .Where(b => b.Dir != 0 && b.Length > MinRise)
            .Select(b => new BeamInfo(b.f.Name, b.f.Position, b.Dir > 0, b.Length)).ToList();

    /// <summary>Floor at the same height <see cref="StepOn"/> units further from the beam than <paramref name="p"/>: room to land.</summary>
    private static bool Roomy(NavWorld nav, Vector3 p, Vector3 axis)
    {
        var away = new Vector3(p.X - axis.X, 0, p.Z - axis.Z);
        if (away.LengthSquared() < 1e-4f) return false;
        var probe = p + Vector3.Normalize(away) * StepOn;
        return nav.Snap(probe, out _, out var on) && MathF.Abs(on.Y - p.Y) < 24 && PointNavigation.Distance(on, probe) < 8;
    }

    private static float Num(string? s) => float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out float v) && float.IsFinite(v) ? v : 0;

    /// <summary>The lift links of a baked world (one with no links yet).</summary>
    public static List<LiftLink> Links(NavWorld nav)
    {
        var beams = Beams(nav.World);
        var links = new List<LiftLink>();
        if (beams.Count == 0) return links;
        var pieces = nav.Components();
        foreach (var beam in beams)
        {
            var o = beam.Origin;
            float bottom = o.Y - 48, top = o.Y + beam.Length + 24;
            var floors = nav.FloorsIn(new(o.X, (bottom + top) / 2, o.Z), new(Reach, (top - bottom) / 2, Reach))
                .Where(f => pieces.ContainsKey(f.Poly)).ToList();
            // The foot: the floor right under the beam.
            var foot = floors.Where(f => PointNavigation.Distance(f.Point, o) < 32 && MathF.Abs(f.Point.Y - o.Y) < 48)
                .OrderBy(f => PointNavigation.Distance(f.Point, o)).Select(f => (Vector3?)f.Point).FirstOrDefault();
            float floorY = foot?.Y ?? o.Y - 10;
            // Landings: per piece of floor, per height, the point nearest the beam.
            var landings = new List<Vector3>();
            foreach (var piece in floors.Where(f => f.Point.Y > floorY + MinRise && PointNavigation.Distance(f.Point, o) <= Reach && pieces[f.Poly].Size >= MinPiece)
                         .GroupBy(f => pieces[f.Poly].Id))
            {
                var sorted = piece.OrderBy(f => f.Point.Y).ToList();
                var level = new List<Vector3>();
                void Flush()
                {
                    var best = level.Where(p => Roomy(nav, p, o)).OrderBy(p => PointNavigation.Distance(p, o)).Select(p => (Vector3?)p).FirstOrDefault();
                    if (best is { } b) landings.Add(b);
                    level.Clear();
                }
                foreach (var f in sorted)
                {
                    if (level.Count > 0 && f.Point.Y - level[^1].Y > 48) Flush();
                    level.Add(f.Point);
                }
                Flush();
            }
            var stops = new List<Vector3>();
            if (foot is { } footPoint) stops.Add(footPoint);
            // Two landings at nearly one height (two pieces of floor beside the shaft): keep both.
            stops.AddRange(landings.OrderBy(p => p.Y));
            for (int i = 0; i < stops.Count; i++)
                for (int j = 0; j < stops.Count; j++)
                {
                    if (i == j || MathF.Abs(stops[j].Y - stops[i].Y) < MinRise) continue;
                    bool upward = stops[j].Y > stops[i].Y;
                    if (upward == beam.Up) links.Add(new(stops[i], stops[j], o, beam.Up, beam.Name));
                }
        }
        return links;
    }

    /// <summary>The first lift link on a route still ahead of the walker: its index in the corners and its arc position.</summary>
    public static (LiftLink Link, int Index, float Arc)? Ahead(NavWorld nav, RouteFollower route)
    {
        if (nav.Lifts.Count == 0) return null;
        for (int i = 0; i + 1 < route.Corners.Count; i++)
        {
            if (route.ArcAt(i + 1) < route.Progress) continue;
            if (nav.LinkAt(route.Corners[i], route.Corners[i + 1]) is { } link) return (link, i, route.ArcAt(i));
        }
        return null;
    }

    /// <summary>
    /// True when the walker has reached the link's start: beside it on the flat and on its floor, or
    /// already being lifted by an up beam (its edge can catch you before you reach the middle).
    /// </summary>
    public static bool AtStart(LiftLink link, Vector3 position) =>
        PointNavigation.Distance(position, link.Start) <= 48
        && position.Y > link.Start.Y - 60 && position.Y < (link.Up ? link.End.Y : link.Start.Y + 60);
}

/// <summary>
/// Rides one lift link live, with the walker's own guard, wait and turn. A timed step: it fails with
/// a message starting "The gravity lift" when the beam does not move you, stops short, or you
/// cannot step off. Never sends anything but W and mouse turns.
/// </summary>
internal sealed class LiftRider(Func<PlayerSample> guard, Func<int, PlayerSample> wait, Func<int, int, int> turn, SteerInput input,
    TurnController turns, int pulse, Action<string, PlayerSample, object?> record, Action<string> show)
{
    private const int Tick = 33;
    /// <summary>The slowest rise or fall counted on (units per second); sets the time limit.</summary>
    public const float MinSpeed = 60;

    public void Ride(LiftLink link)
    {
        var clock = System.Diagnostics.Stopwatch.StartNew();
        input.Sprint(false);
        var s = guard();
        float startY = s.Position.Y, wanted = link.End.Y;
        var axis = new Vector3(link.Axis.X, s.Position.Y, link.Axis.Z);
        string way = link.Up ? "up" : "down";
        record("lift-start", s, new { link.Beam, way, start = Arr(link.Start), end = Arr(link.End), axis = Arr(link.Axis) });
        show($"Gravity lift: stepping in to go {way} {MathF.Abs(link.Rise):F0} units.");

        // 1. Into the beam: walk to its middle (stop early once it has hold of us).
        long until = clock.ElapsedMilliseconds + 8000;
        while (true)
        {
            s = guard();
            float d = PointNavigation.Distance(s.Position, axis);
            if (d <= 12 || MathF.Abs(s.Position.Y - startY) > 20) break;
            if (clock.ElapsedMilliseconds > until) { input.Walk(false); throw new InvalidOperationException($"The gravity lift could not be stepped into ({d:F0} units from its middle after 8 s)."); }
            float angle = PointNavigation.SignedAngle(s.Forward, axis - s.Position);
            bool walk = MathF.Abs(angle) < Steering.TurnInPlaceAbove;
            input.Walk(walk);
            int pixels = turns.Pixels(walk ? Math.Clamp(angle * 0.5f, -0.15f, 0.15f) : angle * 0.8f, pulse * 2);
            if (pixels != 0) turn(pixels, 2); else wait(Tick);
        }
        input.Walk(false);

        // 2. Face the way off while the beam moves us, so stepping off is one press of W.
        var off = new Vector3(link.End.X, 0, link.End.Z) - new Vector3(link.Axis.X, 0, link.Axis.Z);
        bool stepOff = off.Length() > 24;
        long faceUntil = clock.ElapsedMilliseconds + 2500;
        while (stepOff && clock.ElapsedMilliseconds < faceUntil)
        {
            s = guard();
            float angle = PointNavigation.SignedAngle(s.Forward, link.End - s.Position);
            if (MathF.Abs(angle) < 0.12f) break;
            if (turn(turns.Pixels(angle * 0.8f, pulse * 4), 4) == 0) wait(Tick);
            if (Reached(guard().Position.Y)) break;
        }

        // 3. Ride until level with the stop.
        float limit = 6 + MathF.Abs(wanted - startY) / MinSpeed;
        long rideUntil = clock.ElapsedMilliseconds + (long)(Math.Min(limit, 60) * 1000);
        float bestY = s.Position.Y; long movedAt = clock.ElapsedMilliseconds;
        int nudges = 0;
        while (!Reached((s = guard()).Position.Y))
        {
            float progress = link.Up ? s.Position.Y - bestY : bestY - s.Position.Y;
            if (progress > 4) { bestY = s.Position.Y; movedAt = clock.ElapsedMilliseconds; }
            if (clock.ElapsedMilliseconds > rideUntil)
                throw new InvalidOperationException($"The gravity lift did not reach the landing in {limit:F0} s (at height {s.Position.Y:F0}, wanted {wanted:F0}).");
            if (clock.ElapsedMilliseconds - movedAt > 2500)
            {
                // Still on the floor beside the beam, or it let go of us: step to its middle again, twice.
                bool moved = MathF.Abs(s.Position.Y - startY) > 20;
                if (moved || nudges >= 2)
                    throw new InvalidOperationException(moved
                        ? $"The gravity lift stopped at height {s.Position.Y:F0}, short of the landing at {wanted:F0}."
                        : $"The gravity lift did not move you (stood in it for {clock.Elapsed.TotalSeconds:F0} s). Is it off?");
                nudges++;
                record("lift-nudge", s, new { nudges });
                float angle = PointNavigation.SignedAngle(s.Forward, axis - s.Position);
                if (PointNavigation.Distance(s.Position, axis) > 6 && MathF.Abs(angle) < 1.2f) { input.Walk(true); wait(150); input.Walk(false); }
                movedAt = clock.ElapsedMilliseconds;
            }
            show($"Gravity lift: going {way}, height {s.Position.Y:F0} of {wanted:F0}.");
            wait(Tick);
        }
        record("lift-level", s, new { y = s.Position.Y, wanted });

        // 4. Step off onto the landing (the foot of a down beam needs no step).
        if (stepOff)
        {
            long offUntil = clock.ElapsedMilliseconds + 5000;
            while (true)
            {
                s = guard();
                bool onIt = PointNavigation.Distance(s.Position, link.End) <= 20
                    || (PointNavigation.Distance(s.Position, axis) > 56 && MathF.Abs(s.Position.Y - wanted) < 40);
                if (onIt) break;
                if (clock.ElapsedMilliseconds > offUntil)
                {
                    input.Walk(false);
                    throw new InvalidOperationException($"The gravity lift reached the landing's height but stepping off failed ({PointNavigation.Distance(s.Position, link.End):F0} units from it).");
                }
                float angle = PointNavigation.SignedAngle(s.Forward, link.End - s.Position);
                input.Walk(MathF.Abs(angle) < Steering.TurnInPlaceAbove);
                int pixels = turns.Pixels(Math.Clamp(angle * 0.5f, -0.2f, 0.2f), pulse * 2);
                if (pixels != 0) turn(pixels, 2); else wait(Tick);
            }
            input.Walk(false);
        }
        // Let a fall onto the landing finish.
        s = wait(400);
        for (int i = 0; i < 20 && MathF.Abs(wait(100).Position.Y - s.Position.Y) > 2; i++) s = guard();
        s = guard();
        record("lift-done", s, new { y = s.Position.Y, wanted, seconds = clock.Elapsed.TotalSeconds });
        if (MathF.Abs(s.Position.Y - wanted) > 80)
            throw new InvalidOperationException($"The gravity lift left you at height {s.Position.Y:F0}, not on the landing at {wanted:F0}.");
        show("Gravity lift: off, carrying on.");

        // Up: feet a little over the landing's floor. Down: just above a landing, or down at the foot.
        bool Reached(float y) => link.Up ? y >= wanted + 12 : y <= wanted + (stepOff ? 40 : 20);
    }

    private static float[] Arr(Vector3 v) => new[] { v.X, v.Y, v.Z };
}

/// <summary>
/// The rule for doors inside a sector (the user's rule: right-click only to open doors, never Esc):
/// when a walk stalls within <see cref="Within"/> units of a door object, facing it along the route,
/// stop, right-click once, wait <see cref="WaitMs"/> and go on; at most <see cref="MaxTries"/> tries per door.
/// </summary>
internal sealed class DoorOpener(IReadOnlyList<SectorObjects.Door> doors)
{
    public const float Within = 150;
    public const int MaxTries = 2, WaitMs = 1500, StallMs = 1200;
    public const string Failed = "The door did not open (locked or in use).";
    private readonly Dictionary<SectorObjects.Door, int> _tries = new();

    /// <summary>The door in front of the walker within reach, if any: ahead (within 60 degrees of the facing) and on its floor.</summary>
    public SectorObjects.Door? Ahead(Vector3 position, Vector3 forward) =>
        doors.Where(d => PointNavigation.Distance(d.Position, position) <= Within && MathF.Abs(d.Position.Y - position.Y) < 160
                && (PointNavigation.Distance(d.Position, position) < 24 || MathF.Abs(PointNavigation.SignedAngle(forward, d.Position - position)) < 1.05f))
            .OrderBy(d => PointNavigation.Distance(d.Position, position)).FirstOrDefault();

    /// <summary>Counts a try at <paramref name="door"/>; false (and nothing to do) once it has had its tries.</summary>
    public bool Try(SectorObjects.Door door)
    {
        int n = _tries.GetValueOrDefault(door);
        if (n >= MaxTries) return false;
        _tries[door] = n + 1;
        return true;
    }

    public int Tries(SectorObjects.Door door) => _tries.GetValueOrDefault(door);

    // Progress watch, separate from the walk's own stall timer: pressing into a closed door at an
    // angle slides the character along it and turns it in place, which keeps resetting that timer
    // (29 Oct live: a follow slid along Plaza 1's clinic door for seconds and never clicked).
    private float _best = float.MaxValue; private long _bestAt = -1;
    public const float Reach = 70;

    /// <summary>
    /// Call every tick with what is left to go (route remaining, or the gap to a followed target).
    /// Returns the door to open when that has not shrunk by 15 units for <see cref="StallMs"/>
    /// while a door is within <see cref="Within"/> units on this floor, whichever way we face.
    /// </summary>
    public SectorObjects.Door? Blocking(Vector3 position, float left, long nowMs)
    {
        if (_bestAt < 0 || left < _best - 15) { _best = left; _bestAt = nowMs; return null; }
        if (nowMs - _bestAt < StallMs) return null;
        return doors.Where(d => PointNavigation.Distance(d.Position, position) <= Within && MathF.Abs(d.Position.Y - position.Y) < 160)
            .OrderBy(d => PointNavigation.Distance(d.Position, position)).FirstOrDefault();
    }

    /// <summary>Start watching progress afresh (after a click, a replan, a lift).</summary>
    public void Reset() { _best = float.MaxValue; _bestAt = -1; }

    /// <summary>
    /// Open <paramref name="door"/>: stop, turn to face it, step up to within <see cref="Reach"/>
    /// units (a click from further off gets "You cannot reach that!"), right-click once and wait.
    /// The caller's own steering primitives do the moving.
    /// </summary>
    public static void Open(SectorObjects.Door door, Func<PlayerSample> read, Func<float, int> pixelsFor, Action<int> turn,
        Action<bool> walk, Action use, Action<int> wait)
    {
        walk(false);
        for (int i = 0; i < 25; i++)
        {
            var s = read();
            float angle = PointNavigation.SignedAngle(s.Forward, door.Position - s.Position);
            if (MathF.Abs(angle) < 0.12f) break;
            turn(pixelsFor(angle * 0.8f));
        }
        var start = read();
        if (PointNavigation.Distance(start.Position, door.Position) > Reach)
        {
            walk(true);
            for (int i = 0; i < 30; i++)
            {
                wait(50);
                var s = read();
                if (PointNavigation.Distance(s.Position, door.Position) <= Reach) break;
            }
            walk(false);
            wait(150);
        }
        use();
        wait(WaitMs);
    }
}
