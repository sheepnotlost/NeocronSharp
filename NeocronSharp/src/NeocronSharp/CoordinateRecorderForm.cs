using System.Diagnostics;
using System.Text.Json;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class CoordinateRecorderForm : Form
{
    private readonly string _directory;
    private readonly TextBox _name = new() { Text = "Map survey", Dock = DockStyle.Fill, MaxLength = 100 };
    private readonly ComboBox _interval = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
    private readonly SkinButton _start = new() { Text = "Start recording", Dock = DockStyle.Fill };
    private readonly SkinButton _stop = new() { Text = "Stop && save", Dock = DockStyle.Fill, Enabled = false };
    private readonly SkinButton _export = new() { Text = "Export copy…", Dock = DockStyle.Fill, Enabled = false };
    private readonly Label _live = new() { Dock = DockStyle.Fill, Font = new("Consolas", 17, FontStyle.Bold), TextAlign = ContentAlignment.MiddleLeft };
    private readonly Label _connection = new() { Dock = DockStyle.Fill, AutoEllipsis = true };
    private readonly Label _recordStatus = new() { Dock = DockStyle.Fill, AutoEllipsis = true };
    private readonly TextBox _files = new() { Dock = DockStyle.Fill, ReadOnly = true };
    private readonly BufferedGrid _points = new() { Dock = DockStyle.Fill, VirtualMode = true, ReadOnly = true, AllowUserToAddRows = false,
        AllowUserToDeleteRows = false, RowHeadersVisible = false, EnableHeadersVisualStyles = false, RowTemplate = { Height = 28 } };
    private readonly CheckBox _scroll = new() { Text = "Follow newest samples", Checked = true, AutoSize = true };
    private readonly SectorMapPanel _map = new() { Dock = DockStyle.Fill, Margin = new Padding(8) };
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 100 };
    private PlayerReader? _reader;
    private CoordinateFix? _latest;
    private CoordinateRecording? _recording;
    private CoordinateLogWriter? _writer;
    private SectorMapAssets? _assets;
    private bool _closing;
    private Task? _poll;
    private long _retryAfter, _lastDisplay;

    internal CoordinateRecorderForm(string? directory = null)
    {
        _directory = directory ?? Path.Combine(ProjectPaths.Root, "recordings");
        Text = "NeocronSharp — Coordinate recorder"; ClientSize = new(1260, 820); MinimumSize = new(1000, 670);
        Font = new("Segoe UI", 10); StartPosition = FormStartPosition.CenterScreen; DoubleBuffered = true;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(20), ColumnCount = 1, RowCount = 9 };
        foreach (int height in new[] { 44, 46, 50, 30, 42, 32, 34 }) layout.RowStyles.Add(new(SizeType.Absolute, height));
        layout.RowStyles.Add(new(SizeType.Percent, 100)); layout.RowStyles.Add(new(SizeType.Absolute, 70));
        layout.Controls.Add(new Label { Text = "Continuous coordinate recorder", Dock = DockStyle.Fill, Font = new("Segoe UI", 20, FontStyle.Bold) }, 0, 0);
        layout.Controls.Add(new Label { Text = "Click Start recording, then walk normally. Every valid sample is saved automatically—no stopping or marking points.\nX / Z are ground coordinates; Y is height. Recording continues while the game is focused.", Dock = DockStyle.Fill }, 0, 1);
        layout.Controls.Add(_live, 0, 2); layout.Controls.Add(_connection, 0, 3);
        var tools = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 7, RowCount = 1 };
        tools.ColumnStyles.Add(new(SizeType.Percent, 100)); foreach (int width in new[] { 160, 155, 130, 130, 125, 155 }) tools.ColumnStyles.Add(new(SizeType.Absolute, width));
        tools.RowStyles.Add(new(SizeType.Percent, 100));
        _interval.Items.AddRange(new object[] { "100 ms (10/s)", "250 ms (4/s)", "500 ms (2/s)", "1000 ms (1/s)" }); _interval.SelectedIndex = 0;
        tools.Controls.Add(_name, 0, 0); tools.Controls.Add(_interval, 1, 0); tools.Controls.Add(_start, 2, 0); tools.Controls.Add(_stop, 3, 0); tools.Controls.Add(_export, 4, 0);
        var folder = new SkinButton { Text = "Open folder", Dock = DockStyle.Fill };
        folder.Click += (_, _) => { try { Directory.CreateDirectory(_directory); Process.Start(new ProcessStartInfo(_directory) { UseShellExecute = true }); } catch (Exception e) { MessageBox.Show(this, e.Message); } };
        tools.Controls.Add(folder, 5, 0); tools.Controls.Add(_scroll, 6, 0); layout.Controls.Add(tools, 0, 4);
        layout.Controls.Add(_recordStatus, 0, 5); layout.Controls.Add(_files, 0, 6);
        var split = new SplitContainer { Size = new(1200, 440), Dock = DockStyle.Fill, SplitterDistance = 610, Panel1MinSize = 430, Panel2MinSize = 300 };
        foreach (var column in new[] { ("Sample",70), ("Elapsed s",90), ("X",100), ("Y · height",100), ("Z",100), ("Sector",75), ("Segment",80) })
            _points.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = column.Item1, Width = column.Item2, SortMode = DataGridViewColumnSortMode.NotSortable });
        _points.CellValueNeeded += (_, e) =>
        {
            if (_recording == null || e.RowIndex >= _recording.Points.Count) return;
            var p = _recording.Points[e.RowIndex];
            e.Value = e.ColumnIndex switch { 0 => p.Sequence, 1 => (p.ElapsedMilliseconds / 1000d).ToString("N2"), 2 => p.X.ToString("N3"),
                3 => p.Y.ToString("N3"), 4 => p.Z.ToString("N3"), 5 => p.SectorId, 6 => p.Segment, _ => null };
        };
        split.Panel1.Controls.Add(_points);
        var mapSide = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, ColumnCount = 1 };
        mapSide.RowStyles.Add(new(SizeType.Absolute, 38)); mapSide.RowStyles.Add(new(SizeType.Percent, 100));
        var mapTools = new FlowLayoutPanel { Dock = DockStyle.Fill };
        var fit = new SkinButton { Text = "Fit map", Width = 90, Height = 30 }; fit.Click += (_, _) => _map.Fit();
        var center = new SkinButton { Text = "You", Width = 65, Height = 30 }; center.Click += (_, _) => _map.CenterPlayer();
        var heightFilter = new CheckBox { Text = "This height ±48", AutoSize = true, Margin = new Padding(8,7,0,0) };
        heightFilter.CheckedChanged += (_, _) => { _map.NearHeight = heightFilter.Checked; _map.Invalidate(); };
        mapTools.Controls.AddRange(new Control[] { fit, center, heightFilter }); mapSide.Controls.Add(mapTools, 0, 0); mapSide.Controls.Add(_map, 0, 1);
        split.Panel2.Controls.Add(mapSide); layout.Controls.Add(split, 0, 7);
        layout.Controls.Add(new Label { Dock = DockStyle.Fill, Text = "CSV is appended live; JSON is saved when you stop or close this window. Sector changes and missing telemetry start new segments.\nThe trail shows where you travelled; it does not establish walls or walkability in unvisited areas. Heading: 0° = −Z, 90° = +X.\nWalk all floors, stairs, doorways and alternate paths for useful coverage. Sampling is best effort, not a guaranteed frame rate." }, 0, 8);
        Controls.Add(layout); _live.Text = "X —     Y —     Z —"; _connection.Text = "Connecting to the supported Neocron client…";
        _recordStatus.Text = "Ready. Start recording when your character is in-world."; _files.Text = _directory;
        _start.Click += (_, _) => StartRecording(); _stop.Click += (_, _) => StopRecording(); _export.Click += (_, _) => ExportCopy();
        _interval.SelectedIndexChanged += (_, _) => _timer.Interval = SelectedInterval;
        _timer.Tick += async (_, _) =>
        {
            if (_closing || _poll is { IsCompleted: false } || (_reader == null && Environment.TickCount64 < _retryAfter)) return;
            _poll = Poll(); await _poll;
        };
        Shown += (_, _) => _timer.Start();
        FormClosing += async (_, e) =>
        {
            if (_closing) return; _closing = true; _timer.Stop();
            if (_poll is { IsCompleted: false }) { e.Cancel = true; await _poll; StopRecording(); Close(); }
            else StopRecording();
        };
        FormClosed += (_, _) => { _writer?.Dispose(); _reader?.Dispose(); _assets?.Dispose(); _timer.Dispose(); };
        AppTheme.Bind(this);
    }
    private int SelectedInterval => new[] { 100, 250, 500, 1000 }[Math.Max(0, _interval.SelectedIndex)];
    private string SectorName(int sector) => _assets?.Catalog.Name(sector) ?? $"Sector {sector}";
    private async Task Poll()
    {
        CoordinateFix fix;
        try
        {
            fix = await Task.Run(() => { _reader ??= new PlayerReader(ProjectPaths.Client); return _reader.ReadCoordinates(); });
        }
        catch (Exception error)
        {
            _reader?.Dispose(); _reader = null; _retryAfter = Environment.TickCount64 + 1000;
            if (_closing) return;
            _latest = null; _live.Text = "X —     Y —     Z —";
            _connection.Text = "Waiting for fresh coordinates: " + error.Message;
            _recording?.MarkGap(DateTimeOffset.UtcNow, error.Message);
            if (_recording?.IsRecording == true) _recordStatus.Text = $"Recording paused for telemetry · {_recording.Points.Count:N0} saved samples. It resumes automatically.";
            _map.SetData(null, Array.Empty<NearbyEntity>(), null, null, "Waiting for live position; no stale location is shown."); return;
        }
        if (_closing) return; _latest = fix;
        if (_assets == null) { try { _assets = new SectorMapAssets(Path.GetDirectoryName(ProjectPaths.Client)!); } catch { } }
        _live.Text = $"X {fix.Position.X,11:N3}   Y {fix.Position.Y,11:N3}   Z {fix.Position.Z,11:N3}";
        _connection.Text = $"Live · {SectorName(fix.SectorId)} · sector {fix.SectorId} · {fix.CapturedAt.LocalDateTime:HH:mm:ss.fff} · read-only";
        if (_recording?.IsRecording == true && _writer != null)
        {
            try
            {
                var point = _recording.Append(fix, SectorName(fix.SectorId)); _writer.Append(point);
                _recordStatus.Text = $"RECORDING · {point.Sequence:N0} samples · {point.ElapsedMilliseconds / 1000d:N1} s · segment {point.Segment} · {_recording.DistanceWorldUnits:N1} travelled world units";
                if (_recording.Points.Count == CoordinateRecording.MaxSamples) StopRecording("Sample limit reached; start a new recording to continue.");
            }
            catch (Exception error) { StopRecording("Recording stopped: " + error.Message); }
        }
        if (Environment.TickCount64 - _lastDisplay >= 250)
        {
            _lastDisplay = Environment.TickCount64; _points.RowCount = _recording?.Points.Count ?? 0;
            if (_scroll.Checked && _points.RowCount > 0) _points.FirstDisplayedScrollingRowIndex = _points.RowCount - 1;
            UpdateMap(fix);
        }
    }
    private void UpdateMap(CoordinateFix fix)
    {
        SectorMapDefinition? definition = _assets?.Catalog.Find(fix.SectorId); Bitmap? image = null;
        string message = "This sector has no available native map. Coordinate recording continues.";
        if (fix.MapRotationDegrees == null) message = "Waiting for native map orientation. Coordinate recording continues.";
        try { if (definition != null) image = _assets!.Image(definition); } catch (Exception error) { message = error.Message; }
        var snapshot = new EntitySnapshot(fix.CapturedAt, fix.World, 0, fix.Position, fix.Forward, Array.Empty<WorldEntity>(), 0, new(fix.SectorId, fix.MapRotationDegrees));
        _map.Trail = _recording?.Points; _map.SetData(snapshot, Array.Empty<NearbyEntity>(), definition, image, message);
    }
    private void StartRecording()
    {
        if (_recording?.IsRecording == true) return;
        if (_latest == null || Environment.TickCount64 - _latest.MonotonicMilliseconds > 2000)
        { _recordStatus.Text = "Wait for live coordinates before starting. Log in and finish zoning."; return; }
        CoordinateLogWriter? writer = null;
        try
        {
            var recording = new CoordinateRecording(_name.Text, SelectedInterval, DateTimeOffset.UtcNow, Environment.TickCount64);
            writer = new(_directory, recording); _recording = recording; _writer = writer;
            _points.RowCount = 0; _map.Trail = recording.Points; _map.Invalidate();
            _files.Text = writer.CsvPath; _recordStatus.Text = "RECORDING · saving continuously. Walk normally.";
            _start.Enabled = _name.Enabled = _interval.Enabled = _export.Enabled = false; _stop.Enabled = true;
        }
        catch (Exception error) { writer?.Dispose(); _recordStatus.Text = "Could not start recording: " + error.Message; }
    }
    private void StopRecording(string? message = null)
    {
        if (_recording?.IsRecording != true) return;
        _recording.Stop(DateTimeOffset.UtcNow);
        try
        {
            _writer!.Complete(_recording); _export.Enabled = true;
            _recordStatus.Text = message ?? $"Saved {_recording.Points.Count:N0} samples to CSV and JSON · {_recording.Gaps.Count} telemetry gaps.";
        }
        catch (Exception error) { _recordStatus.Text = "JSON save failed; keep the CSV recording: " + error.Message; }
        finally { _writer?.Dispose(); _start.Enabled = _name.Enabled = _interval.Enabled = true; _stop.Enabled = false; _points.RowCount = _recording.Points.Count; }
    }
    private void ExportCopy()
    {
        if (_writer == null || _recording?.IsRecording != false) return;
        using var dialog = new SaveFileDialog { Filter = "CSV coordinates (*.csv)|*.csv|JSON recording (*.json)|*.json", FileName = Path.GetFileNameWithoutExtension(_writer.CsvPath), AddExtension = true };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            string source = dialog.FilterIndex == 2 ? _writer.JsonPath : _writer.CsvPath;
            if (!Path.GetFullPath(source).Equals(Path.GetFullPath(dialog.FileName), StringComparison.OrdinalIgnoreCase)) File.Copy(source, dialog.FileName, true);
        }
        catch (Exception error) { MessageBox.Show(this, error.Message, "Export failed"); }
    }
    internal async Task VerifyEvidence()
    {
        if (_latest == null) throw new InvalidOperationException("Recorder live check requires an in-world character.");
        _name.Text = "Live recorder check"; StartRecording(); await Task.Delay(1300); StopRecording();
        if (_recording == null || _recording.Points.Count < 5 || _writer == null || !File.Exists(_writer.JsonPath) || File.ReadAllLines(_writer.CsvPath).Length != _recording.Points.Count + 1)
            throw new InvalidOperationException("Live coordinate capture or auto-save failed.");
        using var json = JsonDocument.Parse(File.ReadAllText(_writer.JsonPath));
        if (json.RootElement.GetProperty("Points").GetArrayLength() != _recording.Points.Count) throw new InvalidOperationException("JSON lost coordinate samples.");
        using var bitmap = new Bitmap(Width, Height); DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
        bitmap.Save(Path.Combine(ProjectPaths.Root, "logs", "coordinate-recorder-ui.png"));
        File.WriteAllText(Path.Combine(ProjectPaths.Root, "logs", "coordinate-recorder-check.json"), JsonSerializer.Serialize(new { status = "passed",
            samples = _recording.Points.Count, csv = _writer.CsvPath, json = _writer.JsonPath, sector = _latest.SectorId, interval = SelectedInterval, movementInputSent = false }));
    }
    internal async Task BeginCloseEvidence()
    {
        _name.Text = "Close autosave check"; StartRecording(); await Task.Delay(400);
        if (_recording?.IsRecording != true || _recording.Points.Count == 0) throw new InvalidOperationException("Close test did not start capturing.");
    }
    internal void VerifyClosedEvidence()
    {
        if (_recording?.IsRecording != false || _writer == null || !File.Exists(_writer.JsonPath))
            throw new InvalidOperationException("Closing an active recorder did not save JSON.");
        using var json = JsonDocument.Parse(File.ReadAllText(_writer.JsonPath));
        if (json.RootElement.GetProperty("Points").GetArrayLength() != _recording.Points.Count)
            throw new InvalidOperationException("Close autosave lost samples.");
        File.WriteAllText(Path.Combine(ProjectPaths.Root, "logs", "coordinate-recorder-close-check.json"),
            JsonSerializer.Serialize(new { status = "passed", samples = _recording.Points.Count, json = _writer.JsonPath, cleanCloseAutosaved = true }));
    }
}
