using System.Runtime.InteropServices;

namespace NeocronSharp;

/// <summary>Shows the tracker inside another program's window: the suite's Tracker, Quests and Plugins tabs. Commands
/// arrive one per line on stdin: "parent &lt;hwnd&gt;" moves the form into that window, "page &lt;name&gt;" picks the
/// Tracker/Quests/Plugins page, "quit" or the end of input closes it. The form follows the parent's client size, so the
/// two programs' DPI settings never have to agree.</summary>
internal static class EmbeddedHost
{
    private const int GwlStyle = -16;
    private const long WsChild = 0x40000000, WsPopup = 0x80000000, WsCaption = 0x00C00000, WsThickFrame = 0x00040000,
        WsMinimizeBox = 0x00020000, WsMaximizeBox = 0x00010000, WsSysMenu = 0x00080000;
    [DllImport("user32.dll", SetLastError = true)] private static extern nint SetParent(nint child, nint parent);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern nint GetWindowLongPtr(nint window, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] private static extern nint SetWindowLongPtr(nint window, int index, nint value);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetClientRect(nint window, out Rect rect);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool MoveWindow(nint window, int x, int y, int width, int height, bool repaint);
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }

    public static void Attach(TrackerForm form, TextReader input)
    {
        form.UseEmbeddedLayout();
        nint parent = 0; Size fitted = Size.Empty;
        var follow = new System.Windows.Forms.Timer { Interval = 200 };
        void Fit()
        {
            if (parent == 0 || form.IsDisposed) return;
            if (!Native.IsWindow(parent)) { form.Close(); return; }
            if (!GetClientRect(parent, out var rect)) return;
            var size = new Size(rect.Right - rect.Left, rect.Bottom - rect.Top);
            if (size == fitted || size.Width <= 0 || size.Height <= 0) return;
            fitted = size; MoveWindow(form.Handle, 0, 0, size.Width, size.Height, true);
        }
        void Run(string line)
        {
            if (form.IsDisposed) return;
            string[] parts = line.Trim().Split(' ', 2, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0) return;
            switch (parts[0])
            {
                case "parent" when parts.Length == 2 && long.TryParse(parts[1], out long handle) && handle != 0:
                    long style = (GetWindowLongPtr(form.Handle, GwlStyle) & ~(WsPopup | WsCaption | WsThickFrame | WsMinimizeBox | WsMaximizeBox | WsSysMenu)) | WsChild;
                    SetWindowLongPtr(form.Handle, GwlStyle, (nint)style);
                    SetParent(form.Handle, (nint)handle);
                    parent = (nint)handle; fitted = Size.Empty; Fit();
                    break;
                case "page" when parts.Length == 2: form.ShowPage(parts[1]); break;
                case "quit": Detach(); form.Close(); break;
            }
        }
        // Leave the suite's window before closing, so its teardown never destroys this window underneath WinForms.
        void Detach() { if (parent != 0 && form.IsHandleCreated) { SetParent(form.Handle, 0); parent = 0; } }
        follow.Tick += (_, _) => Fit();
        form.FormClosed += (_, _) => follow.Dispose();
        var reader = new Thread(() =>
        {
            try
            {
                for (string? line; (line = input.ReadLine()) != null;)
                {
                    string command = line;
                    if (form.IsHandleCreated && !form.IsDisposed) form.BeginInvoke(() => Run(command));
                }
            }
            catch (IOException) { }
            if (form.IsHandleCreated && !form.IsDisposed) form.BeginInvoke(() => { if (!form.IsDisposed) { Detach(); form.Close(); } });
        }) { IsBackground = true, Name = "Embedded commands" };
        form.Shown += (_, _) => { follow.Start(); reader.Start(); };
    }
}
