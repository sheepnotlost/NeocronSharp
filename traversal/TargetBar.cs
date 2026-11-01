using System.Runtime.InteropServices;

namespace NavmeshPrototype;

/// <summary>
/// The game's red bar at the top of the screen shows only while the crosshair can really target something, so it answers
/// what no map here can: a hill or rock in the way, and the target limit. Read from the right of the bar, clear of the Hud.
/// </summary>
internal static class TargetBar
{
    private const float Left = .50f, Right = .67f, Top = .036f, Bottom = .06f,   // of the client area
        BarEnds = .735f,                                                         // of the region: red bar to here, then its green end
        Share = .3f;

    /// <summary>Is the bar in this picture of the region, top-down BGRA? The green end stays when a hurt mob's red drains.</summary>
    public static bool Looks(byte[] bgra, int width, int height)
    {
        int split = (int)(width * BarEnds), red = 0, green = 0;
        for (int y = 0; y < height; y++)
            for (int x = 0; x < width; x++)
            {
                int i = (y * width + x) * 4, b = bgra[i], g = bgra[i + 1], r = bgra[i + 2];
                if (x < split) { if (r > 120 && g < 70 && b < 70) red++; }
                else if (g > 170 && r < 170 && b < 200 && g - r > 40) green++;
            }
        return red > split * height * Share || green > (width - split) * height * Share;
    }

    public static bool Showing(nint window)
    {
        if (!GetClientRect(window, out var client)) return false;
        var corner = new Point();
        if (!ClientToScreen(window, ref corner)) return false;
        int x = corner.X + (int)(client.Right * Left), y = corner.Y + (int)(client.Bottom * Top);
        int width = (int)(client.Right * (Right - Left)), height = (int)(client.Bottom * (Bottom - Top));
        if (width < 1 || height < 1) return false;
        nint screen = GetDC(0), memory = CreateCompatibleDC(screen), picture = CreateCompatibleBitmap(screen, width, height);
        try
        {
            var pixels = new byte[width * height * 4];
            var header = new BitmapHeader { Size = 40, Width = width, Height = -height, Planes = 1, Bits = 32 };
            SelectObject(memory, picture);
            return BitBlt(memory, 0, 0, width, height, screen, x, y, 0x00CC0020) &&   // SRCCOPY
                GetDIBits(memory, picture, 0, (uint)height, pixels, ref header, 0) != 0 && Looks(pixels, width, height);
        }
        finally
        {
            DeleteObject(picture);
            DeleteDC(memory);
            ReleaseDC(0, screen);
        }
    }

    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct Box { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)]
    private struct BitmapHeader
    {
        public uint Size; public int Width, Height; public ushort Planes, Bits;
        public uint Compression, ImageSize; public int XPerMeter, YPerMeter; public uint Used, Important;
    }

    [DllImport("user32.dll")] private static extern bool GetClientRect(nint window, out Box box);
    [DllImport("user32.dll")] private static extern bool ClientToScreen(nint window, ref Point point);
    [DllImport("user32.dll")] private static extern nint GetDC(nint window);
    [DllImport("user32.dll")] private static extern int ReleaseDC(nint window, nint dc);
    [DllImport("gdi32.dll")] private static extern nint CreateCompatibleDC(nint dc);
    [DllImport("gdi32.dll")] private static extern nint CreateCompatibleBitmap(nint dc, int width, int height);
    [DllImport("gdi32.dll")] private static extern nint SelectObject(nint dc, nint thing);
    [DllImport("gdi32.dll")] private static extern bool BitBlt(nint to, int x, int y, int width, int height, nint from, int fromX, int fromY, uint how);
    [DllImport("gdi32.dll")] private static extern int GetDIBits(nint dc, nint picture, uint start, uint lines, byte[] pixels, ref BitmapHeader header, uint usage);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(nint thing);
    [DllImport("gdi32.dll")] private static extern bool DeleteDC(nint dc);
}
