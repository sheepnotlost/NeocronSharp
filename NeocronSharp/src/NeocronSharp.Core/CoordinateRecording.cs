using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;

namespace NeocronSharp.Core;

public sealed record CoordinateFix(DateTimeOffset CapturedAt, long MonotonicMilliseconds, int ProcessId, ulong World, ulong Physics,
    int SectorId, int? MapRotationDegrees, Vector3 Position, Vector3 Forward);
public sealed record CoordinatePoint(int Sequence, DateTimeOffset TimeUtc, long ElapsedMilliseconds, int Segment, int SectorId, string SectorName,
    float X, float Y, float Z, float ForwardX, float ForwardY, float ForwardZ, float HeadingDegrees, string BreakReason);
public sealed record CoordinateGap(DateTimeOffset TimeUtc, string Reason);
public sealed record CoordinateSession(int FormatVersion, string Name, int RequestedIntervalMilliseconds, DateTimeOffset StartedAtUtc,
    DateTimeOffset? StoppedAtUtc, double DistanceWorldUnits, IReadOnlyList<CoordinatePoint> Points, IReadOnlyList<CoordinateGap> Gaps);

public sealed class CoordinateRecording
{
    public const int MaxSamples = 100000;
    private readonly List<CoordinatePoint> _points = new();
    private readonly List<CoordinateGap> _gaps = new();
    private readonly long _startedTick;
    private CoordinateFix? _previous;
    private string? _pendingBreak;
    public string Name { get; }
    public int IntervalMilliseconds { get; }
    public DateTimeOffset StartedAtUtc { get; }
    public DateTimeOffset? StoppedAtUtc { get; private set; }
    public bool IsRecording => !StoppedAtUtc.HasValue;
    public double DistanceWorldUnits { get; private set; }
    public IReadOnlyList<CoordinatePoint> Points => _points;
    public IReadOnlyList<CoordinateGap> Gaps => _gaps;
    public CoordinateRecording(string name, int intervalMilliseconds, DateTimeOffset startedAt, long startedTick)
    {
        if (intervalMilliseconds is not (100 or 250 or 500 or 1000)) throw new ArgumentOutOfRangeException(nameof(intervalMilliseconds));
        Name = name.Trim().Length == 0 ? "Walk" : name.Trim(); IntervalMilliseconds = intervalMilliseconds;
        StartedAtUtc = startedAt.ToUniversalTime(); _startedTick = startedTick;
    }
    public CoordinatePoint Append(CoordinateFix fix, string sectorName)
    {
        if (!IsRecording) throw new InvalidOperationException("Recording is stopped.");
        if (_points.Count >= MaxSamples) throw new InvalidOperationException("100,000-sample limit reached. Start a new recording to continue.");
        static bool Finite(Vector3 p) => float.IsFinite(p.X) && float.IsFinite(p.Y) && float.IsFinite(p.Z);
        if (fix.SectorId is <= 0 or > 65535 || !Finite(fix.Position) || !Finite(fix.Forward) ||
            Math.Abs(fix.Position.X) > 1_000_000 || Math.Abs(fix.Position.Y) > 1_000_000 || Math.Abs(fix.Position.Z) > 1_000_000 ||
            fix.Forward.X * fix.Forward.X + fix.Forward.Z * fix.Forward.Z < .000001f)
            throw new InvalidOperationException("Invalid coordinate sample.");
        if (fix.MonotonicMilliseconds < _startedTick || (_previous != null && fix.MonotonicMilliseconds < _previous.MonotonicMilliseconds))
            throw new InvalidOperationException("Coordinate clock moved backwards.");
        string reason = _points.Count == 0 ? "Start" : _pendingBreak ?? "";
        if (_previous is { } last)
        {
            if (last.ProcessId != fix.ProcessId || last.World != fix.World || last.Physics != fix.Physics) reason = "Client session changed";
            else if (last.SectorId != fix.SectorId) reason = "Sector changed";
            else if (fix.MonotonicMilliseconds - last.MonotonicMilliseconds > 2000) reason = "Sampling gap";
            else if (Vector3.Distance(last.Position, fix.Position) > 1000) reason = "Position discontinuity";
            if (reason.Length == 0) DistanceWorldUnits += Vector3.Distance(last.Position, fix.Position);
        }
        int segment = _points.Count == 0 ? 1 : _points[^1].Segment + (reason.Length > 0 ? 1 : 0);
        float heading = (MathF.Atan2(fix.Forward.X, -fix.Forward.Z) * 180 / MathF.PI + 360) % 360;
        var point = new CoordinatePoint(_points.Count + 1, fix.CapturedAt.ToUniversalTime(), fix.MonotonicMilliseconds - _startedTick,
            segment, fix.SectorId, sectorName, fix.Position.X, fix.Position.Y, fix.Position.Z,
            fix.Forward.X, fix.Forward.Y, fix.Forward.Z, heading, reason);
        _points.Add(point); _previous = fix; _pendingBreak = null; return point;
    }
    public void MarkGap(DateTimeOffset at, string reason)
    {
        if (!IsRecording || _pendingBreak != null) return;
        _pendingBreak = "Telemetry gap"; _gaps.Add(new(at.ToUniversalTime(), reason));
    }
    public void Stop(DateTimeOffset at) { StoppedAtUtc ??= at.ToUniversalTime(); }
    public CoordinateSession Snapshot() => new(1, Name, IntervalMilliseconds, StartedAtUtc, StoppedAtUtc, DistanceWorldUnits, _points, _gaps);
}

public sealed class CoordinateLogWriter : IDisposable
{
    private StreamWriter? _csv;
    public string CsvPath { get; }
    public string JsonPath { get; }
    public CoordinateLogWriter(string directory, CoordinateRecording recording)
    {
        Directory.CreateDirectory(directory);
        string name = new(recording.Name.Where(c => char.IsLetterOrDigit(c) || c is '-' or '_').Take(40).ToArray());
        if (name.Length == 0) name = "Walk";
        string stem = $"{recording.StartedAtUtc:yyyyMMdd-HHmmss-fff}-{name}-{Guid.NewGuid():N}";
        CsvPath = Path.Combine(Path.GetFullPath(directory), stem + ".csv"); JsonPath = Path.ChangeExtension(CsvPath, ".json");
        _csv = new StreamWriter(new FileStream(CsvPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false)) { AutoFlush = true };
        _csv.WriteLine("sequence,time_utc,elapsed_ms,segment,sector_id,sector_name,x,y,z,forward_x,forward_y,forward_z,heading_degrees,break_reason");
    }
    public void Append(CoordinatePoint point)
    {
        if (_csv == null) throw new InvalidOperationException("Coordinate file is closed.");
        static string Text(string value) => '"' + value.Replace("\"", "\"\"") + '"';
        static string Float(float value) => value.ToString("R", CultureInfo.InvariantCulture);
        _csv.WriteLine(string.Join(',', point.Sequence.ToString(CultureInfo.InvariantCulture), point.TimeUtc.ToString("O", CultureInfo.InvariantCulture),
            point.ElapsedMilliseconds.ToString(CultureInfo.InvariantCulture), point.Segment.ToString(CultureInfo.InvariantCulture),
            point.SectorId.ToString(CultureInfo.InvariantCulture), Text(point.SectorName), Float(point.X), Float(point.Y), Float(point.Z),
            Float(point.ForwardX), Float(point.ForwardY), Float(point.ForwardZ), Float(point.HeadingDegrees), Text(point.BreakReason)));
    }
    public void Complete(CoordinateRecording recording)
    {
        if (recording.IsRecording) throw new InvalidOperationException("Stop recording before finalizing JSON.");
        Dispose();
        string temporary = JsonPath + ".tmp";
        using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            JsonSerializer.Serialize(file, recording.Snapshot(), new JsonSerializerOptions { WriteIndented = true });
        File.Move(temporary, JsonPath);
    }
    public void Dispose() { _csv?.Dispose(); _csv = null; }
}
