using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// The decisions of one subway ride, fed with the time and the position read (null when it cannot be
/// read, as may happen while seated in the train). No input, no game: <see cref="SubwayRide"/> acts on
/// what it says, and the tests drive it with made-up readings.
/// - Waiting: standing at the platform edge facing the track, "use" every few seconds until the train
///   takes us aboard (the position jumps, moves on its own, or stops reading).
/// - Riding: when the train stands still beside the platform we want, "use" to step off.
/// - Done when standing still on that platform's floor; also when put off at another platform
///   (<see cref="Landed"/> says which; the trip then plans again from there).
/// </summary>
internal sealed class SubwayRideLogic(Vector3 board, int toPlatform, string fromName, string toName,
    Func<Vector3, int> platformAt, Func<Vector3, bool> besideDestination)
{
    public enum Act { Wait, Use, Done, Fail }

    /// <summary>Longest wait for a train at the platform (twelve trains run 30 s apart).</summary>
    public const double BoardTimeout = 150;
    /// <summary>Longest time aboard: a wrong-way train goes to the end of the line and back.</summary>
    public const double RideTimeout = 480;
    public const double UseEvery = 3, StillFor = 1.5, LeaveWait = 4;
    private const float Moved = 90, StillDistance = 40;

    public string Phase { get; private set; } = "waiting";
    public string? Message { get; private set; }
    /// <summary>The platform we ended on (when <see cref="Act.Done"/>).</summary>
    public int Landed { get; private set; } = -1;
    public int Uses { get; private set; }

    private double _start = -1, _lastUse = -1e9, _rideStart, _leaveStart, _unreadableSince = -1;
    private int _leaveTries, _reads, _unreadable;
    private readonly List<(double T, Vector3 P)> _recent = new();

    public Act Step(double t, Vector3? position)
    {
        if (_start < 0) _start = t;
        _reads++;
        if (position is { } p) { _recent.Add((t, p)); _recent.RemoveAll(r => t - r.T > 6); _unreadableSince = -1; }
        else { _unreadable++; if (_unreadableSince < 0) _unreadableSince = t; }
        switch (Phase)
        {
            case "waiting":
            {
                bool aboard = position is { } q
                    ? PointNavigation.Distance(q, board) > Moved || MathF.Abs(q.Y - board.Y) > 60
                    : Uses > 0 && t - _unreadableSince >= 1;
                if (aboard) { Phase = "riding"; _rideStart = t; _recent.Clear(); return Act.Wait; }
                if (t - _start > BoardTimeout)
                    return Fail($"No train took us aboard at the {fromName} platform in {BoardTimeout:F0} s ({Uses} uses facing the track). Is a train stopping there, and is \"use\" on the right mouse button?");
                if (t - _lastUse >= UseEvery) return Use(t);
                return Act.Wait;
            }
            case "riding":
            {
                if (t - _rideStart > RideTimeout)
                    return Fail(_unreadable * 2 > _reads
                        ? $"Could not read the position while on the train ({_unreadable} of {_reads} reads failed), so the {toName} stop was not seen; stopped after {RideTimeout / 60:F0} min."
                        : $"The train did not stop at the {toName} platform within {RideTimeout / 60:F0} min.");
                if (position is not { } q || !Still(t, StillFor)) return Act.Wait;
                // Put off (or stepped off) somewhere: on a platform floor and standing still.
                int on = platformAt(q);
                if (on == toPlatform && Still(t, 2)) return Done(on);
                if (on >= 0 && on != toPlatform && Still(t, 4)) return Done(on);
                if (besideDestination(q) && t - _lastUse >= UseEvery)
                {
                    if (++_leaveTries > 4) return Fail($"Could not step off the train at the {toName} platform (used it {_leaveTries - 1} times).");
                    Phase = "leaving"; _leaveStart = t;
                    return Use(t);
                }
                return Act.Wait;
            }
            case "leaving":
            {
                if (position is { } q && platformAt(q) == toPlatform && Still(t, 1)) return Done(toPlatform);
                if (t - _leaveStart >= LeaveWait) Phase = "riding";
                return Act.Wait;
            }
            default: return Phase == "done" ? Act.Done : Act.Fail;
        }
    }

    // True when the readings of the last `seconds` (and there are some that old) stay within a small circle.
    private bool Still(double t, double seconds)
    {
        if (_recent.Count < 2 || t - _recent[0].T < seconds) return false;
        var span = _recent.Where(r => t - r.T <= seconds).Select(r => r.P).ToList();
        return span.Count >= 2 && span.All(a => PointNavigation.Distance(a, span[^1]) < StillDistance);
    }

    private Act Use(double t) { _lastUse = t; Uses++; return Act.Use; }
    private Act Done(int platform) { Phase = "done"; Landed = platform; return Act.Done; }
    private Act Fail(string why) { Phase = "failed"; Message = why; return Act.Fail; }
}

/// <summary>
/// One subway ride live: walk to the boarding spot on the platform edge, face the track, then let
/// <see cref="SubwayRideLogic"/> decide when to "use" (right mouse button: the binding doors use) to
/// get on and off. F8 or losing focus stops it, as a walk. Throws with a message starting "Subway:" on failure.
/// </summary>
internal sealed class SubwayRide(PlayerReader reader, NavWorld nav, Travel travel, Travel.SubwayPlatform from, Travel.SubwayPlatform to,
    int pulse, string logPath, Hud hud, bool run, LiveSteer.Calibration? known, bool countdown)
{
    private const int Tick = 200;
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
        using var input = new SteerInput(reader, pulse, run);
        var clock = Stopwatch.StartNew();
        void Record(string kind, Vector3? at, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new
        {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = at is { } p ? new { p.X, p.Y, p.Z } : null, detail,
        }));
        static bool F8() => (Native.GetAsyncKeyState(0x77) & 0x8000) != 0;

        // 2. Face the track, so "use" points at the train when it stands there.
        var turns = new TurnController(Measured?.Gain ?? 0.0025f);
        for (int i = 0; i < 40; i++)
        {
            if (F8()) throw new OperationCanceledException("F8 stop pressed.");
            var s = reader.ReadSample();
            float angle = PointNavigation.SignedAngle(s.Forward, from.Track - s.Position);
            if (MathF.Abs(angle) < 0.08f) break;
            int pixels = turns.Pixels(angle * 0.8f, pulse * 4);
            for (int sent = 0; sent != pixels;) { sent += input.TurnPulse(pixels - sent); Thread.Sleep(16); }
            Thread.Sleep(120);
        }
        var start = reader.ReadSample();
        Record("ride-start", start.Position, new { from = from.Name, to = to.Name, board = new { from.Board.X, from.Board.Z }, track = new { from.Track.X, from.Track.Z } });

        // 3. Wait, board, ride, step off.
        var logic = new SubwayRideLogic(start.Position, to.Index, from.Name, to.Name, p => travel.PlatformAt(nav, p),
            p => to.Edge.Any(e => PointNavigation.Distance(e, p) < 420 && MathF.Abs(e.Y - p.Y) < 200));
        int elsewhere = 0;
        string lastPhase = "";
        while (true)
        {
            if (F8()) throw new OperationCanceledException("F8 stop pressed.");
            reader.RequireForeground();
            Vector3? at = null;
            try
            {
                var s = reader.ReadSample();
                int? sector = reader.ReadSectorId(s.World);
                if (sector is { } id && id != Travel.Subway)
                {
                    if (++elsewhere >= 3) throw new InvalidOperationException($"Subway: left the subway for {travel.SectorName(id)} during the ride.");
                }
                else { elsewhere = 0; at = s.Position; }
            }
            catch (InvalidOperationException e) when (!e.Message.StartsWith("Subway:", StringComparison.Ordinal) && e.Message != "The game closed.") { at = null; }
            var act = logic.Step(clock.Elapsed.TotalSeconds, at);
            if (logic.Phase != lastPhase)
            {
                lastPhase = logic.Phase;
                Record("phase", at, new { logic.Phase });
                Console.WriteLine(logic.Phase switch
                {
                    "waiting" => $"  waiting for a train at the {from.Name} platform",
                    "riding" => $"  aboard; riding to the {to.Name} platform",
                    "leaving" => $"  at the {to.Name} platform: stepping off",
                    _ => $"  {logic.Phase}",
                });
            }
            switch (act)
            {
                case SubwayRideLogic.Act.Use:
                    Record("use", at, new { logic.Phase, logic.Uses });
                    input.Use();
                    break;
                case SubwayRideLogic.Act.Done:
                    Landed = logic.Landed;
                    Record("done", at, new { landed = logic.Landed });
                    Console.WriteLine(Landed == to.Index ? $"  off the train at the {to.Name} platform" : $"  put off at another platform ({Landed}); planning again from there");
                    return;
                case SubwayRideLogic.Act.Fail:
                    Record("failed", at, new { logic.Message });
                    throw new InvalidOperationException("Subway: " + logic.Message);
            }
            hud.Show(Hud.Cyan, "TRAVERSAL  subway", logic.Phase switch
            {
                "waiting" => $"Waiting for a train at the {from.Name} platform ({clock.Elapsed.TotalSeconds:F0} s).",
                "riding" => $"On the train to the {to.Name} platform.",
                _ => $"Stepping off at the {to.Name} platform.",
            }, "F8 stops");
            Thread.Sleep(Tick);
        }
    }
}
