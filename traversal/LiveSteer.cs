using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Walks the live character along a navmesh route: W held while the mouse steers
/// toward a pure-pursuit aim point. Safety mirrors the app's PointNavigationSession:
/// F8 stops, focus loss stops, any identity change, sector change or position jump stops.
/// </summary>
internal sealed class LiveSteer
{
    private const int Tick = 33, PulseGap = 16;
    // Right-click "use" only on a walk whose destination is a door (an entrance), only near
    // its end, and only while stopped facing along the route: anywhere else it opened a loot
    // box and a CityCom terminal (which free the mouse pointer, after which W types into chat).
    private readonly bool _openDoor;
    private const int MaxUses = 3;
    private readonly PlayerReader _reader;
    private readonly NavWorld _nav;
    private readonly int _sector, _pulse;
    private readonly bool _run;
    private readonly Vector3 _target;
    private readonly bool _wide;
    private readonly string _label, _logPath;
    private readonly Hud _hud;
    private readonly bool _zoneExit, _countdown;

    /// <summary>Walking/running speed and mouse gain, measured once and reused on later legs of a trip.</summary>
    public sealed record Calibration(float Speed, float Gain);

    /// <summary>What this run measured (or was given); pass it to the next leg.</summary>
    public Calibration? Measured { get; private set; }
    private readonly Calibration? _known;
    private readonly Vector3? _pushTo;   // where to walk through the zone line (from the sector map's arrow)

    /// <summary>Where the character stood, and faced, on the last good reading before the zone changed.</summary>
    public (Vector3 Position, Vector3 Forward)? CrossedAt { get; private set; }

    /// <summary>True when an exit walk ended by the game loading another sector.</summary>
    public bool Zoned { get; private set; }

    /// <summary>Only count down and calibrate, then return with <see cref="Measured"/> set (the follow command steers itself).</summary>
    public bool CalibrateOnly { get; init; }

    private sealed class ZonedOut(string why) : Exception(why);

    /// <summary>Stopped by something the navmesh does not know about (a prop), at a place and heading.</summary>
    public sealed class BlockedAt(string message, Vector3 position, Vector3 forward) : InvalidOperationException(message)
    {
        public Vector3 Position { get; } = position;
        public Vector3 Forward { get; } = forward;
    }

    /// <param name="zoneExit">The target is a zone exit: walk into it and treat the sector changing as success.</param>
    /// <param name="countdown">Give the player 5 s to focus the game first (only the first leg of a trip needs it).</param>
    /// <param name="openDoor">The exit is a door: right-click it open when it stops the walk (needs <paramref name="zoneExit"/>).</param>
    public LiveSteer(PlayerReader reader, NavWorld nav, int sector, Vector3 target, bool wide, string label, int pulse, string logPath, Hud hud,
        bool run = false, bool zoneExit = false, bool countdown = true, Calibration? known = null, Vector3? pushTo = null, bool openDoor = false)
    { _openDoor = openDoor && zoneExit; _pushTo = pushTo; _known = known; _zoneExit = zoneExit; _countdown = countdown; _run = run; _hud = hud; _reader = reader; _nav = nav; _sector = sector; _target = target; _wide = wide; _label = label; _pulse = pulse; _logPath = logPath; }

    /// <summary>Time to allow for the lift rides on a route (the route's length is measured on the flat).</summary>
    private float LiftSeconds(List<Vector3> route) =>
        Enumerable.Range(0, Math.Max(0, route.Count - 1)).Select(i => _nav.LinkAt(route[i], route[i + 1]))
            .Sum(l => l == null ? 0 : 20 + MathF.Abs(l.Rise) / LiftRider.MinSpeed);

    public void Run()
    {
        using var log = new StreamWriter(_logPath) { AutoFlush = true };
        using var input = new SteerInput(_reader, _pulse, _run);
        var clock = Stopwatch.StartNew();
        var origin = _reader.ReadSample();
        var previous = origin;
        double deadline = double.MaxValue;
        double previousAt = 0;
        int anomalies = 0;
        bool riding = false;   // in a gravity lift: height changes fast, only a sideways jump is a teleport

        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Y, s.Position.Z }, forward = new { s.Forward.X, s.Forward.Z },
            walking = input.Walking, detail }));

        bool F8() => (Native.GetAsyncKeyState(0x77) & 0x8000) != 0;

        PlayerSample Guard()
        {
            if (F8()) throw new OperationCanceledException("F8 stop pressed.");
            _reader.RequireForeground();
            if (clock.Elapsed.TotalSeconds > deadline) throw new InvalidOperationException("Steering exceeded its time limit.");
            PlayerSample s;
            try { s = _reader.ReadSample(); }
            catch (InvalidOperationException e) when (_zoneExit)
            {
                // Unreadable while the client swaps worlds; one bad read alone proves nothing.
                if (++anomalies >= 3) throw new ZonedOut($"the player is loading into a new sector ({e.Message})");
                Thread.Sleep(30);
                return previous;
            }
            bool same = s.Player == origin.Player && s.World == origin.World && s.Physics == origin.Physics;
            int? sectorRead = _reader.ReadSectorId(s.World);
            // A real teleport is far beyond running speed; a slow tick at 340 u/s is not one.
            double now = clock.Elapsed.TotalSeconds, dt = previousAt == 0 ? 0 : now - previousAt;
            float jump = riding ? PointNavigation.Distance(s.Position, previous.Position) : Vector3.Distance(s.Position, previous.Position), jumpLimit = 60 + 900 * (float)Math.Min(dt, 2);
            string? anomaly = !same ? "the player/world changed" : sectorRead != _sector ? $"sector read as {sectorRead?.ToString() ?? "none"}"
                : jump > jumpLimit ? $"position jumped {jump:F0} units in {dt:F2} s" : null;
            if (anomaly != null)
            {
                if (_zoneExit)
                {
                    // Zoning changes these for good; a glitch lasts one read. Need three in a row.
                    Record("anomaly", s, new { anomaly, count = anomalies + 1 });
                    if (++anomalies >= 3) throw new ZonedOut(anomaly);
                    Thread.Sleep(30);
                    return previous;
                }
                if (!same) throw new InvalidOperationException("The player or world changed (zoning?). Stopped.");
                if (sectorRead != _sector) throw new InvalidOperationException("The sector changed. Stopped.");
                throw new InvalidOperationException($"Unexpected position jump ({anomaly}). Stopped.");
            }
            anomalies = 0;
            previous = s; previousAt = now;
            return s;
        }

        PlayerSample Wait(int ms)
        {
            long until = clock.ElapsedMilliseconds + ms;
            var s = Guard();
            while (clock.ElapsedMilliseconds < until) { Thread.Sleep((int)Math.Clamp(until - clock.ElapsedMilliseconds, 1, 15)); s = Guard(); }
            return s;
        }

        PlayerSample Settle()
        {
            input.Walk(false);
            var s = Wait(300); var c = Wait(100);
            if (Vector3.Distance(s.Position, c.Position) > 0.4f) throw new InvalidOperationException("The character did not settle after releasing W.");
            return c;
        }

        // Send up to `pulses` mouse pulses toward `pixels`, sampling between them; returns pixels sent.
        int Turn(int pixels, int pulses)
        {
            int sent = 0;
            for (int i = 0; i < pulses && sent != pixels; i++) { sent += input.TurnPulse(pixels - sent); Wait(PulseGap); }
            return sent;
        }

        try
        {
            if (_countdown) Console.WriteLine($"Focus Neocron now (mouse-look on: press Tab so the pointer disappears). Starting in 5 s. F8 stops.");
            for (int i = _countdown ? 5 : 0; i > 0; i--)
            {
                Console.Write($"{i}… ");
                _hud.Post(Hud.Amber, $"TRAVERSAL  starting in {i} s", "Click into Neocron now; press Tab so the pointer is hidden.", "F8 stops at any time.");
                for (int j = 0; j < 20; j++) { if (F8()) throw new OperationCanceledException("F8 stop pressed."); Thread.Sleep(50); }
            }
            if (_countdown) Console.WriteLine();
            // The jump guard is for steering, not the countdown: re-anchor on a fresh
            // sample now (the player may have moved, or the game caught up on focus).
            var fresh = _reader.ReadSample();
            if (Vector3.Distance(fresh.Position, previous.Position) > 1)
                Console.WriteLine($"Position changed during the countdown by {Vector3.Distance(fresh.Position, previous.Position):F0} units; re-planning from here.");
            previous = fresh;
            var start = Guard();
            float speed, gain;
            if (_known is { } known)
            {
                // Later legs: right after zoning the player stands at the zone line, where a
                // test step could walk straight back through it. Reuse the first leg's numbers.
                speed = known.Speed; gain = known.Gain;
                Record("calibration-reused", Guard(), new { speed, gain });
            }
            else
            {
                _hud.Post(Hud.Amber, "TRAVERSAL  calibrating", "A short step forward and a small turn to measure speed and mouse gain.");
                Record("start", start, new { target = new { _target.X, _target.Y, _target.Z }, label = _label, pulse = _pulse, sector = _sector });
                var stable = Settle();
                if (Vector3.Distance(start.Position, stable.Position) > 0.5f) throw new InvalidOperationException("Stand still before starting.");

                // Heading check: a short forward step must move along the native forward axis.
                // Like PointNavigation.VerifyForward, but tolerant of ramps/stairs (height change)
                // and of a running step. Standing against a wall, NPC or prop blocks or deflects
                // the step, so turn away and try again before giving up.
                PlayerSample stepped = stable;
                Vector3 measured = default;
                float flat = 0, alignment = 0;
                for (int attempt = 0; ; attempt++)
                {
                    input.Walk(true); Wait(120);
                    stepped = Settle();
                    measured = stepped.Position - stable.Position;
                    flat = new Vector2(measured.X, measured.Z).Length();
                    alignment = flat < 0.01f ? 0 : Vector3.Dot(PointNavigation.Planar(stable.Forward), PointNavigation.Planar(measured));
                    Record("test-step", stepped, new { attempt, flat, alignment, dy = measured.Y });
                    if (flat >= 3 && flat <= 120 && Math.Abs(measured.Y) <= flat * 0.8f && alignment >= 0.93f) break;
                    if (attempt == 3)
                        throw new InvalidOperationException($"The test step went {flat:F0} units (height {measured.Y:F0}), not straight ahead, four times. Is a menu, chat or the free pointer active?");
                    // (Never press Esc to recover: with no window open it starts Neocron's logout
                    // countdown, and a second Esc reaches the "leave Neocron?" menu. 29 Oct live run.)
                    // Turn roughly a quarter or more each time, the same way, so four tries
                    // face four different directions (one wall can block a whole quadrant).
                    Turn(380, 40);
                    stable = Settle();
                }
                speed = Math.Clamp(measured.Length() / 0.12f, 60, 800);
                Record("heading-verified", stepped, new { speed });

                // Turn calibration at the chosen pulse size. The first pulses after focus
                // can be swallowed, so a silent first probe is retried once.
                gain = 0;
                var before = stepped;
                for (int attempt = 0; attempt < 2 && Math.Abs(gain) < 1e-6f; attempt++)
                {
                    int sent = Turn(Math.Max(48, _pulse * 4), 16);
                    var after = Wait(80);
                    float angle = PointNavigation.SignedAngle(before.Forward, after.Forward);
                    if (PointNavigation.Distance(before.Position, after.Position) > 2) throw new InvalidOperationException("Unexpected movement during the turn check.");
                    Record("turn-probe", after, new { sent, angle });
                    if (Math.Abs(angle) > 0.001f) gain = angle / sent;
                    before = after;
                }
                if (Math.Abs(gain) < 1e-6f) throw new InvalidOperationException("Mouse-look did not respond. Press Tab in Neocron so the free pointer disappears, close chat, try again.");
                Console.WriteLine($"Calibrated: {(_run ? "running" : "walking")} {speed:F0} u/s, {gain * 1000:F2} mrad/pixel at {_pulse}px pulses.");
            }
            Measured = new(speed, gain);
            if (CalibrateOnly) return;
            var turns = new TurnController(gain);
            float lookahead = Steering.Lookahead(speed);
            int lastPixels = 0; Vector3 lastForward = Guard().Forward;

            var here = Guard();
            var route = _nav.Route(here.Position, _target, out bool complete, _wide);
            if (route.Count < 2 || !complete) throw new InvalidOperationException("No complete route from here after calibration.");
            var follower = new RouteFollower(route);
            deadline = clock.Elapsed.TotalSeconds + follower.Total / speed * 2 + 20 + LiftSeconds(route);
            Vector3 end = route[^1];
            int replans = 0;
            float bestProgress = 0; long stallMark = clock.ElapsedMilliseconds, turningSince = -1;
            int usesHere = 0, uses = 0;   // door "use" clicks at the current stop, and in all
            Record("route", here, new { corners = route.Select(c => new[] { c.X, c.Y, c.Z }), length = follower.Total, lifts = _nav.Lifts.Count });
            var rider = new LiftRider(Guard, Wait, Turn, input, turns, _pulse, (k, at, d) => Record(k, at, d),
                text => _hud.Show(Hud.Cyan, $"TRAVERSAL  -> {_label}", text, "F8 stops"));
            var doors = new DoorOpener(_nav.Doors);

            while (true)
            {
                var s = Guard();
                float dist = PointNavigation.Distance(s.Position, end);
                // Exits: start pushing early (the trigger is a volume, and circling a point at
                // running speed never settles). Walk, don't run, over the last stretch.
                // (On the floor of the end, not under it: lifts join floors stacked over each other.)
                if (dist <= (_zoneExit ? 70 : Simulator.FinalRadius) && MathF.Abs(s.Position.Y - end.Y) < Simulator.SameFloor) { if (_zoneExit) PushThrough(); else FinalApproach(); return; }
                input.Sprint(dist > 120);
                float off = follower.Update(s.Position);
                // A gravity lift on the route: at its start, ride it (a timed step), then plan on from the landing.
                var lift = Lifts.Ahead(_nav, follower);
                if (lift is { } l && Lifts.AtStart(l.Link, s.Position))
                {
                    riding = true;
                    try { rider.Ride(l.Link); }
                    finally { riding = false; }
                    s = Guard();
                    route = _nav.Route(s.Position, _target, out complete, _wide);
                    if (route.Count < 2 || !complete) throw new InvalidOperationException("Off the gravity lift, but no route on from the landing.");
                    follower = new(route); end = route[^1]; bestProgress = 0; stallMark = clock.ElapsedMilliseconds; usesHere = 0;
                    deadline = Math.Max(deadline, clock.Elapsed.TotalSeconds + follower.Total / speed * 2 + 20 + LiftSeconds(route));
                    Record("replan", s, new { why = "lift", corners = route.Count, length = follower.Total });
                    continue;
                }
                if (off > Simulator.OffRouteLimit)
                {
                    if (++replans > 6) throw new InvalidOperationException("Kept leaving the route; the navmesh and the game disagree here.");
                    input.Walk(false);
                    route = _nav.Route(s.Position, _target, out complete, _wide);
                    if (route.Count < 2 || !complete) throw new InvalidOperationException("Replanning found no route.");
                    follower = new(route); end = route[^1]; bestProgress = 0; stallMark = clock.ElapsedMilliseconds;
                    Record("replan", s, new { off, corners = route.Count, length = follower.Total });
                    _hud.Post(Hud.Amber, $"TRAVERSAL  -> {_label}", $"Off the route by {off:F0} units: replanned ({replans} of 6).");
                    continue;
                }
                // Keep learning the real mouse gain from the last tick's turn.
                turns.Observe(lastPixels, PointNavigation.SignedAngle(lastForward, s.Forward));
                lastForward = s.Forward;
                // Walk to a lift's start exactly: the look-ahead would cut past it into the beam.
                var aim = lift is { } next && next.Arc - follower.Progress < lookahead ? next.Link.Start : follower.Aim(s.Position, lookahead, _nav.Clear);
                var decision = Steering.Decide(s.Position, s.Forward, aim);
                input.Walk(decision.Walk);
                int pixels = turns.Pixels(decision.TurnRadians, _pulse * 2);
                int sent = pixels == 0 ? 0 : Turn(pixels, 2);
                lastPixels = sent;
                float degrees = MathF.Abs(decision.Angle) * 180 / MathF.PI;
                // A positive pixel count moves the mouse right, so the sign of angle/gain is the turn side.
                string turn = degrees < 3 ? "on course" : $"turn {(decision.Angle / turns.Gain > 0 ? "right" : "left")} {degrees:F0} deg";
                _hud.Show(Hud.Green, $"TRAVERSAL  -> {_label}",
                    $"{follower.Remaining:F0} of {follower.Total:F0} units left  ({100 * follower.Progress / Math.Max(1, follower.Total):F0}%)",
                    $"next corner {PointNavigation.Distance(s.Position, follower.NextCorner):F0} units, {turn}",
                    $"{(decision.Walk ? (_run ? "running" : "walking") : "turning in place")}   replans {replans}   F8 stops");
                Record("steer", s, new { aim = new[] { aim.X, aim.Y, aim.Z }, decision.Angle, pixels = sent, off, progress = follower.Progress, follower.Total });
                if (!decision.Walk)
                {
                    if (turningSince < 0) turningSince = clock.ElapsedMilliseconds;
                    if (clock.ElapsedMilliseconds - turningSince > 10_000) throw new InvalidOperationException("Could not face the route. Check mouse-look mode.");
                    Wait(20);
                    stallMark = clock.ElapsedMilliseconds;
                    continue;
                }
                turningSince = -1;
                // A door inside the sector (doors are not level geometry, so routes run through them):
                // when what is left stops shrinking near one, face it, step up to it, right-click it.
                if (doors.Blocking(s.Position, follower.Remaining, clock.ElapsedMilliseconds) is { } door)
                {
                    if (!doors.Try(door)) throw new InvalidOperationException(DoorOpener.Failed);
                    _hud.Post(Hud.Amber, $"TRAVERSAL  -> {_label}", $"A door is in the way: opening it (right click, try {doors.Tries(door)} of {DoorOpener.MaxTries}).");
                    Console.WriteLine($"A door is in the way: right-clicking it (try {doors.Tries(door)} of {DoorOpener.MaxTries}).");
                    DoorOpener.Open(door, Guard, a => turns.Pixels(a, _pulse * 4), px => Turn(px, 4), input.Walk, input.Use, ms => Wait(ms));
                    Record("use", Guard(), new { reason = "door", door = door.Name, at = new[] { door.Position.X, door.Position.Y, door.Position.Z }, tries = doors.Tries(door) });
                    doors.Reset();
                    stallMark = clock.ElapsedMilliseconds;
                    continue;
                }
                if (follower.Progress > bestProgress + 2) { bestProgress = follower.Progress; stallMark = clock.ElapsedMilliseconds; usesHere = 0; }
                // Stopped near the end of a walk to a door, facing along the route: the closed
                // door (doors are not in the level geometry, so the route runs through them).
                // Right-click it and give it time to open; twice at most here.
                else if (_openDoor && follower.Remaining < 600 && MathF.Abs(decision.Angle) < 0.35f && clock.ElapsedMilliseconds - stallMark > 1200)
                {
                    if (usesHere >= 2 || uses >= MaxUses)
                        throw new InvalidOperationException("The door did not open after right-clicking it (locked, or only for some factions?).");
                    input.Walk(false);
                    input.Use();
                    usesHere++; uses++;
                    Record("use", s, new { reason = "stopped", remaining = follower.Remaining });
                    _hud.Post(Hud.Amber, $"TRAVERSAL  -> {_label}", "Stopped at the door: opening it (right click).");
                    Console.WriteLine("Stopped at the door: right-clicking to open it.");
                    Wait(1500);
                    stallMark = clock.ElapsedMilliseconds;
                    continue;
                }
                // At a zone line the character halts while the next zone loads; on an exit walk
                // a halt is only "blocked" once it has outlasted that.
                else if (clock.ElapsedMilliseconds - stallMark > (_zoneExit ? 10_000 : 2000))
                    throw new BlockedAt($"Blocked {follower.Remaining:F0} units from the target: the navmesh says walkable, the game disagrees (door, prop or step?).", s.Position, s.Forward);
                if (sent == 0) Wait(Tick);
            }

            // A zone exit is a trigger at the end of a walkway: keep walking toward and
            // past the exit point until the game starts loading the next sector.
            void PushThrough()
            {
                var s = Guard();
                input.Sprint(false);
                // Aim at the exit's true position (the route ends at its nearest navmesh point,
                // which can be well off), then carry on the same way past it.
                Vector3 beyond = _pushTo ?? _target + PointNavigation.Planar(_target - s.Position) * 300;
                // Zone lines sit at the end of a corridor (the "Synchronizing into city zone" wall),
                // and corridors bend: follow the walkable floor toward the push point to its end,
                // then keep pressing the way the corridor runs. (A straight push turned into a wall
                // in Plaza 2 with the "Entering new district" banner already showing.)
                var corridor = _nav.RouteToward(s.Position, beyond);
                RouteFollower? lead = corridor.Count >= 2 ? new RouteFollower(corridor) : null;
                Vector3 onward = corridor.Count >= 2
                    ? PointNavigation.Planar(corridor[^1] - corridor[^2])
                    : PointNavigation.Planar(beyond - s.Position);
                Record("corridor", s, new { corners = corridor.Select(c => new[] { c.X, c.Z }), onward = new[] { onward.X, onward.Z } });
                _hud.Post(Hud.Green, $"TRAVERSAL  -> {_label}", "At the exit: walking through the zone line.");
                // The game halts the character at the zone line while the next zone loads,
                // which can take several seconds: once halted, just keep pressing forward.
                long until = clock.ElapsedMilliseconds + 16_000, movedAt = clock.ElapsedMilliseconds;
                Vector3 last = s.Position;
                int usesAtExit = 0;
                while (clock.ElapsedMilliseconds < until)
                {
                    s = Guard();
                    if (PointNavigation.Distance(s.Position, last) > 3) { last = s.Position; movedAt = clock.ElapsedMilliseconds; }
                    bool halted = clock.ElapsedMilliseconds - movedAt > 600;
                    // Halted at a door exit: the door wants opening, or the next zone is loading.
                    // Try the door a couple of times, then just keep pressing forward.
                    if (_openDoor && halted && usesAtExit < 2 && uses < MaxUses && clock.ElapsedMilliseconds - movedAt > 1000 * (usesAtExit + 1))
                    {
                        input.Walk(false);
                        input.Use();
                        usesAtExit++; uses++;
                        Record("use", s, new { reason = "at exit" });
                        Console.WriteLine("Halted at the door: right-clicking to open it.");
                        Wait(1500);
                        movedAt = clock.ElapsedMilliseconds;
                        continue;
                    }
                    Vector3 aimAt;
                    if (lead != null && lead.Remaining > 25) { lead.Update(s.Position); aimAt = lead.Aim(s.Position, 60, _nav.Clear); }
                    else aimAt = s.Position + onward * 300;
                    float angle = PointNavigation.SignedAngle(s.Forward, aimAt - s.Position);
                    input.Walk(halted || Math.Abs(angle) < Steering.TurnInPlaceAbove);
                    int pixels = halted ? 0 : turns.Pixels(Math.Clamp(angle * Steering.WalkingShare, -Steering.MaxWalkingTurn, Steering.MaxWalkingTurn), _pulse * 2);
                    if (pixels != 0) Turn(pixels, 2); else Wait(Tick);
                    Record("push", s, new { angle, halted });
                }
                throw new InvalidOperationException("Walked through the exit point but the game did not change sector.");
            }

            void FinalApproach()
            {
                for (int attempt = 0; attempt < 40; attempt++)
                {
                    var s = Settle();
                    float dist = PointNavigation.Distance(s.Position, end);
                    if (dist <= Simulator.ArrivalTolerance && MathF.Abs(s.Position.Y - end.Y) < Simulator.SameFloor)
                    {
                        Record("complete", s, new { error = dist });
                        Console.WriteLine($"Arrived at {_label}, {dist:F1} units from the target.");
                        _hud.Post(Hud.Green, $"TRAVERSAL  arrived at {_label}", $"{dist:F1} units from the target.");
                        return;
                    }
                    float angle = PointNavigation.SignedAngle(s.Forward, end - s.Position);
                    if (Math.Abs(angle) > 0.12f) { Turn(turns.Pixels(angle * 0.8f, _pulse * 4), 4); continue; }
                    input.Walk(true);
                    Wait(Math.Clamp((int)((dist - 3) / speed * 800), 10, 150));
                    input.Walk(false);
                    Record("final-step", s, new { dist, angle });
                    _hud.Show(Hud.Green, $"TRAVERSAL  -> {_label}", $"final approach, {dist:F1} units");
                }
                throw new InvalidOperationException("Could not settle on the target.");
            }
        }
        catch (ZonedOut zoned)
        {
            input.Dispose();
            Zoned = true;
            CrossedAt = (previous.Position, previous.Forward);
            Record("zoned", previous, new { zoned.Message });
            Console.WriteLine($"Zoning: {zoned.Message}.");
            _hud.Post(Hud.Cyan, "TRAVERSAL  zoning", "Loading the next sector...");
        }
        catch (Exception error)
        {
            input.Dispose();
            Record("stopped", previous, new { error.Message });
            _hud.Post(Hud.Red, "TRAVERSAL  stopped", error.Message);
            throw;
        }
    }
}
