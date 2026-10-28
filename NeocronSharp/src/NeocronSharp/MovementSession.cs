using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class MovementSession
{
    private readonly PlayerReader _reader;
    private readonly Action<string> _status;
    public MovementSession(PlayerReader reader, Action<string> status) { _reader = reader; _status = status; }

    public async Task RunAsync(string logPath, CancellationToken cancellation)
    {
        using var log = new StreamWriter(logPath) { AutoFlush = true };
        using var input = new GameInput(_reader);
        var total = Stopwatch.StartNew();
        PlayerSample initial = _reader.ReadSample();
        PlayerSample previous = initial;
        void Record(string kind, PlayerSample sample, int legs = 0, string? message = null) => log.WriteLine(JsonSerializer.Serialize(new {
            timeUtc = DateTimeOffset.UtcNow, elapsedSeconds = total.Elapsed.TotalSeconds, kind,
            position = new { sample.Position.X, sample.Position.Y, sample.Position.Z }, completedLegs = legs, message
        }));

        PlayerSample Guard()
        {
            cancellation.ThrowIfCancellationRequested();
            if ((Native.GetAsyncKeyState(0x77) & 0x8000) != 0) // F8
                throw new OperationCanceledException("F8 stop pressed.", cancellation);
            _reader.RequireForeground();
            if (total.Elapsed > TimeSpan.FromSeconds(60)) throw new InvalidOperationException("The movement test exceeded 60 seconds.");
            var sample = _reader.ReadSample();
            if (sample.Player != initial.Player || sample.World != initial.World || sample.Physics != initial.Physics)
                throw new InvalidOperationException("Player/zone identity changed during the test.");
            if (Vector3.Distance(sample.Position, previous.Position) > 100)
                throw new InvalidOperationException("Position jumped unexpectedly. Movement stopped.");
            previous = sample;
            return sample;
        }

        async Task<PlayerSample> SettleAsync(int milliseconds)
        {
            input.Set(TravelInput.None);
            var timer = Stopwatch.StartNew();
            PlayerSample sample = Guard();
            while (timer.ElapsedMilliseconds < milliseconds)
            {
                await Task.Delay(20, cancellation);
                sample = Guard();
            }
            return sample;
        }

        try
        {
            Record("start", initial, message: $"Evolution 2.5.902 / {_reader.Process.Id} / {_reader.Executable} / {PlayerReader.SupportedSha256}");
            var stable = await SettleAsync(300);
            if (Vector3.Distance(initial.Position, stable.Position) > 0.5f)
                throw new InvalidOperationException("Character was already moving. Stand still before starting.");
            Vector3 a = stable.Position;
            _status("Leg 1/4: recording a short forward segment… F8 stops.");
            var outbound = Stopwatch.StartNew();
            input.Set(TravelInput.Forward);
            var outboundPoints = new List<Vector3> { a };
            while (outbound.ElapsedMilliseconds < 600)
            {
                await Task.Delay(20, cancellation);
                var sample = Guard();
                outboundPoints.Add(sample.Position);
                Record("recording", sample);
                if (Vector3.Distance(a, sample.Position) > 300)
                    throw new InvalidOperationException("The forward segment exceeded the short-distance limit.");
            }
            var endpoint = await SettleAsync(250);
            var route = new StraightLineRoute(a, endpoint.Position);
            // Verify that the recorded first leg was straight, not just its endpoints.
            var axis = Vector3.Normalize(route.B - a);
            foreach (var point in outboundPoints)
            {
                var relative = point - a;
                if ((relative - Vector3.Dot(relative, axis) * axis).Length() > Math.Max(3, route.Length * 0.04f))
                    throw new InvalidOperationException("The recorded forward segment was not straight.");
            }
            Record("arrived-B", endpoint, 1, $"distance={route.Length:F3}; tolerance={route.Tolerance:F3}");
            var legTimer = Stopwatch.StartNew();
            var progressTimer = Stopwatch.StartNew();
            Vector3 progressPosition = endpoint.Position;
            bool correctionPause = false;
            while (!route.Complete)
            {
                var sample = Guard();
                if (legTimer.Elapsed > TimeSpan.FromSeconds(20)) throw new InvalidOperationException("An endpoint could not be reached within 20 seconds.");
                RouteDecision decision = route.Observe(sample.Position, commitArrival: false);
                input.Set(decision.Input);
                Record(decision.Arrived ? "settling" : "moving", sample, decision.CompletedLegs);
                if (decision.Arrived)
                {
                    // Release and verify the character actually stopped at the measured endpoint.
                    var settled = await SettleAsync(250);
                    var settledDecision = route.Observe(settled.Position);
                    if (!settledDecision.Arrived)
                    {
                        Record("endpoint-correction", settled, route.CompletedLegs);
                        continue;
                    }
                    Record(route.CompletedLegs % 2 == 0 ? "arrived-A" : "arrived-B", settled, route.CompletedLegs);
                    Record("endpoint-settled", settled, route.CompletedLegs);
                    if (settledDecision.Complete) break;
                    legTimer.Restart(); progressTimer.Restart(); progressPosition = settled.Position;
                    correctionPause = false;
                }
                else
                {
                    _status($"Leg {route.CompletedLegs+1}/4 — X {sample.Position.X:F1}, Y {sample.Position.Y:F1}, Z {sample.Position.Z:F1}. F8 stops.");
                    if (progressTimer.ElapsedMilliseconds >= 1200)
                    {
                        if (Vector3.Distance(progressPosition, sample.Position) < 0.5f)
                            throw new InvalidOperationException("Character is not making progress. A wall, menu or disabled control may be blocking movement.");
                        progressTimer.Restart(); progressPosition = sample.Position;
                    }
                    // Near an endpoint use individual short pulses, with time to observe the result.
                    float goalDistance = Vector3.Distance(sample.Position, route.CompletedLegs % 2 == 1 ? route.A : route.B);
                    if (goalDistance < Math.Max(12, route.Length * 0.15f))
                    {
                        await Task.Delay(15, cancellation);
                        input.Set(TravelInput.None);
                        await SettleAsync(correctionPause ? 140 : 120);
                        correctionPause = true;
                    }
                    else await Task.Delay(20, cancellation);
                }
            }
            var final = Guard();
            Record("complete", final, 4, $"returnError={Vector3.Distance(final.Position, route.A):F3}");
            _status($"Completed two round trips. Return error {Vector3.Distance(final.Position, route.A):F2} world units. Log: {Path.GetFileName(logPath)}");
        }
        catch (Exception error)
        {
            // Key-up runs before logging/UI work, including on cancellation and focus loss.
            input.Release();
            Record("stopped", previous, message: error.Message);
            throw;
        }
        finally { input.Release(); }
    }
}
