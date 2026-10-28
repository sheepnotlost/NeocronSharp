using System.Runtime.InteropServices;
using System.Text.Json;
using System.Drawing.Drawing2D;
using NeocronSharp.Core;

namespace GameStatusOverlay;

/// <summary>Click-through desktop overlay; no injection and no game input.</summary>
public sealed class StatusPlugin : INeocronPlugin
{
    private IPluginContext? _context;
    private IGameTelemetryContext? _game;
    private StatusPanel? _panel;
    private System.Windows.Forms.Timer? _timer;
    private int _offsetX = 62, _offsetY = 270;
    private bool _failed;

    public void Start(IPluginContext context)
    {
        _context = context;
        _game = context as IGameTelemetryContext ?? throw new InvalidOperationException("This host does not provide game telemetry.");
        var settings = context.ReadSettings();
        _offsetX = ReadInt(settings, "offsetX", 62, 0, 4000);
        _offsetY = ReadInt(settings, "offsetY", 270, 0, 2000);
        double opacity = settings.TryGetProperty("opacity", out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double parsed) && double.IsFinite(parsed)
            ? Math.Clamp(parsed, 0.35, 1.0) : 0.88;
        _panel = new StatusPanel { Opacity = opacity };
        _timer = new System.Windows.Forms.Timer { Interval = 250 };
        _timer.Tick += Tick; _timer.Start();
        context.Log("NPC counter started. It displays only while Neocron is focused.");
    }

    private static int ReadInt(JsonElement settings, string key, int fallback, int min, int max) =>
        settings.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out int result) ? Math.Clamp(result, min, max) : fallback;

    private void Tick(object? sender, EventArgs e)
    {
        try
        {
            var data = _game?.ReadGameTelemetry();
            if (data == null || DateTimeOffset.UtcNow - data.CapturedAt > TimeSpan.FromSeconds(2) ||
                data.GameWindow == 0 || !Native.IsWindow(data.GameWindow) || Native.IsIconic(data.GameWindow) ||
                Native.GetForegroundWindow() != data.GameWindow || !Native.GetClientRect(data.GameWindow, out var client))
            { _panel?.HideOverlay(); return; }
            var origin = new Native.Point();
            if (!Native.ClientToScreen(data.GameWindow, ref origin)) { _panel?.HideOverlay(); return; }
            var panel = _panel!;
            panel.Location = new System.Drawing.Point(origin.X + Math.Min(_offsetX, Math.Max(0, client.Right - client.Left - panel.Width)),
                origin.Y + Math.Min(_offsetY, Math.Max(0, client.Bottom - client.Top - panel.Height)));
            panel.UpdateData(data);
            panel.ShowOverlay();
            _failed = false;
        }
        catch (Exception error)
        {
            _panel?.HideOverlay();
            if (!_failed) _context?.Log("Overlay update failed: " + error.Message);
            _failed = true;
        }
    }

    public void Stop()
    {
        if (_timer != null) { _timer.Stop(); _timer.Tick -= Tick; _timer.Dispose(); _timer = null; }
        _panel?.Close(); _panel?.Dispose(); _panel = null;
        _context?.Log("NPC counter stopped."); _context = null; _game = null;
    }
}

internal sealed class StatusPanel : Form
{
    private readonly Label _entities;
    protected override bool ShowWithoutActivation => true;
    protected override CreateParams CreateParams
    {
        get
        {
            var value = base.CreateParams;
            value.ExStyle |= 0x00000020 | 0x00000080 | 0x08000000; // click-through, tool window, no activation
            return value;
        }
    }
    public StatusPanel()
    {
        Name = "NeocronStatusOverlay"; Text = "Neocron status overlay";
        FormBorderStyle = FormBorderStyle.None; ShowInTaskbar = false; TopMost = true;
        StartPosition = FormStartPosition.Manual; ClientSize = new Size(166, 34);
        BackColor = Color.FromArgb(18, 65, 43); ForeColor = Color.FromArgb(106, 242, 167);
        DoubleBuffered = true;
        using (var outline = Outline()) Region = new Region(outline);
        _entities = new Label { Location = new Point(10, 5), Size = new Size(146, 23), TextAlign = ContentAlignment.MiddleCenter,
            BackColor = Color.Transparent, Font = new Font("Segoe UI", 10, FontStyle.Bold) };
        Controls.Add(_entities);
    }
    private static GraphicsPath Outline()
    {
        var path = new GraphicsPath();
        path.AddPolygon(new[] { new Point(0, 7), new Point(7, 0), new Point(151, 0), new Point(165, 9),
            new Point(165, 26), new Point(158, 33), new Point(12, 33), new Point(0, 23) });
        return path;
    }
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        using var border = new Pen(Color.FromArgb(75, 220, 142), 2);
        using var inner = new Pen(Color.FromArgb(29, 142, 84), 1);
        using var path = Outline();
        e.Graphics.DrawPath(border, path);
        e.Graphics.DrawLine(inner, 9, 4, 148, 4);
        e.Graphics.DrawLine(inner, 16, 29, 156, 29);
    }
    internal void UpdateData(PluginTelemetry data)
    {
        _entities.Text = $"NPCs: {data.NearbyNpcCount:N0}";
    }
    internal void ShowOverlay()
    {
        // Show directly with SW_SHOWNOACTIVATE. Form.Show can activate a window
        // even when the no-activate extended style is set.
        EnsureHandles(this);
        if (!Native.IsWindowVisible(Handle)) Native.ShowWindow(Handle, 4);
    }
    private static void EnsureHandles(Control parent)
    {
        _ = parent.Handle;
        foreach (Control child in parent.Controls) EnsureHandles(child);
    }
    internal void HideOverlay()
    {
        if (IsHandleCreated && Native.IsWindowVisible(Handle)) Native.ShowWindow(Handle, 0);
    }
}

internal static class Native
{
    [StructLayout(LayoutKind.Sequential)] internal struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] internal struct Point { public int X, Y; }
    [DllImport("user32.dll")] internal static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool IsWindow(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool IsIconic(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool GetClientRect(nint window, out Rect rect);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool ClientToScreen(nint window, ref Point point);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool ShowWindow(nint window, int command);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool IsWindowVisible(nint window);
}
