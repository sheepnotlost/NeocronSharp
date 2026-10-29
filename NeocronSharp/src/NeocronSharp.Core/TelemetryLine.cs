using System.Numerics;
using System.Text;
using System.Text.Json;

namespace NeocronSharp.Core;

/// <summary>One JSON object per line for the --telemetry stream. Field order is fixed:
/// sample: {"t","sector","rotation","x","y","z","fx","fz","heading","ok":true};
/// failure: {"t","ok":false,"error"}. X/Z are ground, Y is height; fx/fz is the ground-plane unit forward vector;
/// heading follows the recorder (0 = -Z, 90 = +X).</summary>
public static class TelemetryLine
{
    private static readonly JsonWriterOptions Options = new() { Indented = false };

    public static string Sample(CoordinateFix fix) =>
        Sample(fix.CapturedAt.ToUnixTimeMilliseconds(), fix.SectorId, fix.MapRotationDegrees, fix.Position, fix.Forward);

    public static string Sample(long unixMilliseconds, int sector, int? rotationDegrees, Vector3 position, Vector3 forward)
    {
        if (!float.IsFinite(position.X) || !float.IsFinite(position.Y) || !float.IsFinite(position.Z))
            throw new InvalidOperationException("Position is not finite.");
        if (position == Vector3.Zero) throw new InvalidOperationException("Position is not initialized.");
        if (sector is <= 0 or > 65535) throw new InvalidOperationException("Sector id is out of range.");
        float length = MathF.Sqrt(forward.X * forward.X + forward.Z * forward.Z);
        if (!float.IsFinite(length) || length < 0.001f) throw new InvalidOperationException("Forward vector has no ground direction.");
        var ground = new Vector3(forward.X / length, 0, forward.Z / length);
        return Write(json =>
        {
            json.WriteNumber("t", unixMilliseconds);
            json.WriteNumber("sector", sector);
            if (rotationDegrees is int rotation) json.WriteNumber("rotation", rotation); else json.WriteNull("rotation");
            json.WriteNumber("x", position.X + 0f);   // + 0f turns -0 into 0
            json.WriteNumber("y", position.Y + 0f);
            json.WriteNumber("z", position.Z + 0f);
            json.WriteNumber("fx", ground.X + 0f);
            json.WriteNumber("fz", ground.Z + 0f);
            json.WriteNumber("heading", CoordinateRecording.HeadingDegrees(ground) + 0f);
            json.WriteBoolean("ok", true);
        });
    }

    public static string Error(long unixMilliseconds, string error) => Write(json =>
    {
        json.WriteNumber("t", unixMilliseconds);
        json.WriteBoolean("ok", false);
        json.WriteString("error", string.IsNullOrWhiteSpace(error) ? "Unknown telemetry error." : error);
    });

    private static string Write(Action<Utf8JsonWriter> body)
    {
        using var stream = new MemoryStream(256);
        using (var json = new Utf8JsonWriter(stream, Options))
        {
            json.WriteStartObject(); body(json); json.WriteEndObject();
        }
        return Encoding.UTF8.GetString(stream.GetBuffer(), 0, (int)stream.Length);
    }
}
