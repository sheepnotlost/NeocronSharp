using System.Numerics;
using NeocronSharp.Core;

internal static class PlayerTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        void Reject(Action action)
        {
            try { action(); } catch (InvalidOperationException) { return; }
            throw new Exception("Invalid player data was accepted");
        }
        test("Network players expose real names, rank pairs and visible gear without invented NPC HP", () =>
        {
            var memory = new ActorTests.MemoryFixture(); memory.AddPlayer(1, "Ryker Ekisrai"); memory.AddPlayer(2, "Long Player Name With Accents é");
            var actors = memory.Capture().Entities;
            check(actors.Count == 2 && actors.All(e => e.Identity.Kind == EntityKind.Player && e.Stats == null), "Players must not acquire NPC stats");
            var player = actors.First(e => e.Name == "Ryker Ekisrai").Player!;
            check(player.RankText == "64 / 60" && player.FactionId == 4 && player.SoulLight == 100 && player.ClanId == 2000 && player.ClanRank == 3, "Target-display data decoded incorrectly");
            check(player.Gear[0].DefinitionId == 448 && player.Gear[1].DefinitionId == null && player.Gear[2].DefinitionId == 3635 && player.Gear[3].DefinitionId == 110,
                "Appearance model and weapon namespaces must remain separate");
            check(actors.Any(e => e.Name.EndsWith('é')), "Player names must preserve the client encoding");
        });
        test("Uninitialized network characters remain unknown and do not become fictional players", () =>
        {
            var memory = new ActorTests.MemoryFixture(); memory.Add(1, null);
            check(memory.Capture().Entities.Single().Identity.Kind == EntityKind.UnclassifiedCharacter, "Missing player identity must stay unclassified");
        });
        test("Packed native appearance scalar arrays accept four-byte alignment", () =>
        {
            var memory = new ActorTests.MemoryFixture(); memory.AddPlayer(1, "Player");
            ulong old = memory.Appearance(1) + 0x100;
            byte[] values = memory.Read(old, 19 * 16); memory.Put(old + 4, values); memory.Q(memory.Appearance(1) + 0x10, old + 4);
            check(memory.Capture().Entities.Single().Player!.RankText == "64 / 60", "The native inline scalar array must not require pointer alignment");
        });
        test("Dormant off-map network placeholders are removed from the live list", () =>
        {
            var memory = new ActorTests.MemoryFixture(); memory.AddPlayer(1, "Player");
            foreach (ulong offset in new ulong[] { 0xd8,0xdc,0xe0 }) memory.Put(memory.Physics(1)+offset, BitConverter.GetBytes(-32000f));
            check(memory.Capture().Entities.Count == 0, "Dormant network records must not remain as players across the map");
        });
        test("Player appearance bounds and unterminated names reject corrupt snapshots", () =>
        {
            var large = new ActorTests.MemoryFixture(); large.AddPlayer(1, "Player"); large.Put(large.Appearance(1)+8, BitConverter.GetBytes((ushort)1000)); Reject(()=>large.Capture());
            var name = new ActorTests.MemoryFixture(); name.AddPlayer(1, "Player"); name.Put(name.Appearance(1)+0x506,new byte[]{65}); Reject(()=>name.Capture());
            var blob = new ActorTests.MemoryFixture(); blob.AddPlayer(1,"Player"); blob.Put(blob.Appearance(1)+0x318,BitConverter.GetBytes((ushort)1000)); Reject(()=>blob.Capture());
        });
        test("Player identity mutation is rejected rather than attaching gear to a new owner", () =>
        {
            var memory = new ActorTests.MemoryFixture(); memory.AddPlayer(1,"Player"); bool changed=false;
            Reject(()=>Evolution902Actors.Read((address,size)=>
            {
                var bytes=memory.Read(address,size);
                if(address==memory.Appearance(1)+0x500 && !changed) {memory.Q(memory.Physics(1)+0x608,0);changed=true;}
                return bytes;
            },ActorTests.MemoryFixture.Module,0x11000,ActorTests.MemoryFixture.Registry,0));
        });
        test("Players populate by default and leave tracking when unloaded or when the sector changes", () =>
        {
            var memory=new ActorTests.MemoryFixture();memory.AddPlayer(1,"Player");memory.Add(2,"COPBOT");memory.Add(3,null);
            var entities=memory.Capture().Entities;
            var snapshot=new EntitySnapshot(DateTimeOffset.UtcNow,0x11000,ActorTests.MemoryFixture.Registry,Vector3.Zero,-Vector3.UnitZ,entities,3,new(1,270));
            check(EntityQuery.Nearby(snapshot).Count==2 && EntityQuery.Nearby(snapshot,"player").Single().Entity.Player!=null,"Verified players must be included without the unknown-actor toggle");
            var tracking=new EntityTracking();tracking.Update(snapshot);tracking.Track(entities.First(e=>e.Player!=null));
            tracking.Update(snapshot with {Entities=entities.Where(e=>e.Player==null).ToArray()});
            check(tracking.Lost && tracking.Disappeared==1,"A missing player must unload automatically");
            tracking.Update(snapshot);check(tracking.Lost,"Returning addresses must not silently rebind inspection");
            tracking.Track(entities.First(e=>e.Player!=null));tracking.Update(snapshot with{Sector=new(2,270)});
            check(tracking.Lost && tracking.Appeared==0,"Zone changes must invalidate old player selection");
        });
        test("Player gear joins weapon definitions and only the PLAYER model-resource namespace", () =>
        {
            string root=Path.Combine(Path.GetTempPath(),"NeocronSharp-player-test-"+Guid.NewGuid().ToString("N"));
            string defs=Path.Combine(root,"definitions"),models=Path.Combine(root,"models");Directory.CreateDirectory(defs);Directory.CreateDirectory(models);
            try
            {
                File.WriteAllBytes(Path.Combine(defs,"pak_weapons.csv"),NpcDataTests.Pack("EntryId,Enabled,Name,Level,Range,ClipSize,ShotCount\n448,1,STEINER FP 1.0,102,500,20,4\n"));
                File.WriteAllBytes(Path.Combine(defs,"pak_factions.csv"),NpcDataTests.Pack("EntryId,Enabled,Name\n4,1,Test faction\n"));
                File.WriteAllBytes(Path.Combine(models,"pak_models.ini"),NpcDataTests.Pack("[STATIC]\nset 110 \"./models/TreeTrunk.act\";\n[PLAYER]\nset 110 \"./models/SpyArmor_Gold.act\";\n"));
                var memory=new ActorTests.MemoryFixture();memory.AddPlayer(1,"Player");var entity=memory.Capture().Entities.Single();
                var enriched=PlayerDefinitions.Load(root).Enrich(entity);var gear=enriched.Player!.Gear;
                check(gear[0].Name=="STEINER FP 1.0" && gear[0].TechLevel==102 && gear[0].MagazineSize==20 && gear[0].ShotsPerBurst==4,"Published weapons must resolve base stats");
                check(gear[3].Name=="SpyArmor Gold" && !gear[3].Asset!.Contains("TreeTrunk") && enriched.Player.FactionName=="Test faction","Appearance namespace join is incorrect");
                check(enriched.Stats==null && enriched.Player.AppearanceValues==entity.Player!.AppearanceValues,"Reference data must not invent or overwrite native telemetry");
            }
            finally { foreach(string file in Directory.GetFiles(defs))File.Delete(file);foreach(string file in Directory.GetFiles(models))File.Delete(file);Directory.Delete(defs);Directory.Delete(models);Directory.Delete(root); }
        });
        test("Missing optional player definitions preserve native names and gear IDs", () =>
        {
            var memory=new ActorTests.MemoryFixture();memory.AddPlayer(1,"Player");var entity=memory.Capture().Entities.Single();
            var result=PlayerDefinitions.Load(Path.Combine(Path.GetTempPath(),Guid.NewGuid().ToString("N"))).Enrich(entity);
            check(result.Name=="Player" && result.Player!.Gear[0].DefinitionId==448 && result.Player.Gear[0].Name==null,"Unresolved gear should retain its native ID without breaking the player list");
        });
    }
}
