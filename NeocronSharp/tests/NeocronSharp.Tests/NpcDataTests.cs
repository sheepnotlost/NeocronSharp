using System.IO.Compression;
using System.Text;
using NeocronSharp.Core;

internal static class NpcDataTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        void Reject(byte[] file)
        {
            try { NpcDefinitions.Parse(file); } catch (Exception error) when (error is IOException or InvalidDataException) { return; }
            throw new Exception("Corrupt reference data was accepted");
        }
        test("Health uses HUD bounds and never hides the raw client accumulator", () =>
        {
            var full = NpcHealth.FromNative(18000, 15168)!;
            check(full.Current == 15168 && full.RawCurrent == 18000 && full.Percent == 100 && full.WasClamped, "Over-max health must match HUD bounds");
            var dead = NpcHealth.FromNative(-5, 100)!;
            check(dead.Current == 0 && dead.Percent == 0, "Negative health display must be zero");
            var injured = NpcHealth.FromNative(30, 120)!;
            check(injured.Percent == 25 && !injured.WasClamped, "Injured health ratio must remain real");
            check(NpcHealth.FromNative(0, 0) == null && NpcHealth.FromNative(int.MaxValue, 100) == null, "Invalid health must be unknown");
        });
        test("Compressed definition CSV supports quoted commas, quotes and embedded newlines", () =>
        {
            var rows = NpcDefinitions.Parse(Pack("EntryId,Enabled,Name\n1,1,\"Rifle, \"\"Plasma\"\"\nMk II\"\n2,0,Disabled\n"));
            check(rows.Count == 1 && rows[1]["Name"] == "Rifle, \"Plasma\"\nMk II", "CSV quoting or enabled-row handling failed");
        });
        test("Definition header, expansion limits, duplicate IDs and missing columns are checked", () =>
        {
            Reject(new byte[32]);
            var huge = Pack("EntryId,Enabled\n1,1\n"); BitConverter.GetBytes(int.MaxValue).CopyTo(huge, 12); Reject(huge);
            var shortFile = Pack("EntryId,Enabled\n1,1\n"); BitConverter.GetBytes(1).CopyTo(shortFile, 12); Reject(shortFile);
            Reject(Pack("EntryId,Enabled\n1,1\n1,1\n")); Reject(Pack("Name\nNPC\n"));
        });
        test("Reference lookup uses native IDs and keeps base stats separate from live stats", () =>
        {
            WithDefinitions(folder =>
            {
                var definitions = NpcDefinitions.Load(folder);
                check(definitions.Issues.Count == 0, "Valid definitions must load");
                var stats = new NpcStats(1, NpcHealth.FromNative(500, 1000), 60, 60, 1, 1651, 1, false, 1.5f, 15, 0, 6145);
                var entity = new WorldEntity(new(0x11000, 0x12000, 0x13000, 0x14000, 80, EntityKind.Npc), "COPBOT", new(), "SCRIPTEDPLAYER", stats);
                var enriched = definitions.Enrich(entity);
                var reference = enriched.ReferenceData ?? throw new Exception("Missing NPC reference data");
                check(enriched.Stats == stats && reference.BaseHealth == 15168 && reference.BaseRank == 120, "Definitions must not overwrite live HP/rank");
                check(reference.FactionName == "City Administration" && reference.WeaponName == "NPC CopBot Plasma Rifle TL 128" && reference.AiScript == "WCOP", "Native ID joins failed");
                check(reference.BaseWeaponRange == 500 && reference.WeaponLevel == 128, "Weapon reference data missing");
                check(reference.BaseMagazineSize == 20 && reference.ShotsPerBurst == 4, "Base magazine and burst configuration missing");
                var zeroFaction = definitions.Enrich(entity with { Stats = stats with { FactionId = 0 } });
                check(zeroFaction.ReferenceData!.FactionName == null, "Soul Light row zero is not a verified NPC faction name");
            });
        });
        test("Missing reference files leave native NPC stats usable", () =>
        {
            WithDefinitions(folder =>
            {
                File.Delete(Path.Combine(folder, "definitions", "pak_weapons.csv"));
                var definitions = NpcDefinitions.Load(folder);
                var stats = new NpcStats(1, NpcHealth.FromNative(100, 100), 120, 120, 1, 1651, 1, false, 1, 15, 0, 6145);
                var entity = new WorldEntity(new(), "COPBOT", new(), "SCRIPTEDPLAYER", stats);
                var enriched = definitions.Enrich(entity);
                check(definitions.Issues.Count == 1 && enriched.Stats!.Health!.Percent == 100 && enriched.ReferenceData!.FactionName == "City Administration" && enriched.ReferenceData.WeaponName == null,
                    "Missing weapon metadata must not break health/faction tracking");
            });
        });
        test("A corrupt optional definition is reported without discarding other reference tables", () =>
        {
            WithDefinitions(folder =>
            {
                File.WriteAllBytes(Path.Combine(folder, "definitions", "pak_weapons.csv"), new byte[24]);
                var definitions = NpcDefinitions.Load(folder);
                check(definitions.Issues.Count == 1 && definitions.Issues[0].StartsWith("pak_weapons.csv:"), "Corrupt optional files must be isolated");
            });
        });
    }

    internal static byte[] Pack(string text)
    {
        byte[] payload = Encoding.UTF8.GetBytes(text);
        using var output = new MemoryStream();
        output.Write(new byte[] { 0x0a, 0xf7, 0x3d, 0x88, 0x84, 0x75, 0x84, 0x93, 0xbd, 0xef, 0xfd, 0xab });
        output.Write(BitConverter.GetBytes(payload.Length));
        using (var zip = new ZLibStream(output, CompressionLevel.Fastest, leaveOpen: true)) zip.Write(payload);
        return output.ToArray();
    }

    private static void WithDefinitions(Action<string> action)
    {
        string folder = Path.Combine(Path.GetTempPath(), "NeocronSharp-npc-test-" + Guid.NewGuid().ToString("N"));
        string definitions = Path.Combine(folder, "definitions"); Directory.CreateDirectory(definitions);
        var files = new Dictionary<string, string>
        {
            ["pak_npcs.csv"] = "EntryId,Enabled,Skill,Health,AIScript,DialogScript\n1,1,120,15168,WCOP,NCPD\n",
            ["pak_factions.csv"] = "EntryId,Enabled,Name\n0,1,Soul Light\n1,1,City Administration\n",
            ["pak_weapons.csv"] = "EntryId,Enabled,Name,Level,Range,ClipSize,ShotCount\n1651,1,NPC CopBot Plasma Rifle TL 128,128,500,20,4\n"
        };
        try
        {
            foreach (var file in files) File.WriteAllBytes(Path.Combine(definitions, file.Key), Pack(file.Value));
            action(folder);
        }
        finally
        {
            foreach (string name in files.Keys) File.Delete(Path.Combine(definitions, name));
            Directory.Delete(definitions); Directory.Delete(folder);
        }
    }
}
