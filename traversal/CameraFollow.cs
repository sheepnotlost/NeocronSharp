using System.Diagnostics;
using System.Globalization;
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
    string stopped, Func<Vector3, string?>? crossed = null, bool corpse = false)
{
    private const int MissesToLose = 4, UnreadableToStop = 20;
    private long _readAt = -everyMs;
    private int _misses, _unreadable;

    public Vector3 SeenAt { get; private set; } = target.Position;

    /// <summary>The target's health at the last reading, when it can be read.</summary>
    public int? Health { get; private set; } = target.Stats?.Health?.RawCurrent;

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
        // read for a moment, showing as an unclassified character; that is still them. Never for
        // an NPC: the unnamed character could be a player, with the left button held.)
        if (live != null && (target.Identity.Kind == EntityKind.Npc
                ? live.Identity.Kind != EntityKind.Npc || live.Name != target.Name
                : live.Name != target.Name && live.Identity.Kind != EntityKind.UnclassifiedCharacter)) live = null;
        if (live == null)
        {
            if (++_misses < MissesToLose) return null;
            return crossed?.Invoke(SeenAt) ?? $"{target.Name} is gone (out of range, logged off, despawned, or went through a door). {stopped}";
        }
        _misses = 0;
        if (!corpse && (live.Stats?.Dead == true || live.Player?.Dead == true)) return $"{target.Name} died. {stopped}";
        SeenAt = live.Position;
        Health = live.Stats?.Health?.RawCurrent ?? Health;
        return null;
    }
}

/// <summary>What a camera run does besides watching. The loot sequence runs one after another, so it skips the
/// countdown (<see cref="Now"/>) and passes on the mouse gains the first run measured.</summary>
internal sealed record CameraPlan(bool HoldLeft = false, bool Now = false, (float Yaw, float Pitch)? Gains = null, double GiveUpSeconds = 0, bool Box = false,
    bool MeasureOnly = false, bool Sight = false, float BackTo = 0, ShotLine? Shots = null, bool Use = false,
    bool Pin = false, bool Pushers = false, IReadOnlyCollection<string>? Avoid = null, bool Kite = false,
    bool Stay = false);   // never take a step: a blocked shot ends the fight instead of stepping aside (Stand and hunt)

/// <summary>
/// The live camera follow: mouse pulses only, turning left, right, up and down to keep facing the
/// target. No movement key is ever sent, so you keep walking yourself, and no click unless
/// <paramref name="plan"/> asks for the left button, held from the first time the crosshair is
/// on an NPC until the run ends. With <see cref="CameraPlan.Box"/> it instead runs to a dead NPC and
/// right-clicks its loot box. Ends by returning why it stopped, or by throwing (F8, focus, zone change).
/// </summary>
internal sealed class CameraWatch(PlayerReader reader, WorldEntity target, int pulse, CameraPlan plan, Hud hud, string logPath)
{
    private const int Tick = 16, PulseGap = 16, ReadEveryMs = 80, YawProbe = 96, PitchProbe = 64,
        ProbeStep = 6;   // Windows mouse acceleration: a pixel of a big pulse goes twice as far, and corrections are small.
    /// <summary>Closer than this on the flat, "towards the target" has no useful direction.</summary>
    public const float TooClose = 5;
    /// <summary>Radians per pixel of mouse, once measured.</summary>
    public (float Yaw, float Pitch)? Measured { get; private set; }
    /// <summary>Where a run to a loot box starts to stop. The view stops at 43 degrees down, so the crosshair can't reach the ground nearer than about 88 units, and W up slides on. Not yet set live.</summary>
    public const float BoxReach = 120;
    private const float FacingToRun = 0.35f;
    private const int StuckAfterMs = 3000, BoxAimMs = 2000, UseAimMs = 5000, UseSteadyMs = 625, LookEveryMs = 120,
        MarkEveryMs = 60, PushEveryMs = 250, BodyFrom = 80;   // a look for the game's marks on the mob: about 5 ms for the middle of a 1080 screen
    /// <summary>Seconds aimed at the target with the game not targeting it before the shot is called blocked.</summary>
    private const double BlindSeconds = 5, StepAsideSeconds = 6;   // 5: time for the search round the mob, and more
    private const float StuckBelow = 15;

    public string Run()
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var input = new SteerInput(reader, pulse, plan.Box);
        var clock = Stopwatch.StartNew();
        string title = $"CAMERA  {target.Name}";
        var origin = reader.ReadSteady();
        int? sector = reader.ReadSectorId(origin.World);
        var previous = origin;
        var lapse = new ReadLapse();

        void Record(string kind, PlayerSample s, object? detail = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = clock.Elapsed.TotalSeconds, kind,
            position = new { s.Position.X, s.Position.Y, s.Position.Z }, forward = new { s.Forward.X, s.Forward.Z }, detail }));

        bool F8() => StopRequest.Made();

        // The notebook: one line per fight, and what it learned about the mob.
        string logs = Path.GetDirectoryName(logPath) ?? ".";
        FightNotes? notes = null;
        ScreenAim? seen = null;
        void Note(string ended)
        {
            if (notes == null) return;
            try
            {
                HuntNotes.Add(logs, notes.Line(clock.Elapsed.TotalSeconds, ended));
                HuntNotes.Remember(logs, target.Name, notes.BodyHeight, seen?.SizeAtRange);
            }
            catch (IOException) { }   // a notebook that can't be written must not end a fight
            notes = null;
        }
        string Done(string text) { Note(text); return text; }

        PlayerSample Guard()
        {
            if (F8()) throw new OperationCanceledException("Stop pressed.");
            reader.RequireForeground();
            if (lapse.Read(reader.ReadSample, clock.Elapsed.TotalSeconds, "Camera follow stopped.") is not { } s) return previous;
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
            for (int i = 0; i < 25 && calm < (plan.MeasureOnly ? 10 : 2); i++)   // A healer may be in a VM, where a frame can take half a second.
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

        // Run to the body facing it, with Shift held, then put the crosshair on it and right-click.
        string RunToBox(float yawGain, float pitchGain)
        {
            var box = target.Position;
            var stuckFrom = Guard().Position;
            long stuckAt = clock.ElapsedMilliseconds;
            while (true)
            {
                var s = Guard();
                float away = PointNavigation.Distance(s.Position, box);
                if (away <= BoxReach) break;
                float error = PointNavigation.SignedAngle(CameraAim.Facing(View(s).Yaw), box - s.Position);
                input.Walk(MathF.Abs(error) < FacingToRun);
                input.LookPulse((int)MathF.Round(CameraAim.Turn(error) / yawGain), 0);
                if (clock.ElapsedMilliseconds - stuckAt > StuckAfterMs)
                {
                    if (PointNavigation.Distance(s.Position, stuckFrom) < StuckBelow) throw new InvalidOperationException($"Could not reach the body of {target.Name}. Stopped.");
                    stuckFrom = s.Position; stuckAt = clock.ElapsedMilliseconds;
                }
                hud.Show(Hud.Green, $"LOOT  {target.Name}", $"{away:F0} units away", "F8 stops");
                Wait(Tick);
            }
            input.Walk(false);
            if (!AimAt(box, BoxAimMs, yawGain, pitchGain, () => true)) throw new InvalidOperationException($"Could not aim at the body of {target.Name}.");   // A right-click lands on whatever is there.
            Record("box", previous, new { target = target.Name });
            input.Use();
            return $"Right-clicked the body of {target.Name}.";
        }

        // Put the crosshair on a point, for as long as it takes ready to agree.
        bool AimAt(Vector3 point, int ms, float yawGain, float pitchGain, Func<bool> ready)
        {
            for (long until = clock.ElapsedMilliseconds + ms; clock.ElapsedMilliseconds < until; Wait(Tick))
            {
                var s = Guard();
                var view = View(s);
                float yawError = PointNavigation.Distance(s.Position, point) < TooClose ? 0 : PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), point - s.Position);
                float pitchError = CameraAim.PitchTo(s.Position, point) - view.Pitch;
                if (CameraAim.OnTarget(yawError, pitchError) && ready()) return true;
                input.LookPulse((int)MathF.Round(CameraAim.Turn(yawError) / yawGain), (int)MathF.Round(CameraAim.Turn(pitchError) / pitchGain));
            }
            return false;
        }

        // Crosshair on a standing NPC, then right-click to talk: at once with the game's target bar up to prove it, or once it has
        // held there. The bar's place follows the screen size and UI scale, and on another PC it was never seen (2 Nov).
        string UseNpc(float yawGain, float pitchGain)
        {
            var steady = new SteadyAim(UseSteadyMs);
            var snap = new SnapAim();
            var body = target.Position + new Vector3(0, CameraAim.BodyMiddle, 0);
            for (long until = clock.ElapsedMilliseconds + UseAimMs; clock.ElapsedMilliseconds < until; Wait(Tick))
            {
                var s = Guard();
                var view = View(s);
                float yawError = PointNavigation.Distance(s.Position, body) < TooClose ? 0 : PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), body - s.Position);
                var turn = snap.Step(clock.ElapsedMilliseconds, yawError, CameraAim.PitchTo(s.Position, body) - view.Pitch);
                input.LookBurst((int)MathF.Round(turn.Yaw / yawGain), (int)MathF.Round(turn.Pitch / pitchGain));
                if (!snap.Done || !steady.Ready(clock.ElapsedMilliseconds, TargetBar.Showing(reader.Window))) continue;
                Record("use", previous, new { target = target.Name });
                input.Use();
                return $"Right-clicked {target.Name}.";
            }
            return $"Could not put the crosshair on {target.Name}.";
        }

        try
        {
            if (!plan.Now) Console.WriteLine("Focus Neocron now (mouse-look on: press Tab so the pointer disappears). Starting in 5 s. F8 stops.");
            for (int i = plan.Now ? 0 : 5; i > 0; i--)
            {
                hud.Post(Hud.Amber, $"CAMERA  starting in {i} s", "Click into Neocron now; press Tab so the pointer is hidden.", "F8 stops at any time.");
                for (int j = 0; j < 20; j++) { if (F8()) throw new OperationCanceledException("Stop pressed."); Thread.Sleep(50); }
            }

            float yawGain, pitchGain;
            if (plan.Gains is { } known) (yawGain, pitchGain) = known;
            else
            {
                var reference = CameraAim.Facing(View(Guard()).Yaw);
                yawGain = Measure("yaw", YawProbe, s => PointNavigation.SignedAngle(reference, CameraAim.Facing(View(s).Yaw)), px => input.LookPulse(px, 0));
                pitchGain = Measure("pitch", PitchProbe, s => View(s).Pitch, px => input.LookPulse(0, px));
                Console.WriteLine(string.Create(CultureInfo.InvariantCulture, $"gains {yawGain} {pitchGain}"));
            }
            Measured = (yawGain, pitchGain);
            if (plan.MeasureOnly) return "";
            if (plan.Box) return RunToBox(yawGain, pitchGain);
            if (plan.Use) return UseNpc(yawGain, pitchGain);

            var watch = new TargetWatch(target, () => reader.ReadEntities().Entities, () => clock.ElapsedMilliseconds, ReadEveryMs, "Camera follow stopped.");
            Record("start", previous, new { target = target.Name, id = FollowCommand.Id(target), yawGain, pitchGain });
            Console.WriteLine($"Watching {target.Name}. The camera turns; you keep moving. F8 stops.");
            int ticks = 0;
            int? health = watch.Health;
            long lastHurt = 0, lookAt = 0, markAt = 0;
            int marksLogged = 0;
            var sight = new SightWatch();
            var learned = plan.Sight ? HuntNotes.Recall(logs, target.Name) : null;
            float aimHeight = learned?.BodyHeight is { } body ? Math.Clamp(body, -30, 150) : ScreenAim.MemoryHeight;
            var screen = new ScreenAim(learned is { WidthAtRange: { } w, HeightAtRange: { } h } ? (w, h) : null);
            seen = screen;
            if (plan.Sight)
            {
                notes = new FightNotes(target.Name, FollowCommand.Id(target), PointNavigation.Distance(previous.Position, watch.SeenAt), aimHeight);
                if (learned?.BodyHeight != null) Console.WriteLine($"Aiming {aimHeight:F0} units above {target.Name}'s feet, as learned in {learned.Fights} fights.");
            }
            var track = new TrackAim();
            using var pin = plan.Pin && plan.Sight ? CameraWriter.Open(reader.Process.Id) : null;
            if (plan.Pin && plan.Sight) Console.WriteLine(pin == null ? "Could not open the game to pin the camera: the mouse aims." : "Pinning the camera.");
            bool pinned = pin != null;
            if (notes != null) notes.Pin = pinned;
            long pushAt = 0;
            var kite = new Kite();
            bool cornerSaid = false;
            var backOff = new BackOff(plan.BackTo);
            double aimedAt = -1, clearAt = -1, stepFrom = -1;
            float stepSide = 0;
            while (true)
            {
                var s = Guard();
                if (watch.Read() is { } gone) { Record("lost", s, new { gone }); hud.Post(Hud.Cyan, title, gone); return Done(gone); }
                float away = PointNavigation.Distance(s.Position, watch.SeenAt);
                var view = View(s);
                // Point blank with no mark, low: a parasite lies flat at your feet, and a slugger's legs are still body.
                float height = !plan.Sight ? CameraAim.ShotHeight
                    : away < ScreenAim.PointBlank && !screen.Seen(clock.Elapsed.TotalSeconds) ? Math.Min(aimHeight, ScreenAim.PointBlankHeight) : aimHeight;
                var point = watch.SeenAt + new Vector3(0, height, 0);
                float yawToMemory = away < TooClose ? 0 : PointNavigation.SignedAngle(CameraAim.Facing(view.Yaw), watch.SeenAt - s.Position);
                float pitchToMemory = CameraAim.PitchTo(s.Position, point) - view.Pitch;
                double now = clock.Elapsed.TotalSeconds;
                if (plan.Sight && clock.ElapsedMilliseconds >= markAt)
                {
                    markAt = clock.ElapsedMilliseconds + MarkEveryMs;
                    if (TargetLock.Look(reader.Window) is { } look)
                    {
                        bool wasLocked = screen.Locked(now);
                        bool took = screen.See(now, look.Marks, yawToMemory, pitchToMemory, look.ClientHeight, MathF.Sign(yawGain), away);
                        if (took && notes != null)
                        {
                            notes.Mark(now, screen.Mark!.Value.Measured);
                            // Close up the eye height guessed for the camera is too rough to take the body's height from.
                            if (screen.Locked(now) && away >= BodyFrom)
                            {
                                // Where the body is drawn, above the mob's feet: the aim point's line turned by what the screen showed.
                                float eye = s.Position.Y + CameraAim.EyeHeight, flat = Math.Max(1, away);
                                float drawn = eye + MathF.Tan(MathF.Atan2(point.Y - eye, flat) + screen.Offset.Pitch) * flat;
                                notes.Body(drawn - watch.SeenAt.Y);
                            }
                        }
                        if (took && marksLogged++ % 5 == 0)
                            Record("mark", s, new { x = screen.Mark!.Value.X, y = screen.Mark.Value.Y, measured = screen.Mark.Value.Measured, marks = look.Marks.Count,
                                offsetYaw = screen.Offset.Yaw, offsetPitch = screen.Offset.Pitch, locked = screen.Locked(now), away });
                        if (!wasLocked && screen.Locked(now))
                        {
                            Record("aim-locked", s, new { offsetYaw = screen.Offset.Yaw, offsetPitch = screen.Offset.Pitch, away });
                            Console.WriteLine($"Crosshair on {target.Name}'s body.");
                        }
                    }
                }
                var (yawError, pitchError) = plan.Sight ? screen.Error(now, yawToMemory, pitchToMemory, away) : (yawToMemory, pitchToMemory);
                int x = 0, y = 0;
                if (!plan.Sight)
                {
                    x = CameraAim.Pixels(CameraAim.Turn(yawError, away), yawGain); y = CameraAim.Pixels(CameraAim.Turn(pitchError, away), pitchGain);
                    input.LookPulse(x, y);
                }
                else if (pinned && !pin!.Turn(s.Player, yawError, pitchError) && !pin.Works)
                {
                    pinned = false;
                    Record("pin-refused", s, new { yawError, pitchError });
                    Console.WriteLine("The game put its own camera back: the mouse aims instead.");
                    if (notes != null) notes.PinRefused = true;
                }
                else if (!pinned)
                {
                    var want = track.Want(now, yawError, pitchError, away);
                    x = Math.Clamp((int)MathF.Round(want.Yaw / yawGain), -4 * input.Pulse, 4 * input.Pulse);
                    y = Math.Clamp((int)MathF.Round(want.Pitch / pitchGain), -4 * input.Pulse, 4 * input.Pulse);
                    input.LookSteps(x, y);
                    track.Sent(now, x * yawGain, y * pitchGain);
                }
                if (plan.Pushers && clock.ElapsedMilliseconds >= pushAt)
                {
                    pushAt = clock.ElapsedMilliseconds + PushEveryMs;
                    IReadOnlyList<WorldEntity> around;
                    try { around = FollowCommand.ReadSnapshot(reader).Entities; }
                    catch (InvalidOperationException) { around = Array.Empty<WorldEntity>(); }   // caught mid-update: next time
                    if (Pushers.OnYou(s.Position, around, target, away, plan.Avoid) is { } pusher)
                    {
                        input.HoldLeft(false);
                        string other = $"Switching to {FollowCommand.Id(pusher)} {pusher.Name}: it is on you.";
                        Record("switch", s, new { to = pusher.Name, id = FollowCommand.Id(pusher), away });
                        hud.Post(Hud.Amber, title, other);
                        return Done(other);
                    }
                }
                // Any fall counts, not just a new lowest: a mob healing between hits was given up on while it was being hurt.
                if (watch.Health < health) lastHurt = clock.ElapsedMilliseconds;
                health = watch.Health;
                bool onTarget = CameraAim.OnTarget(yawError, pitchError);
                var shotFrom = s.Position + new Vector3(0, CameraAim.EyeHeight, 0);
                var shotTo = point;
                string? blocker = plan.Shots?.Blocker(shotFrom, shotTo);
                if (plan.Sight)
                {
                    if (clock.ElapsedMilliseconds >= lookAt)
                    {
                        lookAt = clock.ElapsedMilliseconds + LookEveryMs;
                        sight.Update(now, screen.Seen(now) || away < ScreenAim.PointBlank || TargetBar.Showing(reader.Window));
                    }
                    if (onTarget && aimedAt < 0) aimedAt = now;
                    var was = backOff.Now;
                    // A cactus dropping the target bar is not the target limit.
                    backOff.Update(now, sight.Seen(now) || blocker != null, sight.Showing, away, s.Position);
                    input.Back(backOff.Now == BackOff.Phase.Backing);
                    input.Walk(backOff.Now == BackOff.Phase.Returning);
                    if (was == BackOff.Phase.Backing && backOff.Now == BackOff.Phase.Returning)
                        Console.WriteLine($"Target limit {backOff.Limit:F0} units.");
                    if (input.LeftHeld && (!screen.Firing(now, away) || blocker != null)) input.HoldLeft(false);   // Off the body, or something in the way: the shots would only hit that.
                    var keep = plan.Kite && backOff.Now == BackOff.Phase.Done ? kite.Step(now, away, s.Position) : (Back: false, Side: 0);
                    if (keep.Back) input.Back(true);
                    if (kite.Cornered && !cornerSaid)
                    {
                        cornerSaid = true;
                        Record("cornered", s, new { away });
                        Console.WriteLine("Backed into a wall: standing here and shooting.");
                    }
                    notes?.Tick(now, away, screen.Locked(now), screen.Searching(now), keep.Back);
                    if (blocker == null) { input.Strafe(keep.Side); stepFrom = -1; }
                    else
                    {
                        clearAt = now;
                        if (backOff.Now is BackOff.Phase.Waiting or BackOff.Phase.Done)
                        {
                            if (stepFrom < 0)
                            {
                                stepFrom = now;
                                stepSide = plan.Stay ? 0 : plan.Shots!.ClearSide(shotFrom, shotTo) ?? 0;
                                Record("in-the-way", s, new { blocker, stepSide });
                                Console.WriteLine($"{blocker} is in the way of {target.Name}: stepping aside.");
                            }
                            if (stepSide == 0 || now - stepFrom > StepAsideSeconds)
                            {
                                string blocked = $"No line of sight to {target.Name}: {blocker} is in the way. Camera follow stopped.";
                                Record("blocked", s, new { away, blocker });
                                return Done(blocked);
                            }
                            input.Strafe((int)stepSide);
                        }
                    }
                    if (aimedAt >= 0 && backOff.Now != BackOff.Phase.Returning && now - Math.Max(Math.Max(aimedAt, sight.SeenAt), clearAt) > BlindSeconds)
                    {
                        string blocked = $"No line of sight to {target.Name}. Camera follow stopped.";
                        Record("blocked", s, new { away });
                        return Done(blocked);
                    }
                }
                if (input.LeftHeld && plan.GiveUpSeconds > 0 && clock.ElapsedMilliseconds - lastHurt > plan.GiveUpSeconds * 1000)
                {
                    string missed = $"No damage to {target.Name} for {plan.GiveUpSeconds:F0} s. Camera follow stopped.";
                    Record("gave-up", s, new { missed });
                    return Done(missed);
                }
                if (plan.HoldLeft && !input.LeftHeld && onTarget && (!plan.Sight || (blocker == null && screen.Firing(now, away) && backOff.Now == BackOff.Phase.Done)))
                {
                    input.HoldLeft(true);
                    if (lastHurt == 0) lastHurt = clock.ElapsedMilliseconds;
                    Record("hold", s, new { yawError, pitchError, away });
                    Console.WriteLine($"On {target.Name}: holding the left mouse button.");
                }
                hud.Show(Hud.Green, title, $"{away:F0} units away, {MathF.Abs(yawError) * 180 / MathF.PI:F0} deg across, {MathF.Abs(pitchError) * 180 / MathF.PI:F0} deg up/down", "F8 stops");
                // A few lines a second: every tick would be 40 MB an hour.
                if (ticks++ % 10 == 0) Record("track", s, new { Angle = yawError, pitch = pitchError, pixels = x, pixelsY = y, away, offsetYaw = screen.Offset.Yaw, offsetPitch = screen.Offset.Pitch, searching = plan.Sight && screen.Searching(now), target = new[] { watch.SeenAt.X, watch.SeenAt.Y, watch.SeenAt.Z } });
                Wait(Tick);
            }
        }
        catch (Exception error)
        {
            Record("stopped", previous, new { error.Message });
            Note(error.Message);
            hud.Post(Hud.Red, "CAMERA  stopped", error.Message);
            throw;
        }
    }
}
