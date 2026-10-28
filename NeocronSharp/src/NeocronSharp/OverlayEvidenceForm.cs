using NeocronSharp.Core;
using System.Runtime.InteropServices;

namespace NeocronSharp;

/// <summary>Desktop smoke check with a synthetic target window; never sends game input.</summary>
internal sealed class OverlayEvidenceForm : Form
{
    private PluginHost? _host;
    private bool _stale;
    public bool Passed { get; private set; }
    public OverlayEvidenceForm()
    {
        Text = "NeocronSharp overlay test target"; ClientSize = new Size(700, 420);
        StartPosition = FormStartPosition.CenterScreen;
        Controls.Add(new Label { Text = "Checking overlay on a test window…", AutoSize = true, Location = new Point(20, 25) });
        Shown += RunCheck;
    }
    private async void RunCheck(object? sender, EventArgs e)
    {
        try
        {
            string root = Path.Combine(ProjectPaths.Root, "logs", "overlay-evidence-work");
            string target = Path.Combine(root, "plugins", "overlay"); Directory.CreateDirectory(target);
            string fixture = Path.Combine(ProjectPaths.Root, "plugins", "neocronsharp.game-status");
            foreach (string file in new[] { "plugin.json", "GameStatusOverlay.dll" }) File.Copy(Path.Combine(fixture, file), Path.Combine(target, file), true);
            _host = new PluginHost(root, () => new PluginTelemetry(DateTimeOffset.UtcNow - (_stale ? TimeSpan.FromSeconds(5) : TimeSpan.Zero), 123, 45, 678, 7, 1, Handle));
            _host.Discover(); var entry = _host.Entries.Single(e => e.Manifest?.Id == "neocronsharp.game-status");
            _host.Enable(entry);
            if (!entry.Running) throw new InvalidOperationException(entry.Error);
            Activate(); await Task.Delay(900);
            nint panelHandle = FindOwnOverlay();
            var panel = Control.FromHandle(panelHandle) as Form;
            if (panel == null || !IsWindowVisible(panelHandle)) throw new InvalidOperationException($"Overlay did not appear: panel=0x{panelHandle:x}, control={panel != null}, visible={IsWindowVisible(panelHandle)}, foreground=0x{GetForegroundWindow():x}, target=0x{Handle:x}; { _host.ReadRecentLog(entry) }");
            long styles = GetWindowLongPtr(panel.Handle, -20).ToInt64();
            if ((styles & 0x00000020) == 0 || (styles & 0x08000000) == 0 || GetForegroundWindow() == panel.Handle)
                throw new InvalidOperationException($"Overlay does not preserve click-through and game focus: styles=0x{styles:x}, foreground=0x{GetForegroundWindow():x}, target=0x{Handle:x}, panel=0x{panel.Handle:x}.");
            var origin = new NativePoint();
            if (!ClientToScreen(Handle, ref origin) || !GetWindowRect(panelHandle, out var bounds) || bounds.Left - origin.X != 62 || bounds.Top - origin.Y != 270)
                throw new InvalidOperationException("NPC count is not positioned at the requested top-left offset.");
            var labels = Descendants(panel).OfType<Label>().Select(l => l.Text).ToArray();
            if (labels.Length != 1 || labels[0] != "NPCs: 7")
                throw new InvalidOperationException("Overlay displayed incorrect synthetic telemetry.");
            using (var bitmap = new Bitmap(panel.Width, panel.Height))
            using (var graphics = Graphics.FromImage(bitmap))
            {
                nint dc = graphics.GetHdc();
                try { if (!PrintWindow(panelHandle, dc, 2)) throw new InvalidOperationException("Could not capture the overlay window."); }
                finally { graphics.ReleaseHdc(dc); }
                bitmap.Save(Path.Combine(ProjectPaths.Root, "logs", "overlay-ui.png"));
            }
            _stale = true; await Task.Delay(700);
            if (IsWindowVisible(panelHandle)) throw new InvalidOperationException("Overlay did not hide when telemetry became stale.");
            _host.Disable(entry);
            if (IsWindow(panelHandle)) throw new InvalidOperationException("Overlay did not close on disable.");
            Passed = true;
        }
        catch (Exception error) { Console.Error.WriteLine(error.Message); }
        finally { _host?.Dispose(); Close(); }
    }
    private static IEnumerable<Control> Descendants(Control parent)
    {
        foreach (Control child in parent.Controls)
        { yield return child; foreach (var nested in Descendants(child)) yield return nested; }
    }
    internal static void RenderCounter()
    {
        string file = Path.Combine(ProjectPaths.Root, "plugins", "neocronsharp.game-status", "GameStatusOverlay.dll");
        var assembly = System.Reflection.Assembly.LoadFrom(file);
        var type = assembly.GetType("GameStatusOverlay.StatusPanel", true)!;
        using var panel = (Form)Activator.CreateInstance(type, nonPublic: true)!;
        var method = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
        type.GetMethod("UpdateData", method)!.Invoke(panel, new object[] { new PluginTelemetry(DateTimeOffset.UtcNow, 123, 45, 678, 42, 1, 0) });
        panel.Location = Point.Empty; panel.Opacity = 0.01;
        type.GetMethod("ShowOverlay", method)!.Invoke(panel, null);
        Application.DoEvents();
        using var bitmap = new Bitmap(panel.Width, panel.Height);
        using var graphics = Graphics.FromImage(bitmap);
        nint dc = graphics.GetHdc();
        try { if (!PrintWindow(panel.Handle, dc, 2)) throw new InvalidOperationException("Could not render NPC counter."); }
        finally { graphics.ReleaseHdc(dc); }
        Directory.CreateDirectory(Path.Combine(ProjectPaths.Root, "logs"));
        bitmap.Save(Path.Combine(ProjectPaths.Root, "logs", "npc-counter-render.png"));
        type.GetMethod("HideOverlay", method)!.Invoke(panel, null);
    }
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern nint GetWindowLongPtr(nint window, int index);
    [DllImport("user32.dll")] private static extern nint GetForegroundWindow();
    private static nint FindOwnOverlay()
    {
        nint found = 0;
        EnumWindows((window, _) =>
        {
            GetWindowThreadProcessId(window, out uint pid);
            if (pid != Environment.ProcessId) return true;
            var text = new System.Text.StringBuilder(128); GetWindowText(window, text, text.Capacity);
            if (text.ToString() != "Neocron status overlay") return true;
            found = window; return false;
        }, 0);
        return found;
    }
    private delegate bool EnumWindowProc(nint window, nint state);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool EnumWindows(EnumWindowProc callback, nint state);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(nint window, out uint pid);
    [DllImport("user32.dll", EntryPoint = "GetWindowTextW", CharSet = CharSet.Unicode)] private static extern int GetWindowText(nint window, System.Text.StringBuilder text, int count);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsWindowVisible(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsWindow(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool PrintWindow(nint window, nint dc, uint flags);
    [StructLayout(LayoutKind.Sequential)] private struct NativePoint { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct NativeRect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool ClientToScreen(nint window, ref NativePoint point);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetWindowRect(nint window, out NativeRect rect);
}
