using System.Numerics;
using System.Text.Json;
using NeocronSharp.Core;

internal static class TelemetryLineTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        void Reject(Action action) { try { action(); } catch (InvalidOperationException) { return; } throw new Exception("Invalid telemetry sample accepted"); }
        const long T = 1793156400123;
        test("Telemetry sample line has the fixed field order and recorder axes", () =>
        {
            string line = TelemetryLine.Sample(T, 1, 270, new(1.25f, 12.75f, -3.5f), -Vector3.UnitZ);
            check(line == "{\"t\":1793156400123,\"sector\":1,\"rotation\":270,\"x\":1.25,\"y\":12.75,\"z\":-3.5,\"fx\":0,\"fz\":-1,\"heading\":0,\"ok\":true}", line);
            check(!line.Contains('\n') && !line.Contains(' '), "One compact line per sample");
        });
        test("Telemetry heading matches the recorder convention (0 = -Z, 90 = +X)", () =>
        {
            double Heading(Vector3 forward) => JsonDocument.Parse(TelemetryLine.Sample(T, 3, null, Vector3.One, forward)).RootElement.GetProperty("heading").GetDouble();
            check(Heading(Vector3.UnitX) == 90 && Heading(Vector3.UnitZ) == 180 && Heading(-Vector3.UnitX) == 270, "Cardinal headings");
            var start = new DateTimeOffset(2026, 10, 28, 0, 0, 0, TimeSpan.Zero);
            var recording = new CoordinateRecording("t", 100, start, 0);
            var diagonal = Vector3.Normalize(new(1, 0, 1));
            var point = recording.Append(new(start, 0, 1, 0x10000, 0x20000, 1, null, Vector3.One, diagonal), "A");
            check(Math.Abs(Heading(diagonal) - point.HeadingDegrees) < 1e-4, "Telemetry and recorder headings agree");
        });
        test("Telemetry forward is the normalized ground component and rotation may be null", () =>
        {
            using var json = JsonDocument.Parse(TelemetryLine.Sample(T, 7, null, new(-1631.6165f, -255.9f, 781.7576f), new(3, 9, 4)));
            var root = json.RootElement;
            check(root.GetProperty("rotation").ValueKind == JsonValueKind.Null, "Missing map rotation is null");
            double fx = root.GetProperty("fx").GetDouble(), fz = root.GetProperty("fz").GetDouble();
            check(Math.Abs(fx - 0.6) < 1e-6 && Math.Abs(fz - 0.8) < 1e-6, "Pitch is dropped from the ground forward");
            check(root.GetProperty("x").GetSingle() == -1631.6165f && root.GetProperty("y").GetSingle() == -255.9f &&
                root.GetProperty("z").GetSingle() == 781.7576f, "Floats round-trip exactly");
            check(root.GetProperty("sector").GetInt32() == 7 && root.GetProperty("ok").GetBoolean(), "Sector and ok");
        });
        test("Telemetry sample from a CoordinateFix uses its capture time in unix milliseconds", () =>
        {
            var at = DateTimeOffset.FromUnixTimeMilliseconds(T);
            var fix = new CoordinateFix(at, 5, 1, 0x10000, 0x20000, 2, -90, new(10, 20, 30), Vector3.UnitX);
            check(TelemetryLine.Sample(fix).StartsWith("{\"t\":1793156400123,\"sector\":2,\"rotation\":-90,", StringComparison.Ordinal), "Fix fields");
        });
        test("Telemetry rejects non-finite, uninitialized or directionless samples", () =>
        {
            Reject(() => TelemetryLine.Sample(T, 1, 0, new(float.NaN, 0, 1), Vector3.UnitX));
            Reject(() => TelemetryLine.Sample(T, 1, 0, new(1, float.PositiveInfinity, 1), Vector3.UnitX));
            Reject(() => TelemetryLine.Sample(T, 1, 0, Vector3.Zero, Vector3.UnitX));
            Reject(() => TelemetryLine.Sample(T, 1, 0, Vector3.One, Vector3.UnitY));
            Reject(() => TelemetryLine.Sample(T, 1, 0, Vector3.One, new(float.NaN, 0, 1)));
            Reject(() => TelemetryLine.Sample(T, 0, 0, Vector3.One, Vector3.UnitX));
        });
        test("Telemetry error line is compact, escaped and keeps going", () =>
        {
            string line = TelemetryLine.Error(T, "The sector changed \"during\" sampling.\nRetrying.");
            check(line.StartsWith("{\"t\":1793156400123,\"ok\":false,\"error\":", StringComparison.Ordinal) && !line.Contains('\n'), line);
            using var json = JsonDocument.Parse(line);
            check(json.RootElement.GetProperty("error").GetString() == "The sector changed \"during\" sampling.\nRetrying.", "Message round-trips");
            check(line.All(c => c < 128), "ASCII-only output survives any console code page");
            check(JsonDocument.Parse(TelemetryLine.Error(T, "")).RootElement.GetProperty("error").GetString()!.Length > 0, "Never an empty error");
        });
    }
}
