using System.Buffers.Binary;
using System.Numerics;
using System.Text;
using NeocronSharp.Core;

internal static class ActorTests
{
    public static void Run(Action<string, Action> test, Action<bool, string> check)
    {
        void Reject(Action action)
        {
            try { action(); } catch (InvalidOperationException) { return; }
            throw new Exception("Invalid actor telemetry was accepted");
        }
        WorldEntity Entity(int key, ulong address, string name = "COPBOT", EntityKind kind = EntityKind.Npc) =>
            new(new(0x11000, 0x12000, address + 0x1000, address, key, kind), name, new(3, 12, -4), "test");
        EntitySnapshot Snapshot(params WorldEntity[] entities) => new(DateTimeOffset.UtcNow, 0x11000, 0x12000, Vector3.Zero, -Vector3.UnitZ, entities, entities.Length);
        test("NPC filtering uses real names, range and nearest-first 3D distance", () =>
        {
            var near = Entity(1, 0x20000);
            var far = Entity(2, 0x30000, "copbot patrol") with { Position = new(100, 0, 0) };
            var unknown = Entity(3, 0x40000, "COPBOT", EntityKind.UnclassifiedCharacter);
            var snapshot = Snapshot(far, unknown, near);
            var rows = EntityQuery.Nearby(snapshot, " cOpBoT ", 50);
            check(rows.Count == 1 && rows[0].Entity == near && rows[0].Distance == 13 && rows[0].GroundDistance == 5, "Filter or distance mismatch");
            check(EntityQuery.Nearby(snapshot, "copbot", includeUnclassified: true).Count == 3, "Unknown characters need an explicit filter");
            check(EntityQuery.Nearby(snapshot, "spider").Count == 0, "Empty search result must remain empty");
        });
        test("Actor bearing follows the player's heading and separates height", () =>
        {
            var right = EntityQuery.Describe(Entity(1, 0x20000) with { Position = new(10, 20, 0) }, Vector3.Zero, -Vector3.UnitZ);
            check(Math.Abs(right.Bearing - 90) < 0.01 && right.Height == 20, "East is right when facing negative Z");
            var left = EntityQuery.Describe(Entity(1, 0x20000) with { Position = new(0, 0, -10) }, Vector3.Zero, Vector3.UnitX);
            check(Math.Abs(left.Bearing + 90) < 0.01, "Negative Z is left when facing positive X");
        });
        test("Tracking follows a concrete instance, not a reused key or identical name", () =>
        {
            var tracking = new EntityTracking(); var first = Entity(1, 0x20000); var other = Entity(1, 0x30000);
            tracking.Update(Snapshot(first, other)); tracking.Track(first);
            var moved = first with { Position = new(50, 0, 0) };
            tracking.Update(Snapshot(moved, other)); check(tracking.Tracked == moved && !tracking.Lost, "Live instance must update");
            tracking.Update(Snapshot(other)); check(tracking.Lost && tracking.Disappeared == 1, "Duplicate key must not steal selection");
            tracking.Update(Snapshot(first, other)); check(tracking.Lost, "Reappearing addresses must require a new selection");
        });
        test("Zoning and unavailable data invalidate selection and reset change counts", () =>
        {
            var tracking = new EntityTracking(); var first = Entity(1, 0x20000);
            tracking.Update(Snapshot(first)); tracking.Track(first); tracking.Unavailable();
            tracking.Update(Snapshot(first)); check(tracking.Lost && tracking.Appeared == 0, "Reconnect must not resurrect tracking");
            tracking.Track(first); tracking.Update(Snapshot(first) with { Registry = 0x99000 });
            check(tracking.Lost && tracking.Appeared == 0, "New zone must reset the baseline");
        });
        test("Native adapter reads inline and heap NPC names and excludes local physics", () =>
        {
            var fixture = new MemoryFixture(); fixture.Add(1, "COPBOT"); fixture.Add(2, "NEMA Papergirl - Mia Coleman");
            fixture.Add(3, "Local NPC-shaped test record");
            var result = fixture.Capture(fixture.Physics(3));
            check(result.RegistryEntries == 3 && result.Entities.Count == 2, "Local payload must be excluded");
            check(result.Entities.Any(e => e.Name == "COPBOT") && result.Entities.Any(e => e.Name == "NEMA Papergirl - Mia Coleman"), "Both std::string layouts must decode");
        });
        test("Hash keys can collide across actor types without merging entities", () =>
        {
            var fixture = new MemoryFixture(); fixture.Add(1, "COPBOT"); fixture.Add(1, null);
            var result = fixture.Capture();
            check(result.Entities.Count == 2 && result.Entities.Select(e => e.Identity).Distinct().Count() == 2, "Keep actor instances separate");
            check(result.Entities.Count(e => e.Identity.Kind == EntityKind.UnclassifiedCharacter) == 1, "Do not invent a player/NPC classification");
        });
        test("Empty actor registry is a valid empty snapshot", () => check(new MemoryFixture().Capture().Entities.Count == 0, "Empty is not an error"));
        test("Registry cycles and misplaced hash entries are rejected", () =>
        {
            var cycle = new MemoryFixture(); cycle.Add(1, "COPBOT"); cycle.Q(cycle.Node(1) + 24, cycle.Node(1)); Reject(() => cycle.Capture());
            var wrong = new MemoryFixture(); wrong.Add(1, "COPBOT"); wrong.I(wrong.Node(1) + 8, 2); Reject(() => wrong.Capture());
        });
        test("Unknown object classes are skipped without guessing NPC fields", () =>
        {
            var fixture = new MemoryFixture(); fixture.Add(1, "COPBOT"); fixture.Q(fixture.Physics(1), MemoryFixture.Module + 0x1234);
            check(fixture.Capture().Entities.Count == 0, "Unsupported classes must not use scripted NPC offsets");
        });
        test("Name read limits and corrupt position data reject the snapshot", () =>
        {
            var large = new MemoryFixture(); large.Add(1, "COPBOT"); large.Q(large.Physics(1) + 0x760, 1000000); Reject(() => large.Capture());
            var badPosition = new MemoryFixture(); badPosition.Add(1, "COPBOT"); badPosition.Put(badPosition.Physics(1) + 0xd8, BitConverter.GetBytes(float.NaN)); Reject(() => badPosition.Capture());
            var unterminated = new MemoryFixture(); unterminated.Add(1, "COPBOT"); unterminated.Put(unterminated.Physics(1) + 0x756, new byte[] { 65 }); Reject(() => unterminated.Capture());
        });
        test("Registry bucket and chain caps bound corrupt reads", () =>
        {
            var large = new MemoryFixture(); large.I(MemoryFixture.Registry + 8, int.MaxValue); Reject(() => large.Capture());
            var chain = new MemoryFixture(); for (int i = 0; i < Evolution902Actors.MaxChain + 1; i++) chain.Add(1, null);
            Reject(() => chain.Capture());
        });
        test("Registry mutation during a read never publishes a partial snapshot", () =>
        {
            var fixture = new MemoryFixture(); fixture.Add(1, "COPBOT"); bool changed = false;
            Reject(() => Evolution902Actors.Read((address, size) =>
            {
                byte[] data = fixture.Read(address, size);
                if (address == fixture.Physics(1) && !changed) { fixture.Q(fixture.Node(1) + 16, 0x55550); changed = true; }
                return data;
            }, MemoryFixture.Module, 0x11000, MemoryFixture.Registry, 0));
        });
        test("Short native reads fail without retaining previous telemetry", () =>
        {
            var fixture = new MemoryFixture(); fixture.Add(1, "COPBOT");
            Reject(() => Evolution902Actors.Read((a, s) => fixture.Read(a, s)[..^1], MemoryFixture.Module, 0x11000, MemoryFixture.Registry, 0));
        });
        test("Native NPC stats expose HP, rank, faction and equipment without filling unknown character stats", () =>
        {
            var fixture = new MemoryFixture(); fixture.Add(1, "COPBOT"); fixture.Add(2, null);
            var entities = fixture.Capture().Entities;
            var stats = entities.Single(e => e.Name == "COPBOT").Stats!;
            check(stats.TemplateId == 1 && stats.Rank == 120 && stats.FactionId == 1 && stats.WeaponId == 1651 && stats.ArmorId == 1 && stats.Dead == false, "NPC stat layout mismatch");
            check(stats.Health!.Current == 15168 && stats.Health.RawCurrent == 16065 && stats.Health.WasClamped, "Client over-max HP must be preserved and bounded for display");
            check(entities.Single(e => e.Identity.Kind == EntityKind.UnclassifiedCharacter).Stats == null, "Unknown character types must not acquire NPC stats");
        });
        test("Invalid optional stats become unavailable without destroying valid position data", () =>
        {
            var fixture = new MemoryFixture(); fixture.Add(1, "COPBOT"); ulong actor = fixture.Physics(1);
            fixture.I(actor + 0x7a0, 0); fixture.Put(actor + 0x810, BitConverter.GetBytes(float.NaN)); fixture.I(actor + 0x73c, -1); fixture.Put(actor + 0x218, new byte[] { 9 });
            var entity = fixture.Capture().Entities.Single();
            check(entity.Stats!.Health == null && entity.Stats.Rank == null && entity.Stats.FactionId == null && entity.Stats.Dead == null, "Invalid readings must remain unknown");
            check(entity.Position == new Vector3(10, 20, 30), "Optional stats must not blank good coordinates");
        });
        test("HUD rank caps at 255 while retaining the native rank for export", () =>
        {
            var fixture = new MemoryFixture(); fixture.Add(1, "COPBOT"); fixture.Put(fixture.Physics(1) + 0x810, BitConverter.GetBytes(300f));
            var stats = fixture.Capture().Entities.Single().Stats!;
            check(stats.Rank == 255 && stats.RawRank == 300, "HUD rank cap mismatch");
        });
    }

    internal sealed class MemoryFixture
    {
        public const ulong Module = 0x140000000, Registry = 0x20000, Buckets = 0x30000;
        private readonly Dictionary<ulong, byte> _bytes = new();
        private int _count;
        public MemoryFixture()
        {
            Put(Registry, new byte[12]); Q(Registry, Buckets); I(Registry + 8, 4); Put(Buckets, new byte[32]);
            Q(Module + 0x5bfe48 + 0x98, Module + 0x248270); Q(Module + 0x5bbbb8 + 0x98, Module + 0x248270);
            Q(Module + 0x5bfe48 + 0x58, Module + 0x30fcb0); Q(Module + 0x5bfe48 + 0x160, Module + 0x19d420);
            Q(Module + 0x5bbbb8 + 0x58, Module + 0x2e7178); Q(Module + 0x5bbbb8 + 0x160, Module + 0x19d420);
        }
        public ulong Node(int index) => 0x40000UL + (ulong)index * 0x100;
        public ulong Physics(int index) => 0x100000UL + (ulong)index * 0x1000;
        public void Add(int key, string? name)
        {
            int index = ++_count; ulong node = Node(index), actor = Physics(index), bucket = Buckets + (ulong)(Math.Abs((long)key) % 4) * 8;
            Put(node, new byte[32]); Q(node, Module + 0x5ade80); I(node + 8, key); Q(node + 16, actor); Q(node + 24, BinaryPrimitives.ReadUInt64LittleEndian(Read(bucket, 8))); Q(bucket, node);
            Q(actor, Module + (name == null ? 0x5bbbb8UL : 0x5bfe48UL));
            Put(actor + 0xd8, BitConverter.GetBytes(10f).Concat(BitConverter.GetBytes(20f)).Concat(BitConverter.GetBytes(30f)).ToArray());
            if (name == null) { Q(actor + 0x608, 0); return; }
            Put(actor + 0x738, new byte[0x212]); I(actor + 0x73c, 1); I(actor + 0x740, 1);
            Put(actor + 0x790, BitConverter.GetBytes((ushort)1)); I(actor + 0x79c, 16065); I(actor + 0x7a0, 15168);
            Put(actor + 0x810, BitConverter.GetBytes(120f)); Put(actor + 0x818, BitConverter.GetBytes(1.5f)); Put(actor + 0x820, BitConverter.GetBytes(15f));
            Put(actor + 0x948, BitConverter.GetBytes((ushort)1651)); Put(actor + 0x218, new byte[] { 0 }); I(actor + 0xad8, 0);
            byte[] text = Encoding.Latin1.GetBytes(name + '\0'); Put(actor + 0x750, new byte[32]);
            if (text.Length <= 16) { Put(actor + 0x750, text); Q(actor + 0x768, 15); }
            else { ulong heap = 0x500000UL + (ulong)index * 0x100; Q(actor + 0x750, heap); Put(heap, text); Q(actor + 0x768, 63); }
            Q(actor + 0x760, (ulong)text.Length - 1);
        }
        public ulong Appearance(int index) => 0x800000UL + (ulong)index * 0x1000;
        public void AddPlayer(int key, string name)
        {
            int index = _count + 1; Add(key, null); ulong actor = Physics(index), app = Appearance(index);
            ulong scalars = app + 0x100, blobs = app + 0x300, text = app + 0x500, body = app + 0x600, clan = app + 0x700;
            Q(actor + 0x608, app); Put(actor + 0x218, new byte[] { 0 }); Put(app, new byte[0x38]); Q(app, Module + 0x5c5d90);
            Put(app + 8, BitConverter.GetBytes((ushort)19)); Q(app + 0x10, scalars);
            Put(app + 0x18, BitConverter.GetBytes((ushort)4)); Q(app + 0x20, blobs);
            Q(Module + 0x5c5d90 + 0x38, Module + 0x3dfa50); Q(Module + 0x5c5d90 + 0x40, Module + 0x3dfa20);
            Put(scalars, new byte[19*16]); Put(blobs, new byte[4*16]);
            foreach (var value in new[] { (5,228f), (6,64f), (7,60f), (8,4f), (10,448f), (11,65535f), (12,3635f), (13,1024f) })
                Put(scalars + (ulong)value.Item1*16, BitConverter.GetBytes(value.Item2));
            byte[] nameBytes = Encoding.Latin1.GetBytes(name+'\0'); Put(text, nameBytes); Q(blobs + 16, text); Put(blobs + 24, BitConverter.GetBytes((ushort)nameBytes.Length));
            Put(body, new byte[15]); Put(body, BitConverter.GetBytes((ushort)110)); Q(blobs, body); Put(blobs+8, BitConverter.GetBytes((ushort)15));
            Put(clan, BitConverter.GetBytes((uint)((2000<<4)|3))); Q(blobs+48, clan); Put(blobs+56, BitConverter.GetBytes((ushort)4));
        }
        public void Put(ulong address, byte[] bytes) { for (int i = 0; i < bytes.Length; i++) _bytes[address + (ulong)i] = bytes[i]; }
        public void Q(ulong address, ulong value) => Put(address, BitConverter.GetBytes(value));
        public void I(ulong address, int value) => Put(address, BitConverter.GetBytes(value));
        public byte[] Read(ulong address, int size) => Enumerable.Range(0, size).Select(i => _bytes.TryGetValue(address + (ulong)i, out var value) ? value : throw new InvalidOperationException("Unreadable fixture memory")).ToArray();
        public Evolution902Actors.Capture Capture(ulong local = 0) => Evolution902Actors.Read(Read, Module, 0x11000, Registry, local);
    }
}
