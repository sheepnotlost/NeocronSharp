using System.IO.Compression;
using System.Numerics;
using System.Text;
using NeocronSharp.Core;

internal static class MapTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        var plaza = new SectorMapDefinition(1, "PLAZA SEC-1", 2001, "gfx/maps/plaza_p1_sm.bmp", new(195, 204), new(-3248, -2767), 0.028f);
        test("Sector reference maps to its bitmap anchor independently of height", () =>
        {
            foreach (int rotation in new[] { 0, 90, 180, 270 })
                check(Vector2.Distance(plaza.Project(new(-3248, 999, -2767), rotation), new(195, 204)) < 0.001f, "Map anchor drifted");
        });
        test("Plaza COPBOT projection matches the game's verified 270-degree transform", () =>
        {
            var point = plaza.Project(new(-1469, -256, 1069), 270);
            check(Vector2.Distance(point, new(145.188f, 96.592f)) < 0.001f, "Wrong axis sign, offset or map scale");
            var unrotated = plaza.Project(new(-2248, 0, -2767), 90);
            check(Vector2.Distance(unrotated, new(223, 204)) < 0.001f, "Quarter-turn orientation must be supported");
        });
        test("Invalid map coordinates and scaling are rejected", () =>
        {
            bool rejected = false;
            try { (plaza with { Scale = float.NaN }).Project(Vector3.Zero, 270); } catch (InvalidOperationException) { rejected = true; }
            check(rejected, "Invalid scale must not place fake map markers");
        });
        test("Sector changes invalidate tracking even when the world root and actor addresses are reused", () =>
        {
            var entity = new WorldEntity(new(0x11000, 0x12000, 0x13000, 0x14000, 1, EntityKind.Npc), "COPBOT", Vector3.Zero, "SCRIPTEDPLAYER");
            var first = new EntitySnapshot(DateTimeOffset.UtcNow, 0x11000, 0x12000, Vector3.Zero, -Vector3.UnitZ, new[] { entity }, 1, new(1, 270));
            var tracking = new EntityTracking(); tracking.Update(first); tracking.Track(entity);
            tracking.Update(first with { Sector = new(2, 270) });
            check(tracking.Lost && tracking.Appeared == 0 && tracking.Disappeared == 0, "A new sector must not retain a reused actor or count all NPCs as new spawns");
        });
        test("Map viewport letterboxes without stretching and preserves picking after pan", () =>
        {
            var view = new MapViewport { ViewSize = new(1000, 500), ImageSize = new(256, 256) };
            var a = view.ToScreen(Vector2.Zero); var b = view.ToScreen(new(256, 256));
            check(Math.Abs((b.X - a.X) - (b.Y - a.Y)) < 0.001 && a.X > a.Y, "Square image must remain square");
            view.Drag(new(50, -70)); var point = new Vector2(75, 180);
            check(Vector2.Distance(view.FromScreen(view.ToScreen(point)), point) < 0.001, "Pan must preserve hit-test coordinates");
        });
        test("Map zoom stays under the cursor, respects bounds, and resets on sector change", () =>
        {
            var view = new MapViewport { ViewSize = new(600, 500) }; var cursor = new Vector2(210, 190);
            Vector2 before = view.FromScreen(cursor); view.ZoomAt(cursor, 2);
            check(Vector2.Distance(before, view.FromScreen(cursor)) < 0.001, "Zoom anchor moved");
            view.ZoomAt(cursor, 100); check(view.Zoom == 12, "Zoom cap missing");
            view.ZoomAt(cursor, 0.001f); check(view.Zoom == 1, "Minimum zoom missing");
            view.Reset(); check(view.Pan == Vector2.Zero && view.Zoom == 1, "New sector must reset viewport");
        });
        test("Map catalog joins bitmap IDs to map assets rather than unrelated resource namespaces", () =>
        {
            WithFolder(folder =>
            {
                var defs = Path.Combine(folder, "definitions"); var gfx = Path.Combine(folder, "gfx"); Directory.CreateDirectory(defs); Directory.CreateDirectory(gfx);
                File.WriteAllBytes(Path.Combine(defs, "pak_worldinfo.csv"), NpcDataTests.Pack("EntryId,Enabled,Name\n1,1,PLAZA SEC-1\n2,1,PLAZA SEC-2\n"));
                File.WriteAllBytes(Path.Combine(defs, "pak_maps.csv"), NpcDataTests.Pack("EntryId,Enabled,WorldId,BitmapId,BitmapRefX,BitmapRefY,WorldRefX,WorldRefZ,Scale\n1,1,1,2001,195,204,-3248,-2767,0.028\n2,1,2,2002,0,0,0,0,0.05\n"));
                File.WriteAllBytes(Path.Combine(gfx, "pak_gfx.ini"), NpcDataTests.Pack("set 2001 \"gfx\\modeltextures\\unrelated.dds\";\nset 2001 \"gfx\\maps\\plaza_p1_sm.bmp\", \"gfx\\maps\\plaza_p1_sm_a.bmp\", 0;\n"));
                var catalog = new SectorMapCatalog(folder);
                check(catalog.Count == 1 && catalog.Find(1)!.AssetPath == "gfx/maps/plaza_p1_sm.bmp", "Bitmap namespace join failed");
                check(catalog.Find(2) == null && catalog.Name(2) == "PLAZA SEC-2" && catalog.Find(999) == null, "Missing maps must not reuse another sector's image");
                foreach (string file in Directory.GetFiles(defs)) File.Delete(file);
                File.Delete(Path.Combine(gfx, "pak_gfx.ini")); Directory.Delete(gfx); Directory.Delete(defs);
            });
        });
        test("Local PAK reader decompresses just the named asset with case-insensitive paths", () =>
        {
            WithFolder(folder =>
            {
                string file = Path.Combine(folder, "gfx.pak"); byte[] expected = Encoding.ASCII.GetBytes("native-map-bitmap-fixture");
                WriteArchive(file, expected);
                var archive = new GamePakArchive(file);
                check(archive.Read("gfx/MAPS/PLAZA_P1_SM.BMP").SequenceEqual(expected), "Named PAK entry failed to round-trip");
                File.Delete(file);
            });
        });
        test("Archive bounds and incorrect expansion sizes fail without unsafe reads", () =>
        {
            WithFolder(folder =>
            {
                string file = Path.Combine(folder, "gfx.pak"); WriteArchive(file, new byte[100]);
                byte[] bytes = File.ReadAllBytes(file); BitConverter.GetBytes(uint.MaxValue).CopyTo(bytes, 12); File.WriteAllBytes(file, bytes);
                bool failed = false; try { _ = new GamePakArchive(file); } catch (InvalidDataException) { failed = true; }
                check(failed, "Out-of-file PAK entry was accepted");
                WriteArchive(file, new byte[100]); bytes = File.ReadAllBytes(file); BitConverter.GetBytes(1).CopyTo(bytes, 20); File.WriteAllBytes(file, bytes);
                failed = false; try { new GamePakArchive(file).Read("maps/plaza_p1_sm.bmp"); } catch (InvalidDataException) { failed = true; }
                check(failed, "Wrong expansion size was accepted"); File.Delete(file);
            });
        });
        test("Local compressed map updates take priority over archive images", () =>
        {
            WithFolder(folder =>
            {
                string gfx = Path.Combine(folder, "gfx"); Directory.CreateDirectory(gfx);
                byte[] bitmap = new byte[80]; bitmap[0] = (byte)'B'; bitmap[1] = (byte)'M';
                string file = Path.Combine(gfx, "pak_test.bmp");
                // Use the native envelope around arbitrary binary, not UTF-8 text.
                using var envelope = new MemoryStream();
                envelope.Write(new byte[] { 0x0a, 0xf7, 0x3d, 0x88, 0x84, 0x75, 0x84, 0x93, 0xbd, 0xef, 0xfd, 0xab });
                envelope.Write(BitConverter.GetBytes(bitmap.Length));
                using (var zip = new ZLibStream(envelope, CompressionLevel.Fastest, leaveOpen: true)) zip.Write(bitmap);
                File.WriteAllBytes(file, envelope.ToArray());
                byte[] read = GameMapFiles.Read(folder, "gfx/test.bmp", _ => throw new Exception("Should use the local map update"));
                check(read.SequenceEqual(bitmap), "Local BMP envelope was not decoded");
                File.Delete(file); Directory.Delete(gfx);
            });
        });
        test("Local map paths cannot escape the game install", () =>
        {
            bool rejected = false;
            try { GameMapFiles.Read(Path.GetTempPath(), "../outside.bmp", _ => Array.Empty<byte>()); } catch (InvalidDataException) { rejected = true; }
            check(rejected, "Map traversal path was accepted");
        });
    }
    private static void WriteArchive(string path, byte[] payload)
    {
        byte[] name = Encoding.ASCII.GetBytes("maps\\plaza_p1_sm.bmp\0");
        using var compressed = new MemoryStream();
        using (var zip = new ZLibStream(compressed, CompressionLevel.Fastest, leaveOpen: true)) zip.Write(payload);
        using var file = File.Create(path); using var writer = new BinaryWriter(file);
        writer.Write(0x3d458cdeU); writer.Write(1); writer.Write(20 + name.Length); writer.Write(8 + 20 + name.Length);
        writer.Write((int)compressed.Length); writer.Write(payload.Length); writer.Write(name.Length); writer.Write(name); writer.Write(compressed.ToArray());
    }
    private static void WithFolder(Action<string> action)
    {
        string folder = Path.Combine(Path.GetTempPath(), "NeocronSharp-map-test-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(folder);
        try { action(folder); }
        finally { if (!Directory.EnumerateFileSystemEntries(folder).Any()) Directory.Delete(folder); }
    }
}
