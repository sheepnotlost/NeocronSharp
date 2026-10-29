using System.Drawing;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class MainForm : Form
{
    private readonly Label _status;
    private readonly Button _start, _read, _stop, _save, _go;
    private readonly Label _savedLabel;
    private SavedSpot? _saved;
    private CancellationTokenSource? _cancel;
    private Task? _running;

    public MainForm()
    {
        Text = "NeocronSharp — Character navigation";
        ClientSize = new Size(680, 410);
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        Font = new Font("Segoe UI", 10);
        var title = new Label { Text = "Walk to a saved spot", Location = new Point(24, 20), Size = new Size(620, 36), Font = new Font("Segoe UI", 18, FontStyle.Bold) };
        var help = new Label { Text = "Save a destination, then walk elsewhere with a clear path back.\nIn Neocron, press Tab if needed so the mouse cursor disappears; close chat.\nStart here, focus Neocron in five seconds, and leave the mouse still. F8 stops.", Location = new Point(24, 65), Size = new Size(635, 80) };
        _save = new SkinButton { Text = "&Save this spot", Location = new Point(24, 155), Size = new Size(170, 38), TabIndex = 0 };
        _go = new SkinButton { Text = "&Walk to saved spot", Location = new Point(210, 155), Size = new Size(210, 38), TabIndex = 1, Enabled = false };
        _stop = new SkinButton { Text = "S&top", Location = new Point(436, 155), Size = new Size(100, 38), Enabled = false, TabIndex = 2 };
        _savedLabel = new Label { Text = "No destination saved yet. Stay in the same area after saving.", Location = new Point(24, 205), Size = new Size(630, 40) };
        _read = new SkinButton { Text = "Read &position", Location = new Point(24, 250), Size = new Size(150, 38), TabIndex = 3 };
        _start = new SkinButton { Text = "Test &out/back twice", Location = new Point(190, 250), Size = new Size(230, 38), TabIndex = 4 };
        _status = new Label { Text = "Use default W/S controls and mouse-look. This version does not go around walls.", Location = new Point(24, 310), Size = new Size(630, 80) };
        Controls.AddRange(new Control[] { title, help, _save, _go, _savedLabel, _read, _start, _stop, _status });
        AppTheme.Bind(this);
        _read.Click += (_, _) => ReadPosition();
        _save.Click += (_, _) => SaveSpot();
        _go.Click += async (_, _) => { _running = RunAsync(navigate: true); await _running; };
        _start.Click += async (_, _) => { _running = RunAsync(); await _running; };
        _stop.Click += (_, _) => _cancel?.Cancel();
        FormClosing += async (_, eventArgs) =>
        {
            if (_running is { IsCompleted: false })
            {
                eventArgs.Cancel = true;
                _cancel?.Cancel();
                await _running;
                Close();
            }
        };
    }

    private void SaveSpot()
    {
        try
        {
            using var reader = new PlayerReader(ProjectPaths.Client);
            var sample = reader.ReadSample();
            _saved = new SavedSpot(sample.Position, sample.Player, sample.World, sample.Physics);
            _savedLabel.Text = "Destination saved. Walk elsewhere nearby, then choose Walk to saved spot.";
            _go.Enabled = true;
            Status("Saved your current spot. No movement sent.");
        }
        catch (Exception error) { Status(error.Message); }
    }

    private void Status(string text)
    {
        if (IsDisposed || Disposing) return;
        if (InvokeRequired) { BeginInvoke(new Action(() => Status(text))); return; }
        _status.Text = text;
        _status.ForeColor = text.StartsWith("Stopped:", StringComparison.Ordinal) ? Color.Firebrick : SystemColors.ControlText;
    }

    private void ReadPosition()
    {
        try
        {
            using var reader = new PlayerReader(ProjectPaths.Client);
            var sample = reader.ReadSample();
            Status($"Connected to {PlayerReader.BuildLabel}. X {sample.Position.X:F3}, Y {sample.Position.Y:F3}, Z {sample.Position.Z:F3}. No movement sent.");
        }
        catch (Exception error) { Status(error.Message); }
    }

    private async Task RunAsync(bool navigate = false)
    {
        _cancel = new CancellationTokenSource();
        _start.Enabled = _read.Enabled = _save.Enabled = _go.Enabled = false;
        _stop.Enabled = true;
        try
        {
            using var reader = new PlayerReader(ProjectPaths.Client);
            if (navigate)
            {
                var target = _saved ?? throw new InvalidOperationException("Save a destination first.");
                var sample = reader.ReadSample();
                if (sample.Player != target.Player || sample.World != target.World || sample.Physics != target.Physics)
                    throw new InvalidOperationException("Your game session changed. Save the destination again before starting.");
                PointNavigation.ValidateDestination(sample.Position, target.Position);
                if (PointNavigation.Distance(sample.Position, target.Position) <= PointNavigation.ArrivalTolerance)
                {
                    Status("You are already at the saved spot. Walk somewhere else first, then use Walk to saved spot.");
                    return;
                }
            }
            string directory = Path.Combine(ProjectPaths.Root, "logs");
            Directory.CreateDirectory(directory);
            string logPath = Path.Combine(directory, $"{(navigate ? "navigation" : "movement")}-{DateTime.UtcNow:yyyyMMdd-HHmmss-fff}.jsonl");
            for (int seconds = 5; seconds > 0; seconds--)
            {
                Status($"Focus Neocron now. Starting in {seconds} seconds… F8 stops.");
                if ((Native.GetAsyncKeyState(0x77) & 0x8000) != 0) _cancel.Cancel();
                await Task.Delay(1000, _cancel.Token);
            }
            if (navigate)
            {
                var saved = _saved ?? throw new InvalidOperationException("Save a destination first.");
                await Task.Run(() => new PointNavigationSession(reader, Status).RunAsync(saved, logPath, _cancel.Token));
            }
            else await Task.Run(() => new MovementSession(reader, Status).RunAsync(logPath, _cancel.Token));
        }
        catch (OperationCanceledException) { Status("Stopped. Movement keys released."); }
        catch (Exception error)
        {
            Status($"Stopped: {error.Message}");
            WindowState = FormWindowState.Normal;
            Activate();
        }
        finally
        {
            _cancel.Dispose(); _cancel = null;
            _start.Enabled = _read.Enabled = _save.Enabled = true;
            _go.Enabled = _saved != null;
            _stop.Enabled = false;
        }
    }
}
