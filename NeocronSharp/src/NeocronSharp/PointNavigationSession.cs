using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed record SavedSpot(Vector3 Position, ulong Player, ulong World, ulong Physics);

internal sealed class PointNavigationSession
{
    private readonly PlayerReader _reader;
    private readonly Action<string> _status;
    public PointNavigationSession(PlayerReader reader, Action<string> status) { _reader = reader; _status = status; }

    public async Task RunAsync(SavedSpot destination, string logPath, CancellationToken cancellation)
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var input = new GameInput(_reader);
        var timer = Stopwatch.StartNew();
        var previous = _reader.ReadSample();
        void Record(string kind, PlayerSample sample, string? message = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = timer.Elapsed.TotalSeconds, kind,
            position = new { sample.Position.X, sample.Position.Y, sample.Position.Z },
            forward = new { sample.Forward.X, sample.Forward.Y, sample.Forward.Z },
            distance = PointNavigation.Distance(sample.Position, destination.Position), message
        }));

        PlayerSample Guard()
        {
            cancellation.ThrowIfCancellationRequested();
            if ((Native.GetAsyncKeyState(0x77) & 0x8000) != 0) throw new OperationCanceledException("F8 stop pressed.", cancellation);
            _reader.RequireForeground();
            if (timer.Elapsed.TotalSeconds > 60) throw new InvalidOperationException("Navigation exceeded 60 seconds.");
            var sample = _reader.ReadSample();
            if (sample.Player != destination.Player || sample.World != destination.World || sample.Physics != destination.Physics)
                throw new InvalidOperationException("The saved spot belongs to another player/session. Save it again in the current area.");
            if (Vector3.Distance(sample.Position, previous.Position) > 60) throw new InvalidOperationException("Unexpected position jump; navigation stopped.");
            previous = sample;
            return sample;
        }

        async Task<PlayerSample> WaitAsync(int milliseconds)
        {
            long until = timer.ElapsedMilliseconds + milliseconds;
            PlayerSample sample = Guard();
            while (timer.ElapsedMilliseconds < until)
            {
                await Task.Delay(Math.Clamp((int)(until - timer.ElapsedMilliseconds), 1, 16), cancellation);
                sample = Guard();
            }
            return sample;
        }

        async Task<PlayerSample> SettleAsync()
        {
            input.Set(TravelInput.None);
            var sample = await WaitAsync(300);
            var confirmation = await WaitAsync(100);
            if (Vector3.Distance(sample.Position, confirmation.Position) > 0.4f)
                throw new InvalidOperationException("The character did not settle after releasing movement.");
            return confirmation;
        }

        async Task<PlayerSample> TurnAsync(int pixels)
        {
            foreach (int pulse in SteeringPulses.Split(pixels))
            {
                input.Turn(pulse);
                await WaitAsync(16);
            }
            return await WaitAsync(60);
        }

        try
        {
            var start = Guard();
            float startingDistance = PointNavigation.Distance(start.Position, destination.Position);
            PointNavigation.ValidateDestination(start.Position, destination.Position);
            Record("start", start, $"client={PlayerReader.SupportedSha256}; destination={destination.Position}");
            if (startingDistance <= PointNavigation.ArrivalTolerance)
            {
                Record("complete", start, "Already at the saved spot.");
                _status("You are already at the saved spot.");
                return;
            }
            var stable = await SettleAsync();
            if (Vector3.Distance(start.Position, stable.Position) > 0.5f)
                throw new InvalidOperationException("Stand still before starting navigation.");

            _status("Checking steering with a short forward step… F8 stops.");
            input.Set(TravelInput.Forward);
            await WaitAsync(80);
            var afterStep = await SettleAsync();
            Vector3 measured = afterStep.Position - stable.Position;
            PointNavigation.VerifyForward(stable.Forward, measured);
            Record("heading-verified", afterStep, $"alignment={Vector3.Dot(PointNavigation.Planar(stable.Forward), PointNavigation.Planar(measured)):F6}");
            float speed = Math.Clamp(measured.Length() / 0.08f, 20, 500);

            _status("Checking turning response… F8 stops.");
            int calibrationPixels = 16;
            var afterTurn = await TurnAsync(calibrationPixels);
            float angle = PointNavigation.SignedAngle(afterStep.Forward, afterTurn.Forward);
            Record("steering-probe", afterTurn, $"pixels={calibrationPixels}; headingChange={angle:F8}; displacement={PointNavigation.Distance(afterStep.Position, afterTurn.Position):F4}");
            if (Math.Abs(angle) < 0.001f)
            {
                afterTurn = await TurnAsync(24);
                calibrationPixels += 24;
                angle = PointNavigation.SignedAngle(afterStep.Forward, afterTurn.Forward);
                Record("steering-probe", afterTurn, $"pixels={calibrationPixels}; headingChange={angle:F8}");
            }
            float sensitivity = angle / calibrationPixels;
            if (Math.Abs(angle) < 0.001f)
                throw new InvalidOperationException("Mouse-look did not respond. In Neocron press Tab so the free mouse pointer disappears, close chat, then try again.");
            if (Math.Abs(angle) > 0.7f || PointNavigation.Distance(afterStep.Position, afterTurn.Position) > 2)
                throw new InvalidOperationException("Unexpected movement during the turning check. Leave the mouse and movement keys still while navigation runs.");
            Record("steering-verified", afterTurn, $"radiansPerPixel={sensitivity:F8}");

            float bestDistance = PointNavigation.Distance(afterTurn.Position, destination.Position);
            var progressTimer = Stopwatch.StartNew();
            var turningTimer = Stopwatch.StartNew();
            bool wasTurning = false;
            while (true)
            {
                var sample = Guard();
                var decision = PointNavigation.Decide(sample.Position, sample.Forward, destination.Position, sensitivity);
                Record("navigation", sample, $"travel={decision.Travel}; mouseX={decision.MouseX}");
                if (decision.NearDestination)
                {
                    var settled = await SettleAsync();
                    if (PointNavigation.Distance(settled.Position, destination.Position) <= PointNavigation.ArrivalTolerance &&
                        Math.Abs(settled.Position.Y - destination.Position.Y) <= 2)
                    {
                        Record("complete", settled, "Arrival confirmed after key release and stationary sampling.");
                        _status($"Arrived at the saved spot. Error {Vector3.Distance(settled.Position, destination.Position):F2} world units.");
                        return;
                    }
                    Record("endpoint-correction", settled);
                    continue;
                }
                if (decision.MouseX != 0)
                {
                    if (!wasTurning) turningTimer.Restart();
                    if (turningTimer.Elapsed.TotalSeconds > 8) throw new InvalidOperationException("Could not face the destination. Check mouse-look mode.");
                    var turned = await TurnAsync(decision.MouseX);
                    float observedGain = PointNavigation.SignedAngle(sample.Forward, turned.Forward) / decision.MouseX;
                    if (Math.Abs(observedGain) is > 0.00005f and < 0.08f && Math.Sign(observedGain) == Math.Sign(sensitivity))
                        sensitivity = sensitivity * 0.6f + observedGain * 0.4f;
                    wasTurning = true;
                    progressTimer.Restart();
                    _status($"Turning toward saved spot — {decision.Distance:F0} world units away. F8 stops.");
                    continue;
                }
                wasTurning = false;
                if (decision.Distance < bestDistance - 0.5f) { bestDistance = decision.Distance; progressTimer.Restart(); }
                else if (progressTimer.Elapsed.TotalSeconds > 1.8)
                    throw new InvalidOperationException("Movement is blocked or not approaching the spot. This version needs a clear path.");
                if (decision.Distance > startingDistance + 40)
                    throw new InvalidOperationException("Movement is taking the character away from the saved spot.");
                _status($"Walking to saved spot — {decision.Distance:F1} world units away. F8 stops.");
                input.Set(decision.Travel);
                if (decision.Distance < Math.Max(30, speed * 0.15f))
                {
                    int pulseMilliseconds = Math.Clamp((int)((decision.Distance - PointNavigation.ArrivalTolerance) / speed * 350), 5, 18);
                    await WaitAsync(pulseMilliseconds);
                    input.Set(TravelInput.None);
                    await WaitAsync(110);
                }
                else await WaitAsync(20);
            }
        }
        catch (Exception error)
        {
            input.Release();
            Record("stopped", previous, error.Message);
            throw;
        }
        finally { input.Release(); }
    }
}
