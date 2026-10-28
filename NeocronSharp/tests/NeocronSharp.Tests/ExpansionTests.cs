using System.IO.Compression;
using System.Numerics;
using System.Text;
using NeocronSharp.Core;

internal static class ExpansionTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        test("Eleven persistent skin IDs retain basic as one and distinguish all ten period styles", () =>
        {
            check(SkinCatalog.All.Count == 11 && SkinCatalog.Get(1).Material == "Matte" && SkinCatalog.All.Select(x => x.Id).SequenceEqual(Enumerable.Range(1,11)), "Skin identity mismatch");
            check(SkinCatalog.All.Select(x => x.Name).Distinct().Count() == 11 && SkinCatalog.Get(-10).Id == 1, "Unknown skins must fall back to basic");
        });
        test("Every skin keeps readable body, muted and LCD text contrast", () =>
        {
            foreach (var skin in SkinCatalog.All)
            {
                foreach (int surface in new[] {skin.Window,skin.Surface,skin.Input,skin.Selection})
                {
                    check(SkinCatalog.Contrast(skin.Ink,surface) >= 4.5, $"{skin.Name}: body contrast");
                    check(SkinCatalog.Contrast(skin.Muted,surface) >= 4.5, $"{skin.Name}: muted contrast");
                    check(SkinCatalog.Contrast(skin.Accent,surface) >= 4.5, $"{skin.Name}: data accent contrast");
                }
                check(SkinCatalog.Contrast(skin.LcdInk,skin.LcdBack) >= 4.5, $"{skin.Name}: LCD contrast");
            }
        });
        test("Loot child tables preserve duplicate parent IDs while unique tables reject duplicates", () =>
        {
            byte[] data = NpcDataTests.Pack("EntryId,Enabled,Id\n1,1,-144\n1,1,123\n");
            check(NpcDefinitions.ParseRows(data).Count == 2, "Grouped child rows were lost");
            bool failed = false; try { NpcDefinitions.Parse(data); } catch (InvalidDataException) { failed = true; }
            check(failed, "Unique tables must still reject duplicates");
        });
        test("Loot resolves negative group references and positive item references without fake percentages", () =>
        {
            Fixture(folder =>
            {
                var loot = new LootCatalog(folder); var table = loot.Get(440);
                check(loot.Npcs.Count == 2 && loot.NpcsWithContainer == 1 && table.Items.Count == 3 && table.Rules.Count == 2, "Loot joins or coverage failed");
                check(table.Items.Any(i => i.Name == "Small Limbs") && table.Items.Any(i => i.Name == "Trophy"), "Named loot candidates missing");
                check(table.Rules[0].ChanceRaw == 500 && table.Rules[1].ChanceRaw == -40 && table.ItemsAtOnce == 10, "Raw signed rules must remain raw");
                check(table.Items.Single(i => i.Name == "Trophy").OutputRule.Contains("not proof"), "Special generation must not claim finished items");
            });
        });
        test("Container zero is not treated as a service NPC dropping dummy container contents", () =>
        {
            Fixture(folder => { var loot = new LootCatalog(folder); check(loot.Get(1).Items.Count == 0 && loot.Get(999).Items.Count == 0, "Unknown/no loot is not dummy loot"); });
        });
        test("Offline loot search finds both creature names and desired items", () =>
        {
            Fixture(folder =>
            {
                var loot = new LootCatalog(folder);
                check(loot.Search("spider").Single().TemplateId == 440 && loot.Search("small limbs").Single().TemplateId == 440, "NPC/item reverse lookup failed");
                check(loot.Search("", true).Count == 1 && loot.Search("", false).Count == 2, "Assigned-only filter failed");
            });
        });
        test("BSP extraction retains real geometry, path heights and explicit world-change properties", () =>
        {
            var world = BspEnvironment.Read(Bsp(), 1, "Test", "fixture.bsp");
            check(world.Summary.GroundPoints == 1 && world.Summary.Transitions == 1 && world.StaticGeometry.Triangles.SequenceEqual(new[] {0,1,2}), "BSP data was lost");
            var point = world.Summary.Features.Single(x => x.Kind == "GroundPathPoint");
            check(point.Position == new Vector3(10,20,30) && world.Summary.Features.Single(x => x.Kind == "WorldChange").Properties["NextLevel"] == "2", "3D/path/transition semantics lost");
        });
        test("Corrupt BSP chunk bounds are rejected before entity or geometry allocation", () =>
        {
            byte[] bad = Bsp(); BitConverter.GetBytes(int.MaxValue).CopyTo(bad,4);
            bool failed = false; try { BspEnvironment.Read(bad,1,"Test","fixture"); } catch (InvalidDataException) { failed = true; }
            check(failed, "Corrupt BSP size accepted");
        });
        test("World geometry uses BSP resource mapping while DAT overrides remain spawn data", () =>
        {
            Fixture(folder =>
            {
                string defs=Path.Combine(folder,"definitions"), worlds=Path.Combine(folder,"worlds");Directory.CreateDirectory(worlds);
                File.WriteAllBytes(Path.Combine(defs,"pak_worldinfo.csv"),NpcDataTests.Pack("EntryId,Enabled,Name,DatPathOverride\n1,1,First,./worlds/variant.dat\n2,1,Second,\n"));
                File.WriteAllBytes(Path.Combine(worlds,"pak_worlds.ini"),NpcDataTests.Pack("set 1 \".\\worlds\\base.bsp\";\nset 2 \".\\worlds\\base.bsp\";\n"));
                File.WriteAllBytes(Path.Combine(worlds,"base.bsp"),Bsp());
                var catalog = new EnvironmentCatalog(folder);
                check(catalog.Areas.First(a=>a.WorldId==1).AssetPath=="worlds/base.bsp", "DAT override incorrectly changed geometry file");
                catalog.ScanAll(); check(catalog.Scanned.Count==2 && catalog.WorldRoute(1,2).SequenceEqual(new[]{1,2}), "Authored cross-sector graph failed");
                check(catalog.WorldRoute(2,1).Length==0, "Unconfigured reverse transition was invented");
                foreach(string file in Directory.GetFiles(worlds))File.Delete(file);Directory.Delete(worlds);
            });
        });
    }
    private static byte[] Bsp()
    {
        using var stream=new MemoryStream();using var writer=new BinaryWriter(stream);
        void Chunk(int type,int size,int count,byte[] data){writer.Write(type);writer.Write(size);writer.Write(count);writer.Write(data);}
        byte[] header=new byte[28];Encoding.ASCII.GetBytes("GBSP").CopyTo(header,0);BitConverter.GetBytes(17).CopyTo(header,8);Chunk(0,28,1,header);
        byte[] model=new byte[80];BitConverter.GetBytes(1).CopyTo(model,48);Chunk(1,80,1,model);
        byte[] vertices=new byte[36];BitConverter.GetBytes(1f).CopyTo(vertices,12);BitConverter.GetBytes(1f).CopyTo(vertices,32);Chunk(14,12,3,vertices);
        Chunk(13,4,3,new[]{0,1,2}.SelectMany(BitConverter.GetBytes).ToArray());byte[] face=new byte[36];BitConverter.GetBytes(3).CopyTo(face,4);Chunk(11,36,1,face);
        using var entities=new MemoryStream();using var ew=new BinaryWriter(entities);ew.Write(2);
        void Entity(params (string Key,string Value)[] values)
        {
            ew.Write(values.Length);foreach(var (key,value) in values)foreach(string text in new[]{key,value}){byte[] bytes=Encoding.Latin1.GetBytes(text+'\0');ew.Write(bytes.Length);ew.Write(bytes);}
        }
        Entity(("classname","GroundPathPoint"),("Origin","10 20 30"),("%name%","Point1"));
        Entity(("classname","WorldChange"),("Origin","40 50 60"),("NextLevel","2"),("NextLevelStartIndex","3"));
        Chunk(16,1,(int)entities.Length,entities.ToArray());Chunk(65535,0,0,Array.Empty<byte>());return stream.ToArray();
    }
    private static void Fixture(Action<string> action)
    {
        string folder=Path.Combine(Path.GetTempPath(),"NeocronSharp-expansion-test-"+Guid.NewGuid().ToString("N"));string defs=Path.Combine(folder,"definitions");Directory.CreateDirectory(defs);
        var tables=new Dictionary<string,string>
        {
            ["pak_npcs.csv"]="EntryId,Enabled,Skill,FactionId,ItemContainerId,ModelTargetType,ModelTargetValue\n1,1,120,1,0,1,1\n440,1,1,18,1000,1,440\n",
            ["pak_characters.csv"]="EntryId,Enabled,Name\n1,1,COPBOT\n440,1,Small Spider\n",
            ["pak_items.csv"]="EntryId,Enabled,Name,TechLevel,LootGroupId\n4000,1,Insect Eyes,1,144\n4002,1,Small Limbs,1,144\n9000,1,Trophy,5,999\n",
            ["pak_itemgroups.csv"]="EntryId,Enabled,Name\n144,1,Small Animal Loot\n",
            ["pak_itemcontainers.csv"]="EntryId,Enabled,ItemsAtOnce,RespawnTime\n0,1,1,1000\n1000,1,10,2000\n",
            ["pak_itemcontainerchildren.csv"]="EntryId,Enabled,Id,Quality,Chance\n0,1,9000,0.8,100\n1000,1,-144,0.3,500\n1000,1,9000,-0.5,-40\n"
        };
        try { foreach(var table in tables)File.WriteAllBytes(Path.Combine(defs,table.Key),NpcDataTests.Pack(table.Value));action(folder); }
        finally { foreach(string file in Directory.GetFiles(defs))File.Delete(file);Directory.Delete(defs);if(!Directory.EnumerateFileSystemEntries(folder).Any())Directory.Delete(folder); }
    }
}
