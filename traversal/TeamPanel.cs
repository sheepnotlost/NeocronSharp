using System.Runtime.InteropServices.WindowsRuntime;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;

namespace NavmeshPrototype;

/// <summary>One team member as the panel shows them: name, health, and each buff slot's seconds left (null: shown, timer unread).</summary>
internal sealed record PanelMember(string Name, int? Health, int Top, Dictionary<int, int?> Buffs);

/// <summary>
/// The team panel on the left of the game view (Alt+T): a green bar per member (name, health) and under it their buff
/// icons with the seconds left. Always on screen, so a healer reads who needs what without aiming at anyone. Ported
/// from team_panel.py (tested there on the 7 Nov screenshots); found by the bars, so it works wherever it sits and at any size.
/// Slots: 1 heal (green cross), 2 pale ring, 3 red ring, 4 blue ring, 5 anchor.
/// </summary>
internal sealed class TeamPanel
{
    private const float BarHeight = 26f, Icon = 35f, Pitch = 37.7f;
    private const int MaxIcons = 8;
    private static readonly (int R, int G, int B) Bar = (60, 175, 112);

    private readonly OcrEngine _ocr = OcrEngine.TryCreateFromLanguage(new Windows.Globalization.Language("en-US"))
        ?? throw new InvalidOperationException("Windows English text recognition is unavailable.");

    /// <summary>The panel in a picture of the client's left side (top-down BGRA, <paramref name="width"/> x <paramref name="height"/>).</summary>
    public List<PanelMember> Read(byte[] bgra, int width, int height)
    {
        var members = new List<PanelMember>();
        foreach (var (x, y, w, h) in Bars(bgra, width, height))
        {
            float s = h / BarHeight;
            int full = Math.Min(width - x, (int)MathF.Round(308 * s));
            var words = Words(Gray(bgra, width, x, y, full, h), full, h, 3);
            string name = string.Join(" ", words.Where(t => t.X < 210 * s && !t.Text.All(char.IsDigit)).OrderBy(t => t.X).Select(t => t.Text)).Trim();
            string digits = string.Concat(words.Where(t => t.X > 210 * s && t.Text.All(char.IsDigit)).OrderBy(t => t.X).Select(t => t.Text));
            var buffs = new Dictionary<int, int?>();
            int top = y + h + (int)MathF.Round(2 * s), tile = (int)MathF.Round(Icon * s);
            for (int i = 0; i < MaxIcons; i++)
            {
                int left = x + (int)MathF.Round(i * Pitch * s);
                if (left + tile > width || top + tile > height) break;
                if (Mean(bgra, width, left, top, tile, tile) < 60) break;       // the dark background: no more icons
                int? slot = Classify(bgra, width, left, top, tile);
                if (slot == null) continue;
                int ly = top + tile - (int)MathF.Round(s), lh = (int)MathF.Round(20 * s), lx = Math.Max(0, left - (int)MathF.Round(s)), lw = Math.Min(width - lx, (int)MathF.Round(36.5f * s));
                int? seconds = null;
                if (ly + lh <= height && lw > 4)
                {
                    var small = Gray(bgra, width, lx, ly, lw, lh);
                    foreach (int k in new[] { 6, 5, 7, 4 })      // the small digits read at some enlargements and not at others
                    {
                        var label = Words(Resize(small, lw, lh, k), lw * k, lh * k, 1);
                        string text = new(string.Concat(label.Select(t => t.Text)).Where(char.IsDigit).ToArray());
                        if (text.Length > 0 && int.TryParse(text, out var n)) { seconds = n; break; }
                    }
                }
                buffs[slot.Value] = seconds;
            }
            members.Add(new PanelMember(name, int.TryParse(digits, out var hp) ? hp : null, y, buffs));
        }
        return members;
    }

    private static List<(int X, int Y, int W, int H)> Bars(byte[] bgra, int width, int height)
    {
        // Rows where a long run of the bar's green starts at the left; consecutive ones are one bar.
        var found = new List<(int, int, int, int)>();
        int limit = Math.Min(width, (int)(width * .22f));
        bool InBar(int i) => Math.Abs(bgra[i + 2] - Bar.R) < 28 && Math.Abs(bgra[i + 1] - Bar.G) < 28 && Math.Abs(bgra[i] - Bar.B) < 28;
        int startY = -1, minX = int.MaxValue, maxX = 0;
        for (int y = 0; y <= height; y++)
        {
            int count = 0, first = int.MaxValue, last = 0;
            if (y < height)
                for (int x = 0; x < limit; x++)
                    if (InBar((y * width + x) * 4)) { count++; first = Math.Min(first, x); last = x; }
            bool row = count >= 100 && count >= (last - first + 1) * .4;
            if (row)
            {
                if (startY < 0) startY = y;
                minX = Math.Min(minX, first); maxX = Math.Max(maxX, last);
            }
            else if (startY >= 0)
            {
                int h = y - startY;
                if (h >= 12 && h <= 90) found.Add((minX, startY, maxX - minX + 1, h));
                startY = -1; minX = int.MaxValue; maxX = 0;
            }
        }
        return found;
    }

    private static int? Classify(byte[] bgra, int width, int left, int top, int size)
    {
        int heal = 0, red = 0, blue = 0, area = size * size;
        for (int y = 0; y < size; y++)
            for (int x = 0; x < size; x++)
            {
                int i = ((top + y) * width + left + x) * 4, b = bgra[i], g = bgra[i + 1], r = bgra[i + 2];
                if (r < 90 && g > 200 && b < 110) heal++;
                if (r > 45 && r > g * 1.8 && r > b * 2.5) red++;
                if (b > 110 && r < 60 && g < 70) blue++;
            }
        if (heal > .04 * area) return 1;
        if (red > .02 * area) return 3;
        if (blue > .02 * area) return 4;
        var tile = Gray(bgra, width, left, top, size, size);
        double best = .5; int? slot = null;
        foreach (var (number, reference) in new[] { (2, TeamIcons.Slot2), (5, TeamIcons.Slot5) })
        {
            double score = Match(tile, size, reference);
            if (score > best) { best = score; slot = number; }
        }
        return slot;
    }

    /// <summary>The best normalised correlation of the reference's middle (25 px at scale 1, scaled) anywhere in the tile.</summary>
    private static double Match(byte[] tile, int size, byte[] reference)
    {
        float k = size / Icon;
        int m = Math.Max(4, (int)MathF.Round(25 * k));
        var patch = new double[m * m];
        for (int y = 0; y < m; y++)
            for (int x = 0; x < m; x++)
                patch[y * m + x] = reference[(5 + (int)(y / k)) * 35 + 5 + (int)(x / k)];
        double pm = patch.Average(), pn = Math.Sqrt(patch.Sum(v => (v - pm) * (v - pm)));
        if (pn < 1e-6) return 0;
        double best = -1;
        for (int oy = 0; oy + m <= size; oy++)
            for (int ox = 0; ox + m <= size; ox++)
            {
                double sum = 0, sq = 0;
                for (int y = 0; y < m; y++)
                    for (int x = 0; x < m; x++) { double v = tile[(oy + y) * size + ox + x]; sum += v; sq += v * v; }
                double mean = sum / (m * m), norm = Math.Sqrt(Math.Max(0, sq - m * m * mean * mean));
                if (norm < 1e-6) continue;
                double dot = 0;
                for (int y = 0; y < m; y++)
                    for (int x = 0; x < m; x++) dot += (tile[(oy + y) * size + ox + x] - mean) * (patch[y * m + x] - pm);
                best = Math.Max(best, dot / (norm * pn));
            }
        return best;
    }

    private static double Mean(byte[] bgra, int width, int left, int top, int w, int h)
    {
        long sum = 0;
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++) { int i = ((top + y) * width + left + x) * 4; sum += bgra[i] + bgra[i + 1] + bgra[i + 2]; }
        return sum / (3.0 * w * h);
    }

    private static byte[] Gray(byte[] bgra, int width, int left, int top, int w, int h)
    {
        var gray = new byte[w * h];
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
            {
                int i = ((top + y) * width + left + x) * 4;
                gray[y * w + x] = (byte)((bgra[i + 2] * 299 + bgra[i + 1] * 587 + bgra[i] * 114) / 1000);
            }
        return gray;
    }

    private static byte[] Resize(byte[] gray, int w, int h, int k)
    {
        int W = w * k, H = h * k;
        var big = new byte[W * H];
        for (int y = 0; y < H; y++)
        {
            float fy = Math.Clamp((y + .5f) / k - .5f, 0, h - 1), y0 = MathF.Floor(fy); int y1 = Math.Min(h - 1, (int)y0 + 1); float ty = fy - y0;
            for (int x = 0; x < W; x++)
            {
                float fx = Math.Clamp((x + .5f) / k - .5f, 0, w - 1), x0 = MathF.Floor(fx); int x1 = Math.Min(w - 1, (int)x0 + 1); float tx = fx - x0;
                float top = gray[(int)y0 * w + (int)x0] * (1 - tx) + gray[(int)y0 * w + x1] * tx, bottom = gray[y1 * w + (int)x0] * (1 - tx) + gray[y1 * w + x1] * tx;
                big[y * W + x] = (byte)(top * (1 - ty) + bottom * ty);
            }
        }
        return big;
    }

    /// <summary>Words in light-on-dark gray text, in the picture's own pixels (<paramref name="up"/>: how much it is enlarged first).</summary>
    private List<(string Text, int X, int Y)> Words(byte[] gray, int w, int h, int up)
    {
        if (up > 1) { gray = Resize(gray, w, h, up); w *= up; h *= up; }
        const int pad = 10;
        int W = w + 2 * pad, H = h + 2 * pad;
        var bytes = new byte[W * H * 4];
        Array.Fill(bytes, (byte)255);
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
            {
                byte v = (byte)(255 - gray[y * w + x]);
                int i = ((y + pad) * W + x + pad) * 4;
                bytes[i] = bytes[i + 1] = bytes[i + 2] = v; bytes[i + 3] = 255;
            }
        using var bitmap = SoftwareBitmap.CreateCopyFromBuffer(bytes.AsBuffer(), BitmapPixelFormat.Bgra8, W, H, BitmapAlphaMode.Ignore);
        var result = _ocr.RecognizeAsync(bitmap).AsTask().GetAwaiter().GetResult();
        var words = new List<(string, int, int)>();
        foreach (var line in result.Lines)
            foreach (var word in line.Words)
                words.Add((word.Text, (int)Math.Round((word.BoundingRect.X - pad) / up), (int)Math.Round((word.BoundingRect.Y - pad) / up)));
        return words;
    }
}
