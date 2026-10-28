using System.Buffers.Binary;
using System.Numerics;
using System.Text;

namespace NeocronSharp.Core;

/// <summary>Read-only adapter for the fingerprinted x64 Evolution 2.5.902 actor hash table.</summary>
public static class Evolution902Actors
{
    public const int MaxBuckets = 4096, MaxEntries = 8192, MaxChain = 128, MaxNameBytes = 192;
    public sealed record Capture(IReadOnlyList<WorldEntity> Entities, int RegistryEntries);

    public static Capture Read(Func<ulong, int, byte[]> read, ulong module, ulong world, ulong registry, ulong localPhysics)
    {
        static void Pointer(ulong value, int alignment = 8)
        {
            if (value < 0x10000 || value > 0x7fffffffffff || value % (ulong)alignment != 0)
                throw new InvalidOperationException("Actor registry contains an invalid pointer.");
        }
        byte[] Bytes(ulong address, int size)
        {
            var bytes = read(address, size);
            if (bytes.Length != size) throw new InvalidOperationException("Incomplete actor telemetry.");
            return bytes;
        }
        ulong U64(byte[] bytes, int at = 0) => BinaryPrimitives.ReadUInt64LittleEndian(bytes.AsSpan(at, 8));
        Pointer(registry);
        var header = Bytes(registry, 12);
        ulong buckets = U64(header);
        int count = BinaryPrimitives.ReadInt32LittleEndian(header.AsSpan(8));
        if (count is < 1 or > MaxBuckets) throw new InvalidOperationException("Unsupported actor bucket count.");
        Pointer(buckets);
        var heads = Bytes(buckets, count * 8);
        var visited = new HashSet<ulong>();
        var payloads = new HashSet<ulong>();
        var entities = new List<WorldEntity>();
        for (int bucket = 0; bucket < count; bucket++)
        {
            ulong node = U64(heads, bucket * 8);
            int chain = 0;
            while (node != 0)
            {
                Pointer(node);
                if (++chain > MaxChain || !visited.Add(node) || visited.Count > MaxEntries)
                    throw new InvalidOperationException("Actor registry changed or exceeded its traversal limit.");
                var data = Bytes(node, 32);
                if (U64(data) != module + 0x5ade80) throw new InvalidOperationException("Unrecognized actor registry node.");
                int key = BinaryPrimitives.ReadInt32LittleEndian(data.AsSpan(8));
                if (Math.Abs((long)key) % count != bucket) throw new InvalidOperationException("Actor hash chain changed during sampling.");
                ulong physics = U64(data, 16), next = U64(data, 24);
                Pointer(physics);
                ulong table = U64(Bytes(physics, 8));
                EntityKind? kind = table == module + 0x5bfe48 ? EntityKind.Npc :
                    table == module + 0x5bbbb8 ? EntityKind.UnclassifiedCharacter : null;
                if (kind != null && physics != localPhysics)
                {
                    if (!payloads.Add(physics)) throw new InvalidOperationException("Duplicate actor payload in registry.");
                    if (U64(Bytes(table + 0x98, 8)) != module + 0x248270)
                        throw new InvalidOperationException("Actor position getter changed.");
                    var xyz = Bytes(physics + 0xd8, 12);
                    var position = new Vector3(BitConverter.ToSingle(xyz, 0), BitConverter.ToSingle(xyz, 4), BitConverter.ToSingle(xyz, 8));
                    if (!float.IsFinite(position.X) || !float.IsFinite(position.Y) || !float.IsFinite(position.Z) ||
                        Math.Max(Math.Max(Math.Abs(position.X), Math.Abs(position.Y)), Math.Abs(position.Z)) > 1_000_000)
                        throw new InvalidOperationException("Invalid actor coordinates.");
                    bool dormant = kind == EntityKind.UnclassifiedCharacter && position == new Vector3(-32000, -32000, -32000);
                    var player = kind == EntityKind.UnclassifiedCharacter && !dormant ? ReadPlayer(physics, table) : null;
                    if (player != null) kind = EntityKind.Player;
                    string name = kind == EntityKind.Npc ? ReadName(physics + 0x750) : player?.Name ?? "Unnamed character";
                    if (name.Length == 0) name = "Unnamed NPC";
                    string nativeClass = kind == EntityKind.Npc ? "SCRIPTEDPLAYER" : "LSTPLAYER";
                    var stats = kind == EntityKind.Npc ? ReadStats(physics, table) : null;
                    if (!dormant) entities.Add(new(new(world, registry, node, physics, key, kind.Value), name, position, nativeClass, stats, Player: player?.Details));
                    if (U64(Bytes(physics, 8)) != table) throw new InvalidOperationException("Actor changed during sampling.");
                }
                if (!data.SequenceEqual(Bytes(node, 32))) throw new InvalidOperationException("Actor registry mutated during sampling.");
                node = next;
            }
        }
        if (!header.SequenceEqual(Bytes(registry, 12)) || !heads.SequenceEqual(Bytes(buckets, count * 8)))
            throw new InvalidOperationException("Actor registry changed during sampling; retrying.");
        return new(entities, visited.Count);

        (string Name, PlayerDetails Details)? ReadPlayer(ulong physics, ulong table)
        {
            if (U64(Bytes(table + 0x58, 8)) != module + 0x2e7178 || U64(Bytes(table + 0x160, 8)) != module + 0x19d420)
                throw new InvalidOperationException("Network player getters changed.");
            ulong manager = U64(Bytes(physics + 0x608, 8));
            if (manager == 0) return null;
            Pointer(manager);
            var header = Bytes(manager, 0x38);
            if (U64(header) != module + 0x5c5d90 || U64(Bytes(module + 0x5c5d90 + 0x38, 8)) != module + 0x3dfa50 ||
                U64(Bytes(module + 0x5c5d90 + 0x40, 8)) != module + 0x3dfa20)
                throw new InvalidOperationException("Player appearance getters changed.");
            int scalarCount = BinaryPrimitives.ReadUInt16LittleEndian(header.AsSpan(8));
            int blobCount = BinaryPrimitives.ReadUInt16LittleEndian(header.AsSpan(0x18));
            if (scalarCount > 64 || blobCount > 16) throw new InvalidOperationException("Player appearance exceeds read limits.");
            ulong scalarPointer = U64(header, 0x10), blobPointer = U64(header, 0x20);
            if (scalarCount > 0) Pointer(scalarPointer, 4); // The real manager embeds this array at +0x44.
            if (blobCount > 0) Pointer(blobPointer);
            byte[] scalars = scalarCount > 0 ? Bytes(scalarPointer, scalarCount * 16) : Array.Empty<byte>();
            byte[] blobs = blobCount > 0 ? Bytes(blobPointer, blobCount * 16) : Array.Empty<byte>();
            byte[] Blob(int index, int limit)
            {
                if (index >= blobCount) return Array.Empty<byte>();
                ulong ptr = U64(blobs, index * 16);
                int length = BinaryPrimitives.ReadUInt16LittleEndian(blobs.AsSpan(index * 16 + 8));
                if (length == 0) return Array.Empty<byte>();
                if (length > limit) throw new InvalidOperationException("Player appearance field exceeds read limits.");
                Pointer(ptr, 1); return Bytes(ptr, length);
            }
            var text = Blob(1, MaxNameBytes + 1);
            if (text.Length == 0) return null;
            int end = Array.IndexOf(text, (byte)0);
            if (end < 0 || text.AsSpan(0, end).ContainsAnyInRange((byte)0, (byte)31) || text.AsSpan(0, end).Contains((byte)127))
                throw new InvalidOperationException("Invalid player name.");
            string name = Encoding.Latin1.GetString(text, 0, end).Trim();
            if (name.Length == 0) return null;
            var values = new Dictionary<int, float>();
            for (int i = 0; i < scalarCount; i++)
            { float value = BitConverter.ToSingle(scalars, i * 16); if (float.IsFinite(value)) values[i] = value; }
            int? Number(int index, int max = 65535) => values.TryGetValue(index, out float value) && value >= 0 && value <= max ? (int)value : null;
            var gear = new List<PlayerGear>();
            for (int i = 0; i < 3; i++)
            { int? id = Number(10 + i); gear.Add(new($"Visible weapon {i + 1}", id == 65535 ? null : id)); }
            var body = Blob(0, 32);
            int? Word(int offset) => body.Length >= offset + 2 ? BinaryPrimitives.ReadUInt16LittleEndian(body.AsSpan(offset)) : null;
            gear.Add(new("Body appearance model", Word(0)));
            gear.Add(new("Torso appearance model", Word(11) is { } torso && torso != 0 ? torso : null));
            gear.Add(new("Leg appearance model", Word(13) is { } legs && legs != 0 ? legs : null));
            foreach (var selector in new[] { ("Head texture selector",2), ("Torso texture selector",5), ("Leg texture selector",8) })
            { int? id = Word(selector.Item2); gear.Add(new(selector.Item1, id == 65535 ? null : id, id.HasValue && id != 65535 ? "Client appearance selector" : null)); }
            for (int i = 0; i < 4; i++)
            { int? id = Number(13 + i); gear.Add(new($"Appearance attachment {i + 1}", id is > 0 and < 65535 ? id : null)); }
            var clan = Blob(3, 4);
            uint? packed = clan.Length == 4 ? BinaryPrimitives.ReadUInt32LittleEndian(clan) : null;
            int? soul = Number(5, 255) is { } encoded ? encoded - 128 : null;
            int? faction = Number(8); if (faction >= 100) faction = 1; // Same target-display GM-faction convention.
            byte dead = Bytes(physics + 0x218, 1)[0];
            if (U64(Bytes(physics + 0x608, 8)) != manager || !header.SequenceEqual(Bytes(manager, 0x38)) ||
                (blobCount > 0 && !blobs.SequenceEqual(Bytes(blobPointer, blobCount * 16))) || !text.SequenceEqual(Blob(1, MaxNameBytes + 1)))
                throw new InvalidOperationException("Player appearance changed during sampling.");
            return (name, new(Number(6, 255), Number(7, 255), faction, null, soul,
                packed.HasValue ? (int)(packed.Value >> 4) : null, packed.HasValue ? (int)(packed.Value & 15) : null,
                dead <= 1 ? dead == 1 : null, gear, values));
        }

        NpcStats ReadStats(ulong physics, ulong table)
        {
            if (U64(Bytes(table + 0x58, 8)) != module + 0x30fcb0 ||
                U64(Bytes(table + 0x160, 8)) != module + 0x19d420)
                throw new InvalidOperationException("NPC stats getters changed.");
            // Contiguous native fields, including the std::string objects but
            // without dereferencing their pointers a second time.
            var stats = Bytes(physics + 0x738, 0x212);
            int I32(int offset) => BinaryPrimitives.ReadInt32LittleEndian(stats.AsSpan(offset - 0x738, 4));
            ushort U16(int offset) => BinaryPrimitives.ReadUInt16LittleEndian(stats.AsSpan(offset - 0x738, 2));
            float F32(int offset) => BitConverter.ToSingle(stats, offset - 0x738);
            static float? Bounded(float value, float max) => float.IsFinite(value) && value >= 0 && value <= max ? value : null;
            float? rank = Bounded(F32(0x810), 65535);
            int faction = I32(0x73c);
            var health = NpcHealth.FromNative(I32(0x79c), I32(0x7a0));
            byte dead = Bytes(physics + 0x218, 1)[0];
            int function = BinaryPrimitives.ReadInt32LittleEndian(Bytes(physics + 0xad8, 4));
            // Recheck template ownership, not volatile health/animation fields.
            // A legitimate HP update should not blank the entire tracker.
            if (U16(0x790) != BinaryPrimitives.ReadUInt16LittleEndian(Bytes(physics + 0x790, 2)))
                throw new InvalidOperationException("NPC template changed during sampling.");
            return new(U16(0x790), health, rank.HasValue ? (int)Math.Min(rank.Value, 255) : null, rank,
                faction is >= 0 and <= 65535 ? faction : null, U16(0x948), I32(0x740),
                dead <= 1 ? dead == 1 : null, Bounded(F32(0x818), 100000), Bounded(F32(0x820), 100000), function, U16(0x798));
        }

        string ReadName(ulong address)
        {
            // MSVC std::string: 16-byte inline buffer, size +0x10, capacity +0x18.
            var text = Bytes(address, 32);
            ulong length = U64(text, 16), capacity = U64(text, 24);
            if (length > MaxNameBytes || capacity < length || capacity > 4095 || (capacity < 16 && capacity != 15))
                throw new InvalidOperationException("Invalid NPC name string.");
            byte[] value;
            if (capacity == 15) value = text.AsSpan(0, (int)length + 1).ToArray();
            else
            {
                ulong pointer = U64(text);
                if (pointer < 0x10000 || pointer > 0x7fffffffffff) throw new InvalidOperationException("Invalid NPC name pointer.");
                value = Bytes(pointer, (int)length + 1);
            }
            if (value[^1] != 0 || value.AsSpan(0, (int)length).Contains((byte)0) ||
                value.Take((int)length).Any(c => c < 32 && c != 10 && c != 13 && c != 9) || value.Contains((byte)127))
                throw new InvalidOperationException("Unreadable NPC name text.");
            if (!text.SequenceEqual(Bytes(address, 32))) throw new InvalidOperationException("NPC name changed during sampling.");
            return Encoding.Latin1.GetString(value, 0, (int)length).Replace("\\n", " / ").Replace('\n', ' ').Replace('\r', ' ').Replace('\t', ' ').Trim();
        }
    }
}
