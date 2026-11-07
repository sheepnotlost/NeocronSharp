namespace NavmeshPrototype;

/// <summary>
/// Where the game draws a mob, in screen pixels from the crosshair (right and down positive): the box its corner
/// brackets make round the body. Memory gives the mob's feet only roughly where the body is drawn, so this is what the
/// aim is put on.
/// </summary>
internal readonly record struct TargetMark(float Left, float Top, float Right, float Bottom, bool Measured)
{
    public float X => (Left + Right) / 2;
    public float Y => (Top + Bottom) / 2;
    public float HalfWidth => (Right - Left) / 2;
    public float HalfHeight => (Bottom - Top) / 2;
}

/// <summary>
/// The game's marks on a mob near the crosshair (seen on 6 Nov, in both videos): its health box, "100%" in pinkish white
/// on red, and just below it the four red corner brackets round its body. The box's left edge is the brackets' left,
/// and they start 8 pixels below the box's text (at 1080 high). The far corners are found when they can be; where not,
/// the body is taken to be a small mob's size.
/// </summary>
internal static class TargetLock
{
    /// <summary>Of the client height, each way from the crosshair: the part of the screen looked at.</summary>
    public const float Reach = .3f;
    /// <summary>A small mob's brackets, of the client height: a Genotoxic Parasite was 45 x 19 to 74 x 35 at 1080.</summary>
    public const float SmallWidth = .05f, SmallHeight = .025f;

    /// <summary>The marks on screen now, and the client area's height; null when the screen could not be read.</summary>
    public static (List<TargetMark> Marks, int ClientHeight)? Look(nint window)
    {
        var grab = TargetBar.Grab(window, (w, h) =>
        {
            int half = (int)(h * Reach);
            return (w / 2 - half, h / 2 - half, 2 * half, 2 * half);
        });
        return grab is { } g ? (Find(g.Pixels, g.Width, g.ClientHeight), g.ClientHeight) : null;
    }

    /// <summary>The marks in a square picture centred on the crosshair, top-down BGRA, from a client area this many pixels high.</summary>
    public static List<TargetMark> Find(byte[] bgra, int size, int clientHeight)
    {
        float s = clientHeight / 1080f;
        int half = size / 2;
        bool Pink(int x, int y)
        {
            int i = (y * size + x) * 4, b = bgra[i], g = bgra[i + 1], r = bgra[i + 2];
            // Near white on screen (219,216,216 at 2560x1440, 7 Nov); a video blurs it pink (255,200,198).
            return r > 190 && g > 150 && b > 150 && r >= g - 4 && r - g < 70 && Math.Abs(g - b) < 24;
        }
        bool BoxRed(int x, int y)
        {
            int i = (y * size + x) * 4, b = bgra[i], g = bgra[i + 1], r = bgra[i + 2];
            return r > 140 && g < 80 && b < 80;
        }
        bool Red(int x, int y)
        {
            if (x < 0 || y < 0 || x >= size || y >= size) return false;
            int i = (y * size + x) * 4, b = bgra[i], g = bgra[i + 1], r = bgra[i + 2];
            return r > 80 && r - g > 30 && r - b > 30;
        }
        bool ThinAcross(int x, int y) => Red(x, y) && !Red(x, y - 3) && !Red(x, y + 3);
        bool ThinDown(int x, int y) => Red(x, y) && !Red(x - 3, y) && !Red(x + 3, y);

        // Pinkish white pixels, grouped by 8-pixel cells that touch.
        const int Cell = 8;
        var cells = new Dictionary<(int, int), List<(int X, int Y)>>();
        for (int y = 0; y < size; y++)
            for (int x = 0; x < size; x++)
                if (Pink(x, y))
                {
                    var key = (x / Cell, y / Cell);
                    if (!cells.TryGetValue(key, out var list)) cells[key] = list = new();
                    list.Add((x, y));
                }
        var marks = new List<TargetMark>();
        var seen = new HashSet<(int, int)>();
        foreach (var start in cells.Keys)
        {
            if (!seen.Add(start)) continue;
            var group = new List<(int X, int Y)>();
            var stack = new Stack<(int, int)>();
            stack.Push(start);
            while (stack.Count > 0)
            {
                var (cx, cy) = stack.Pop();
                group.AddRange(cells[(cx, cy)]);
                for (int dx = -1; dx <= 1; dx++)
                    for (int dy = -1; dy <= 1; dy++)
                        if (cells.ContainsKey((cx + dx, cy + dy)) && seen.Add((cx + dx, cy + dy))) stack.Push((cx + dx, cy + dy));
            }
            int x0 = group.Min(p => p.X), x1 = group.Max(p => p.X), y0 = group.Min(p => p.Y), y1 = group.Max(p => p.Y);
            if (group.Count < 12 * s * s || x1 - x0 > .06f * clientHeight || y1 - y0 > .02f * clientHeight || y1 - y0 < .004f * clientHeight) continue;
            // The red box behind the text: its health fill left of the first letter, or, low on health, only the fill's stub and
            // the outline further left. At 11% a dark gap of 8 px lay between them, the label went unseen, and a mob all but
            // dead was let go as out of view (7 Nov).
            int reach = (int)(.03f * clientHeight), boxed = 0;
            bool Edge(int x, int y) => BoxRed(x, y) || Red(x, y);
            for (int y = y0; y <= y1; y++)
                for (int x = x0 - 1; x >= Math.Max(0, x0 - reach); x--)
                    if (Edge(x, y)) { boxed++; break; }
            if (boxed < (y1 - y0) * .5f) continue;
            // The box's own edges: left along the text's middle row, bottom down its left side. The brackets start at the
            // box's left, a few pixels below it (6 at 1080 high, 9 at 1440).
            int middle = (y0 + y1) / 2, boxLeft = x0, boxBottom = y1;
            for (int x = Math.Max(0, x0 - reach); x < x0; x++)
                if (Edge(x, middle)) { boxLeft = x; break; }
            while (boxLeft > 0 && x0 - boxLeft < reach + 4 && Edge(boxLeft - 1, middle)) boxLeft--;
            int side = Math.Min(boxLeft + 1, x0 - 1 >= 0 ? x0 - 1 : x0);
            while (boxBottom + 1 < size && boxBottom - y1 < .01f * clientHeight && Edge(side, boxBottom + 1)) boxBottom++;
            float left = boxLeft, top = boxBottom + 6.5f * s;
            int l = (int)MathF.Round(left), t = (int)MathF.Round(top);
            var box = Brackets(l, t, clientHeight, size, ThinAcross, ThinDown);
            bool measured = box is not null;
            if (box is { } found) left = found.Left;
            float r = box?.Right ?? left + SmallWidth * clientHeight, b = box?.Bottom ?? top + SmallHeight * clientHeight;
            marks.Add(new TargetMark(left - half, top - half, r - half, b - half, measured));
        }
        return marks;
    }

    /// <summary>
    /// The brackets' right edge and bottom, from their top-left corner: a top-right corner on the top row, a bottom-left one
    /// in the left column (the label's left is the brackets' to within a few pixels: "92%" sat 5 right of them), and a
    /// bottom-right one where those two meet. Red floor tiles make corners of their own, so one
    /// corner alone proves nothing; three that make a box with the label's corner do.
    /// </summary>
    private static (int Left, int Right, int Bottom)? Brackets(int left, int top, int clientHeight, int size, Func<int, int, bool> across, Func<int, int, bool> down)
    {
        int arm = Math.Max(3, (int)MathF.Round(.0035f * clientHeight)), most = (int)(.45f * clientHeight);
        bool Arm(int x, int y, int dx, int dy, Func<int, int, bool> thin)
        {
            for (int k = 2; k <= arm + 1; k++) if (!thin(x + dx * k, y + dy * k)) return false;
            return true;
        }
        bool TopRight(int x, int y) => Arm(x, y, -1, 0, across) && Arm(x, y, 0, 1, down);
        bool BottomLeft(int x, int y) => Arm(x, y, 1, 0, across) && Arm(x, y, 0, -1, down);
        bool BottomRight(int x, int y) => Arm(x, y, -1, 0, across) && Arm(x, y, 0, -1, down);
        var rights = new List<int>();
        for (int x = left + (int)(.01f * clientHeight); x < Math.Min(size - 4, left + most); x++)
            for (int y = top - 3; y <= top + 3; y++)
                if (TopRight(x, y)) { rights.Add(x); break; }
        var bottoms = new List<(int X, int Y)>();
        for (int y = top + (int)(.008f * clientHeight); y < Math.Min(size - 4, top + most); y++)
            for (int x = left - (int)(.008f * clientHeight); x <= left + 4; x++)
                if (BottomLeft(x, y)) { bottoms.Add((x, y)); break; }
        foreach (var (bx, by) in bottoms)
            foreach (int x in rights)
                for (int dx = -2; dx <= 2; dx++)
                    for (int dy = -2; dy <= 2; dy++)
                        if (BottomRight(x + dx, by + dy)) return (bx, x + dx, by + dy);
        return null;
    }
}
