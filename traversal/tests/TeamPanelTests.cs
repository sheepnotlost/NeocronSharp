using System.Runtime.InteropServices.WindowsRuntime;
using NavmeshPrototype;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;

/// <summary>(Names compare without case: the C OCR reads a capital C as c at this size.) The team panel reader on the 7 Nov screenshots (the same ones tests/test_team_panel.py reads).</summary>
internal static class TeamPanelTests
{
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }

    private static byte[] Frame(string name, int y, out int width, out int height)
    {
        string path = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, @"..\..\..\..\..\tests\fixtures", name));
        using var stream = File.OpenRead(path).AsRandomAccessStream();
        var decoder = BitmapDecoder.CreateAsync(stream).AsTask().GetAwaiter().GetResult();
        var pixels = decoder.GetPixelDataAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Ignore, new BitmapTransform(), ExifOrientationMode.IgnoreExifOrientation, ColorManagementMode.DoNotColorManage)
            .AsTask().GetAwaiter().GetResult().DetachPixelData();
        width = 2000; height = 1125;
        var frame = new byte[width * height * 4];
        for (int i = 3; i < frame.Length; i += 4) frame[i] = 255;
        int w = (int)decoder.PixelWidth, h = (int)decoder.PixelHeight;
        for (int row = 0; row < h; row++) System.Buffer.BlockCopy(pixels, row * w * 4, frame, ((y + row) * width) * 4, w * 4);
        return frame;
    }

    private static string Show(Dictionary<int, int?> buffs) => string.Join(",", buffs.OrderBy(b => b.Key).Select(b => $"{b.Key}:{b.Value}"));

    public static void Run(Action<string, Action> test)
    {
        test("Team panel: one member, four buffs with their seconds", () =>
        {
            var members = new TeamPanel().Read(Frame("team_panel_one.png", 480, out var w, out var h), w, h);
            Check(members.Count == 1, $"one bar, got {members.Count}");
            Check(string.Equals(members[0].Name, "Canibaal", StringComparison.OrdinalIgnoreCase) && members[0].Health == 100, $"name and health: {members[0].Name} {members[0].Health}");
            Check(Show(members[0].Buffs) == "2:87,3:84,4:80,5:496", "buffs: " + Show(members[0].Buffs));
        });

        test("Team panel: two members stacked, the second with no buffs and less health", () =>
        {
            var members = new TeamPanel().Read(Frame("team_panel_two.png", 410, out var w, out var h), w, h);
            Check(members.Count == 2, $"two bars, got {members.Count}");
            Check(string.Equals(members[0].Name, "Canibaal", StringComparison.OrdinalIgnoreCase) && members[0].Health == 100 && Show(members[0].Buffs) == "5:240", "first: " + Show(members[0].Buffs));
            Check(string.Equals(members[1].Name, "Bertel", StringComparison.OrdinalIgnoreCase) && members[1].Health == 97 && members[1].Buffs.Count == 0, $"second: {members[1].Name} {members[1].Health} {Show(members[1].Buffs)}");
        });

        test("Team panel: no panel, no members", () =>
        {
            Check(new TeamPanel().Read(new byte[2000 * 1125 * 4], 2000, 1125).Count == 0, "nothing on a dark frame");
        });
    }
}
