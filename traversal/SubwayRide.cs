using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// The decisions of one subway ride, fed with the time, the player's position (null when it cannot be
/// read, as may happen while seated) and the trains' positions (null when they could not be read this
/// time; never readable, it falls back to "use" from where it stands). No
/// input, no game: <see cref="SubwayRide"/> acts on what it says, and the tests drive it with made-up readings.
/// - Waiting at the platform edge for a train to stand on this platform's track (still for 1 s).
/// - Approaching: walk toward the car's middle until within <see cref="Reach"/> (or blocked), then
///   "use" (right-click) it. Aboard when the position joins the car, jumps or stops reading.
/// - Riding: when our train stands still beside the platform we want, Space (Jump) to leave the car.
/// - Done when standing on that platform's floor, off the car; also when put off at another platform
///   (<see cref="Landed"/> says which; the trip then plans again from there).
/// Without train readings it falls back to "use" every few seconds from where it stands.
/// </summary>
internal sealed class SubwayRideLogic(Vector3 board, Vector3 track, int toPlatform, string fromName, string toName,
    Func<Vector3, int> platformAt, Func<Vector3, bool> besideDestination)
{
    public enum Act { Wait, Approach, Use, Jump, Done, Fail }

    /// <summary>Longest wait for a train at the platform (eleven trains run 30 s apart).</summary>
    public const double BoardTimeout = 150;
    /// <summary>Longest time aboard: a wrong-way train goes to the end of the line and back.</summary>
    public const double RideTimeout = 480;
    public const double UseEvery = 3, StillFor = 1.5, LeaveWait = 3, UseWait = 2.5, TrainStill = 1.0, ApproachLongest = 4;
    /// <summary>
    /// How close to the car's middle a right-click reaches, on the flat. Live (29 Oct, Plaza): from the
    /// boarding spot, about 245 from the middle, the game said "You cannot reach that!". 190 is about
    /// 100 from the car's side, taking the car to be some 90 to each side of its middle. Each "use" logs
    /// its distance and whether it boarded, to refine this.
    /// </summary>
    public const float Reach = 190;
    /// <summary>A train stands at this platform when its middle is this far out from the boarding spot, toward the track (live: 240 at Plaza).</summary>
    public const float TrackNear = 40, TrackFar = 450, AlongTrack = 700;
    public const int UsesPerTrain = 4, TrainsToTry = 3, Jumps = 2;
    private const float Moved = 90, StillDistance = 40, TrainStillDistance = 30, SeatRadius = 80, StepOffDistance = 120;

    public string Phase { get; private set; } = "waiting";
    public string? Message { get; private set; }
    /// <summary>The platform we ended on (when <see cref="Act.Done"/>).</summary>
    public int Landed { get; private set; } = -1;
    public int Uses { get; private set; }
    /// <summary>What to face and walk toward (Approach), or face and click (Use): the car's middle; null to use straight ahead.</summary>
    public Vector3? Goal { get; private set; }
    /// <summary>The train we board or ride (its registry key), or -1.</summary>
    public int Train { get; private set; } = -1;
    /// <summary>On the last "use": the flat distance to the car's middle, or NaN when the train was not read.</summary>
    public float UseDistance { get; private set; } = float.NaN;
    public int TrainsTried { get; private set; }

    private double _start = -1, _lastUse = -1e9, _rideStart, _leaveStart, _unreadableSince = -1, _approachStart, _phaseStart;
    private int _reads, _unreadable, _usesThisTrain, _jumps;
    private bool _everTrains;
    private Vector3 _useAt, _approachFrom, _trainAt;
    private readonly List<(double T, Vector3 P)> _recent = new();
    private readonly Dictionary<int, List<(double T, Vector3 P)>> _trains = new();
    private readonly HashSet<int> _given = new();   // trains tried as often as allowed: not again while they stand here

    public Act Step(double t, Vector3? position) => Step(t, position, null);

    public Act Step(double t, Vector3? position, IReadOnlyList<(int Key, Vector3 P)>? trains)
    {
        if (_start < 0) { _start = t; _useAt = board; }
        _reads++;
        if (position is { } p) { _recent.Add((t, p)); _recent.RemoveAll(r => t - r.T > 6); _unreadableSince = -1; }
        else { _unreadable++; if (_unreadableSince < 0) _unreadableSince = t; }
        if (trains != null)
        {
            if (trains.Count > 0) _everTrains = true;
            foreach (var (key, at) in trains)
            {
                if (!_trains.TryGetValue(key, out var h)) _trains[key] = h = new();
                h.Add((t, at)); h.RemoveAll(r => t - r.T > 3);
            }
            foreach (var gone in _trains.Keys.Where(k => trains.All(x => x.Key != k)).ToList()) _trains.Remove(gone);
            _given.RemoveWhere(k => TrainAt(k) is not { } at || !Standing(k, at, t));
        }
        Vector3? ours = Train >= 0 ? TrainAt(Train) : null;
        switch (Phase)
        {
            case "waiting":
            {
                if (t - _start > BoardTimeout)
                    return Fail(TrainsTried > 0
                        ? $"Could not board a train at the {fromName} platform in {BoardTimeout:F0} s: right-clicked {Uses} times on {TrainsTried} trains, the last from {UseDistance:F0} units of its middle (\"You cannot reach that!\" means too far)."
                        : !_everTrains
                            ? $"No train took us aboard at the {fromName} platform in {BoardTimeout:F0} s ({Uses} uses facing the track; the trains could not be read)."
                            : $"No train stopped at the {fromName} platform in {BoardTimeout:F0} s.");
                if (!_everTrains)
                {
                    // Fallback: no train readings (after 2 s of trying). Use straight ahead every few seconds, as at a door.
                    if (t - _start < 2) return Act.Wait;
                    bool aboard = position is { } q ? Off(q, _useAt) : Uses > 0 && t - _unreadableSince >= 1;
                    if (aboard) return Aboard(t, position);
                    Goal = null;
                    if (t - _lastUse >= UseEvery) return Use(t, position);
                    return Act.Wait;
                }
                if (position is not { } me) return Act.Wait;
                foreach (var (key, h) in _trains)
                    if (!_given.Contains(key) && Standing(key, h[^1].P, t))
                    {
                        if (Train != key) { Train = key; _usesThisTrain = 0; TrainsTried++; }
                        _trainAt = h[^1].P; Goal = _trainAt;
                        return BeginApproach(t, me);
                    }
                return Act.Wait;
            }
            case "approaching":
            {
                if (ours is not { } car || PointNavigation.Distance(car, _trainAt) > TrainStillDistance * 2) return TrainLeft();
                if (position is not { } me) return Act.Wait;
                if (me.Y < _approachFrom.Y - 30)
                    return Fail($"Stepped off the {fromName} platform's edge while walking up to the train (height {me.Y:F0}, was {_approachFrom.Y:F0}).");
                float d = PointNavigation.Distance(me, car);
                bool stalled = t - _approachStart > 0.6 && Progress(t, 0.5) < 10;
                if (d <= Reach || stalled || PointNavigation.Distance(me, _approachFrom) > 300 || t - _approachStart > ApproachLongest)
                {
                    _usesThisTrain++;
                    UseDistance = d;
                    Phase = "using"; _phaseStart = t;
                    return Use(t, me);
                }
                return Act.Approach;
            }
            case "using":
            {
                // Aboard: joined the car (seated at its middle), jumped, or unreadable for a second.
                if (position is { } q ? (ours is { } c && PointNavigation.Distance(q, c) < SeatRadius) || Off(q, _useAt)
                                       : t - _unreadableSince >= 1)
                    return Aboard(t, position);
                if (ours is not { } car || PointNavigation.Distance(car, _trainAt) > TrainStillDistance * 2) return TrainLeft();
                if (t - _phaseStart < UseWait) return Act.Wait;
                if (_usesThisTrain >= UsesPerTrain)
                {
                    _given.Add(Train);
                    if (TrainsTried >= TrainsToTry)
                        return Fail($"Could not board the train at the {fromName} platform: right-clicked {Uses} times on {TrainsTried} trains, the last from {UseDistance:F0} units of its middle (\"You cannot reach that!\" means too far).");
                    Phase = "waiting"; Goal = null;
                    return Act.Wait;
                }
                // Not aboard: walk closer and try again.
                if (position is not { } me) return Act.Wait;
                return BeginApproach(t, me);
            }
            case "riding":
            {
                if (t - _rideStart > RideTimeout)
                    return Fail(_unreadable * 2 > _reads && ours == null
                        ? $"Could not read the position while on the train ({_unreadable} of {_reads} reads failed), so the {toName} stop was not seen; stopped after {RideTimeout / 60:F0} min."
                        : $"The train did not stop at the {toName} platform within {RideTimeout / 60:F0} min.");
                // Put off (or stepped off) somewhere: on a platform floor, off the car and standing still.
                if (position is { } q && Still(t, 2) && (ours is not { } c0 || PointNavigation.Distance(q, c0) > StepOffDistance))
                {
                    int on = platformAt(q);
                    if (on == toPlatform) return Done(on);
                    if (on >= 0 && Still(t, 4)) return Done(on);
                }
                // At our stop: the train (or, unread, we) still beside the platform wanted.
                bool there = ours is { } car
                    ? TrainStillFor(Train, t, StillFor) && besideDestination(car)
                    : position is { } q2 && Still(t, StillFor) && besideDestination(q2);
                if (there) { Phase = "leaving"; _leaveStart = t; return Jump(); }
                return Act.Wait;
            }
            case "leaving":
            {
                if (position is { } q && platformAt(q) == toPlatform && Still(t, 0.6) &&
                    (ours is not { } c || PointNavigation.Distance(q, c) > StepOffDistance))
                    return Done(toPlatform);
                if (t - _leaveStart < LeaveWait) return Act.Wait;
                bool stands = ours is { } car ? TrainStillFor(Train, t, 0.5) && besideDestination(car) : position is { } q3 && besideDestination(q3);
                if (_jumps < Jumps && stands) { _leaveStart = t; return Jump(); }
                return Fail($"Could not leave the train at the {toName} platform (pressed Space {_jumps} times{(stands ? "" : "; the train moved on")}).");
            }
            default: return Phase == "done" ? Act.Done : Act.Fail;
        }
    }

    /// <summary>True when the train's middle is out from the boarding spot toward this platform's track, and has stood still for a second.</summary>
    private bool Standing(int key, Vector3 at, double t)
    {
        var n = new Vector2(track.X - board.X, track.Z - board.Z);
        if (n.LengthSquared() < 1) return false;
        n = Vector2.Normalize(n);
        var d = new Vector2(at.X - board.X, at.Z - board.Z);
        float across = Vector2.Dot(d, n), along = MathF.Abs(d.X * n.Y - d.Y * n.X);
        return across is >= TrackNear and <= TrackFar && along <= AlongTrack && MathF.Abs(at.Y - board.Y) < 150 && TrainStillFor(key, t, TrainStill);
    }

    private bool TrainStillFor(int key, double t, double seconds)
    {
        if (!_trains.TryGetValue(key, out var h) || h.Count < 2 || t - h[0].T < seconds) return false;
        var span = h.Where(r => t - r.T <= seconds).Select(r => r.P).ToList();
        return span.Count >= 2 && span.All(a => PointNavigation.Distance(a, span[^1]) < TrainStillDistance);
    }

    private Vector3? TrainAt(int key) => _trains.TryGetValue(key, out var h) && h.Count > 0 ? h[^1].P : null;

    private bool Off(Vector3 q, Vector3 from) => PointNavigation.Distance(q, from) > Moved || MathF.Abs(q.Y - from.Y) > 60;

    // How far the player moved over the last `seconds` (0 when the readings do not go back that far).
    private float Progress(double t, double seconds)
    {
        var span = _recent.Where(r => t - r.T <= seconds).ToList();
        return span.Count < 2 || t - span[0].T < seconds * 0.8 ? 0 : PointNavigation.Distance(span[0].P, span[^1].P);
    }

    // True when the readings of the last `seconds` (and there are some that old) stay within a small circle.
    private bool Still(double t, double seconds)
    {
        if (_recent.Count < 2 || t - _recent[0].T < seconds) return false;
        var span = _recent.Where(r => t - r.T <= seconds).Select(r => r.P).ToList();
        return span.Count >= 2 && span.All(a => PointNavigation.Distance(a, span[^1]) < StillDistance);
    }

    private Act BeginApproach(double t, Vector3 me)
    {
        Phase = "approaching"; _approachStart = t; _approachFrom = me;
        _recent.RemoveAll(r => r.T < t);   // progress is measured from here
        _recent.Add((t, me));
        return Act.Approach;
    }

    /// <summary>The runner stood still a while (turning to face the car): measure the approach's progress from here.</summary>
    public void Resume(double t, Vector3 me)
    {
        if (Phase != "approaching") return;
        _approachStart = t;
        _recent.RemoveAll(r => r.T < t);
        _recent.Add((t, me));
    }

    private Act TrainLeft()
    {
        // It pulled out before we were aboard: wait for the next (this one counts as tried).
        Phase = "waiting"; Goal = null;
        return Act.Wait;
    }

    private Act Aboard(double t, Vector3? at)
    {
        Phase = "riding"; _rideStart = t; _recent.Clear(); Goal = null;
        if (Train < 0 && at is { } q && _trains.Count > 0)
            Train = _trains.MinBy(k => PointNavigation.Distance(k.Value[^1].P, q)).Key;
        return Act.Wait;
    }

    private Act Use(double t, Vector3? at) { _lastUse = t; Uses++; if (at is { } q) _useAt = q; return Act.Use; }
    private Act Jump() { _jumps++; return Act.Jump; }
    private Act Done(int platform) { Phase = "done"; Landed = platform; return Act.Done; }
    private Act Fail(string why) { Phase = "failed"; Message = why; return Act.Fail; }
}

/// <summary>
/// One subway ride live: walk to the boarding spot on the platform edge and face the track; then, as
/// <see cref="SubwayRideLogic"/> says, walk up to the train standing there, right-click it (keys.ini:
/// Use = MBUTTON 2) to board, and press Space (Jump) to leave the car at the stop wanted. F8 or losing
/// focus stops it, as a walk. Throws with a message starting "Subway:" on failure.
/// </summary>
internal sealed class SubwayRide(PlayerReader reader, NavWorld nav, Travel travel, Travel.SubwayPlatform from, Travel.SubwayPlatform to,
    int pulse, string logPath, Hud hud, bool run, LiveSteer.Calibration? known, bool countdown)
{
    private const int Tick = 200, WalkTick = 50;
    public LiveSteer.Calibration? Measured { get; private set; }
    public int Landed { get; private set; } = -1;

    public void Run()
    {
        Measured = known;
        // 1. To the middle of the platform edge (the train stops along it).
        var walk = new LiveSteer(reader, nav, Travel.Subway, from.Board, true, $"the {from.Name} subway platform", pulse, logPath, hud, run,
            countdown: countdown, known: known);
        walk.Run();
        Measured = walk.Measured ?? known;
        string rideLog = Path.ChangeExtension(logPath, null) + "-ride.jsonl";
        using var log = new StreamWriter(rideLog) { AutoFlush = true };
        using var input = new SteerInput(reader, pulse, run: false);
        var clock = Stopwatch.StartNew();
        void Record(string kind, Vector3? at, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new
        {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = at is { } p ? new { p.X, p.Y, p.Z } : null, detail,
        }));
        static bool F8() => (Native.GetAsyncKeyState(0x77) & 0x8000) != 0;
        var turns = new TurnController(Measured?.Gain ?? 0.0025f);

        // Turn toward a point (standing still), within about 5 degrees.
        void Face(Vector3 point)
        {
            for (int i = 0; i < 20; i++)
            {
                if (F8()) throw new OperationCanceledException("F8 stop pressed.");
                var s = reader.ReadSteady();
                float angle = PointNavigation.SignedAngle(s.Forward, point - s.Position);
                if (MathF.Abs(angle) < 0.08f) return;
                // Mouse-look is slow (live gain about 0.00018 rad a pixel): allow a big turn per round.
                int pixels = turns.Pixels(angle * 0.8f, 3000);
                for (int sent = 0; sent != pixels;)
                {
                    if (F8()) throw new OperationCanceledException("F8 stop pressed.");
                    sent += input.TurnPulse(pixels - sent); Thread.Sleep(16);
                }
                Thread.Sleep(120);
            }
        }

        // 2. Face the track, so the train is ahead when it pulls in.
        Face(from.Track);
        var start = reader.ReadSteady();
        Record("ride-start", start.Position, new { from = from.Name, to = to.Name, board = new { from.Board.X, from.Board.Z }, track = new { from.Track.X, from.Track.Z } });

        // 3. Wait, walk up to the train, board, ride, step off.
        var logic = new SubwayRideLogic(from.Board, from.Track, to.Index, from.Name, to.Name, p => travel.PlatformAt(nav, p),
            p => to.Edge.Any(e => PointNavigation.Distance(e, p) < 420 && MathF.Abs(e.Y - p.Y) < 200));
        int elsewhere = 0, trainMisses = 0;
        string lastPhase = "";
        try
        {
            while (true)
            {
                if (F8()) throw new OperationCanceledException("F8 stop pressed.");
                reader.RequireForeground();
                Vector3? at = null;
                try
                {
                    // The position alone: the orientation may not read while seated.
                    var s = reader.ReadPosition();
                    int? sector = reader.ReadSectorId(s.World);
                    if (sector is { } id && id != Travel.Subway)
                    {
                        if (++elsewhere >= 3) throw new InvalidOperationException($"Subway: left the subway for {travel.SectorName(id)} during the ride.");
                    }
                    else { elsewhere = 0; at = s.Position; }
                }
                catch (InvalidOperationException e) when (!e.Message.StartsWith("Subway:", StringComparison.Ordinal) && e.Message != "The game closed.") { at = null; }
                // The trains (null this tick when the registry was caught mid-update: the logic keeps what it saw).
                IReadOnlyList<(int Key, Vector3 P)>? trains = null;
                try { trains = reader.ReadTrains(); trainMisses = 0; }
                catch (InvalidOperationException e) when (e.Message != "The game closed.")
                {
                    if (++trainMisses == 25) Record("trains-unreadable", at, new { e.Message });
                }

                var act = logic.Step(clock.Elapsed.TotalSeconds, at, trains);
                if (logic.Phase != lastPhase)
                {
                    lastPhase = logic.Phase;
                    Record("phase", at, new { logic.Phase, logic.Train, trains = trains?.Count });
                    Console.WriteLine(logic.Phase switch
                    {
                        "waiting" => $"  waiting for a train at the {from.Name} platform",
                        "approaching" => $"  a train stands at the {from.Name} platform: walking up to it",
                        "using" => $"  right-clicking the train",
                        "riding" => $"  aboard; riding to the {to.Name} platform",
                        "leaving" => $"  at the {to.Name} platform: Space to leave the car",
                        _ => $"  {logic.Phase}",
                    });
                }
                switch (act)
                {
                    case SubwayRideLogic.Act.Approach:
                    {
                        // Walk toward the car's middle: face it standing when well off, then steer a little as we go.
                        if (logic.Goal is { } goal)
                        {
                            var s = reader.ReadSteady();
                            float angle = PointNavigation.SignedAngle(s.Forward, goal - s.Position);
                            if (MathF.Abs(angle) > 0.25f)
                            {
                                input.Walk(false);
                                Face(goal);
                                logic.Resume(clock.Elapsed.TotalSeconds, reader.ReadPosition().Position);
                            }
                            else
                            {
                                int pixels = turns.Pixels(angle * 0.6f, pulse * 4);
                                for (int sent = 0; sent != pixels;) { sent += input.TurnPulse(pixels - sent); Thread.Sleep(16); }
                            }
                            input.Walk(true);
                        }
                        break;
                    }
                    case SubwayRideLogic.Act.Use:
                        input.Walk(false);
                        Thread.Sleep(250);
                        if (logic.Goal is { } car) Face(car);
                        Record("use", at, new { logic.Phase, logic.Uses, logic.Train, distance = float.IsNaN(logic.UseDistance) ? (float?)null : logic.UseDistance,
                            car = logic.Goal is { } g ? new { g.X, g.Y, g.Z } : null });
                        input.Use();
                        break;
                    case SubwayRideLogic.Act.Jump:
                        input.Walk(false);
                        Record("jump", at, new { logic.Train });
                        input.Jump();
                        break;
                    case SubwayRideLogic.Act.Done:
                        Landed = logic.Landed;
                        Record("done", at, new { landed = logic.Landed });
                        Console.WriteLine(Landed == to.Index ? $"  off the train at the {to.Name} platform" : $"  put off at another platform ({Landed}); planning again from there");
                        return;
                    case SubwayRideLogic.Act.Fail:
                        input.Walk(false);
                        Record("failed", at, new { logic.Message });
                        throw new InvalidOperationException("Subway: " + logic.Message);
                    default:
                        input.Walk(false);
                        break;
                }
                hud.Show(Hud.Cyan, "TRAVERSAL  subway", logic.Phase switch
                {
                    "waiting" => $"Waiting for a train at the {from.Name} platform ({clock.Elapsed.TotalSeconds:F0} s).",
                    "approaching" or "using" => $"Boarding the train at the {from.Name} platform (right-click {logic.Uses}).",
                    "riding" => $"On the train to the {to.Name} platform.",
                    _ => $"Leaving the car at the {to.Name} platform.",
                }, "F8 stops");
                Thread.Sleep(logic.Phase == "approaching" ? WalkTick : Tick);
            }
        }
        finally { input.Walk(false); }
    }
}
