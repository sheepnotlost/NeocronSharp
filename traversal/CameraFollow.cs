using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using NeocronSharp;
using NeocronSharp.Core;

namespace NavmeshPrototype;

/// <summary>
/// Is a followed actor still there, and where: read at most every <paramref name="everyMs"/> ms,
/// so a registry caught mid-update or one missed reading never ends a follow. Shared by the walk
/// (<see cref="FollowWalk"/>) and the camera (<see cref="CameraWatch"/>).
/// </summary>
/// <param name="stopped">The end of every message saying the follow is over, e.g. "Follow stopped."</param>
/// <param name="crossed">Why the target is gone when it vanished at a zone exit, if it did.</param>
internal sealed class TargetWatch(WorldEntity target, Func<IReadOnlyList<WorldEntity>> read, Func<long> millis, int everyMs,
    string stopped, Func<Vector3, string?>? crossed = null)
{
    private const int MissesToLose = 4, UnreadableToStop = 20;
    private long _readAt = -everyMs;
    private int _misses, _unreadable;

    public Vector3 SeenAt { get; private set; } = target.Position;

    /// <summary>Returns why the target is gone, or null while it is still there.</summary>
    public string? Read()
    {
        if (millis() - _readAt < everyMs) return null;
        _readAt = millis();
        WorldEntity? live = null;
        try
        {
            live = read().FirstOrDefault(e => e.Identity.Node == target.Identity.Node && e.Identity.Physics == target.Identity.Physics);
        }
        catch (InvalidOperationException e)
        {
            // Caught the registry mid-update: try again next time. For seconds on end, give up.
            if (++_unreadable >= UnreadableToStop) throw new InvalidOperationException($"The actors around you could not be read for 3 s ({e.Message}). {stopped}");
            return null;
        }
        _unreadable = 0;
        // A different actor at a reused address is not the target. (A player's name can fail to
        // read for a moment, showing as an unclassified character; that is still them.)
        if (live != null && live.Name != target.Name && live.Identity.Kind != EntityKind.UnclassifiedCharacter) live = null;
        if (live == null)
        {
            if (++_misses < MissesToLose) return null;
            return crossed?.Invoke(SeenAt) ?? $"{target.Name} is gone (out of range, logged off, despawned, or went through a door). {stopped}";
        }
        _misses = 0;
        if (live.Stats?.Dead == true || live.Player?.Dead == true) return $"{target.Name} died. {stopped}";
        SeenAt = live.Position;
        return null;
    }
}

/// <summary>
/// The live camera follow: mouse pulses only, turning left and right to keep facing the target
/// with the same steering as a walk. No movement key and no click is ever sent, so you keep
/// walking yourself. Ends by returning why it stopped, or by throwing (F8, focus, zone change).
/// </summary>
internal sealed class CameraWatch(PlayerReader reader, WorldEntity target, int pulse, Hud hud, string logPath)
{
    private const int Tick = 33, PulseGap = 16, ReadEveryMs = 80;
    /// <summary>Closer than this on the flat, "towards the target" has no useful direction.</summary>
    public const float TooClose = 5;

    public string Run()
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var input = new SteerInput(reader, pulse);
        var clock = Stopwatch.StartNew();
        string title = $"CAMERA  {target.Name}";
        var origin = reader.ReadSteady();
        int? sector = reader.ReadSectorId(origin.World);
        var previous = origin;

        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Y, s.Position.Z }, forward = new { s.Forward.X, s.Forward.Z }, detail }));

        bool F8() => (Native.GetAsyncKeyState(0x77) & 0x8000) != 0;

        PlayerSample Guard()
        {
            if (F8()) throw new OperationCanceledException("F8 stop pressed.");
            reader.RequireForeground();
            PlayerSample s;
            try { s = reader.ReadSteady(); }
            catch (InvalidOperationException) { throw new InvalidOperationException("Your character could not be read (zoning?). Camera follow stopped."); }
            if (s.Player != origin.Player || s.World != origin.World || s.Physics != origin.Physics || reader.ReadSectorId(s.World) != sector)
                throw new InvalidOperationException("You changed zone. Camera follow stopped.");
            return previous = s;
        }

        PlayerSample Wait(int ms)
        {
            long until = clock.ElapsedMilliseconds + ms;
            var s = Guard();
            while (clock.ElapsedMilliseconds < until) { Thread.Sleep((int)Math.Clamp(until - clock.ElapsedMilliseconds, 1, 15)); s = Guard(); }
            return s;
        }

        int Turn(int pixels, int pulses)
        {
            int sent = 0;
            for (int i = 0; i < pulses && sent != pixels; i++) { sent += input.TurnPulse(pixels - sent); Wait(PulseGap); }
            return sent;
        }

        try
        {
            Console.WriteLine("Focus Neocron now (mouse-look on: press Tab so the pointer disappears). Starting in 5 s. F8 stops.");
            for (int i = 5; i > 0; i--)
            {
                hud.Post(Hud.Amber, $"CAMERA  starting in {i} s", "Click into Neocron now; press Tab so the pointer is hidden.", "F8 stops at any time.");
                for (int j = 0; j < 20; j++) { if (F8()) throw new OperationCanceledException("F8 stop pressed."); Thread.Sleep(50); }
            }

            // Mouse gain from a small turn alone: a walk's test step would move the character.
            // The first pulses after focus can be swallowed, so a silent first probe is retried once.
            float gain = 0;
            var before = Guard();
            for (int attempt = 0; attempt < 2 && Math.Abs(gain) < 1e-6f; attempt++)
            {
                int sent = Turn(Math.Max(48, pulse * 4), 16);
                var after = Wait(80);
                float angle = PointNavigation.SignedAngle(before.Forward, after.Forward);
                Record("turn-probe", after, new { sent, angle });
                if (Math.Abs(angle) > 0.001f) gain = angle / sent;
                before = after;
            }
            if (Math.Abs(gain) < 1e-6f) throw new InvalidOperationException("Mouse-look did not respond. Press Tab in Neocron so the free pointer disappears, close chat, try again.");

            var turns = new TurnController(gain);
            var watch = new TargetWatch(target, () => reader.ReadEntities().Entities, () => clock.ElapsedMilliseconds, ReadEveryMs, "Camera follow stopped.");
            Record("start", before, new { target = target.Name, id = FollowCommand.Id(target), gain });
            Console.WriteLine($"Watching {target.Name}. The camera turns; you keep moving. F8 stops.");
            int lastPixels = 0;
            Vector3 lastForward = before.Forward;
            while (true)
            {
                var s = Guard();
                if (watch.Read() is { } gone) { Record("lost", s, new { gone }); hud.Post(Hud.Cyan, title, gone); return gone; }
                turns.Observe(lastPixels, PointNavigation.SignedAngle(lastForward, s.Forward));
                lastForward = s.Forward;
                float away = PointNavigation.Distance(s.Position, watch.SeenAt);
                var decision = Steering.Decide(s.Position, s.Forward, watch.SeenAt);
                int pixels = away < TooClose ? 0 : turns.Pixels(decision.TurnRadians, pulse * 2);
                int sent = pixels == 0 ? 0 : Turn(pixels, 2);
                lastPixels = sent;
                hud.Show(Hud.Green, title, $"{away:F0} units away, {MathF.Abs(decision.Angle) * 180 / MathF.PI:F0} deg off centre", "F8 stops");
                Record("track", s, new { decision.Angle, pixels = sent, away, target = new[] { watch.SeenAt.X, watch.SeenAt.Y, watch.SeenAt.Z } });
                if (sent == 0) Wait(Tick);
            }
        }
        catch (Exception error)
        {
            Record("stopped", previous, new { error.Message });
            hud.Post(Hud.Red, "CAMERA  stopped", error.Message);
            throw;
        }
    }
}
