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
/// The live camera follow: mouse pulses only, turning left, right, up and down to keep facing the
/// target. No movement key and no click is ever sent, so you keep walking yourself. Ends by
/// returning why it stopped, or by throwing (F8, focus, zone change).
/// </summary>
internal sealed class CameraWatch(PlayerReader reader, WorldEntity target, int pulse, Hud hud, string logPath)
{
    private const int Tick = 16, PulseGap = 16, ReadEveryMs = 80, YawProbe = 96, PitchProbe = 64,
        ProbeStep = 6;   // Windows mouse acceleration: a pixel of a big pulse goes twice as far, and corrections are small.
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

        bool F8() => StopRequest.Made();

        PlayerSample Guard()
        {
            if (F8()) throw new OperationCanceledException("Stop pressed.");
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

        (float Yaw, float Pitch) View(PlayerSample s) => reader.ReadCamera(s)
            ?? throw new InvalidOperationException("The camera's angles could not be read on this game build. Camera follow stopped.");

        // The value once the game has caught up: a turn shows late, so one quick read measures only part of it.
        float Settled(Func<PlayerSample, float> value)
        {
            float last = value(Wait(60));
            int calm = 0;
            for (int i = 0; i < 25 && calm < 2; i++)
            {
                float now = value(Wait(60));
                calm = MathF.Abs(now - last) < 0.0015f ? calm + 1 : 0;
                last = now;
            }
            return last;
        }

        // Radians per pixel: test moves one way then the other, until two agree. The first pulses after
        // focus can be swallowed, so one measurement alone proves nothing (31 Oct: one this far off hunted).
        float Measure(string axis, int pixels, Func<PlayerSample, float> value, Action<int> send)
        {
            float? last = null;
            for (int attempt = 0, way = 1; attempt < 6; attempt++, way = -way)
            {
                float before = Settled(value);
                for (int sent = 0; sent < pixels; sent += ProbeStep) { send(way * ProbeStep); Wait(PulseGap); }
                float gain = (Settled(value) - before) / (way * pixels);
                Record("gain-probe", previous, new { axis, way, gain });
                if (MathF.Abs(gain) < 1e-5f) continue;
                if (last is { } g && Math.Sign(g) == Math.Sign(gain) && MathF.Abs(g - gain) < 0.35f * MathF.Abs(gain)) return (g + gain) / 2;
                last = gain;
            }
            throw new InvalidOperationException("Mouse-look did not respond steadily. Press Tab in Neocron so the free pointer disappears, close chat, try again.");
        }

        try
        {
            Console.WriteLine("Focus Neocron now (mouse-look on: press Tab so the pointer disappears). Starting in 5 s. F8 stops.");
            for (int i = 5; i > 0; i--)
            {
                hud.Post(Hud.Amber, $"CAMERA  starting in {i} s", "Click into Neocron now; press Tab so the pointer is hidden.", "F8 stops at any time.");
                for (int j = 0; j < 20; j++) { if (F8()) throw new OperationCanceledException("Stop pressed."); Thread.Sleep(50); }
            }

            var reference = CameraAim.Facing(View(Guard()).Yaw);
            float yawGain = Measure("yaw", YawProbe, s => PointNavigation.SignedAngle(reference, CameraAim.Facing(View(s).Yaw)), px => input.LookPulse(px, 0));
            float pitchGain = Measure("pitch", PitchProbe, s => View(s).Pitch, px => input.LookPulse(0, px));

            var watch = new TargetWatch(target, () => reader.ReadEntities().Entities, () => clock.ElapsedMilliseconds, ReadEveryMs, "Camera follow stopped.");
            Record("start", previous, new { target = target.Name, id = FollowCommand.Id(target), yawGain, pitchGain });
            Console.WriteLine($"Watching {target.Name}. The camera turns; you keep moving. F8 stops.");
            int ticks = 0;
            while (true)
            {
                var s = Guard();
                if (watch.Read() is { } gone) { Record("lost", s, new { gone }); hud.Post(Hud.Cyan, title, gone); return gone; }
                float away = PointNavigation.Distance(s.Position, watch.SeenAt);
                var view = View(s);
                float yawError = away < TooClose ? 0 : PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), watch.SeenAt - s.Position);
                float pitchError = CameraAim.PitchTo(s.Position, watch.SeenAt) - view.Pitch;
                int x = (int)MathF.Round(CameraAim.Turn(yawError) / yawGain), y = (int)MathF.Round(CameraAim.Turn(pitchError) / pitchGain);
                input.LookPulse(x, y);
                hud.Show(Hud.Green, title, $"{away:F0} units away, {MathF.Abs(yawError) * 180 / MathF.PI:F0} deg across, {MathF.Abs(pitchError) * 180 / MathF.PI:F0} deg up/down", "F8 stops");
                // A few lines a second: every tick would be 40 MB an hour.
                if (ticks++ % 10 == 0) Record("track", s, new { Angle = yawError, pitch = pitchError, pixels = x, pixelsY = y, away, target = new[] { watch.SeenAt.X, watch.SeenAt.Y, watch.SeenAt.Z } });
                Wait(Tick);
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
