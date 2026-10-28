using System.IO.Compression;
using System.Text;

namespace NeocronSharp.Core;

/// <summary>Bounded read-only access to the local game's PAK; never extracts to the install.</summary>
public sealed class GamePakArchive
{
    private sealed record Entry(long Offset, int CompressedSize, int Size);
    private readonly string _path;
    private readonly Dictionary<string, Entry> _entries = new(StringComparer.OrdinalIgnoreCase);
    public GamePakArchive(string path)
    {
        _path = path;
        using var file = File.OpenRead(path);
        using var reader = new BinaryReader(file, Encoding.Latin1);
        if (reader.ReadUInt32() != 0x3d458cde) throw new InvalidDataException("Unsupported game archive header.");
        uint count = reader.ReadUInt32();
        if (count > 100000) throw new InvalidDataException("Archive entry limit exceeded.");
        long firstPayload = file.Length;
        for (int i = 0; i < count; i++)
        {
            long start = file.Position;
            int recordSize = reader.ReadInt32(); long offset = reader.ReadUInt32();
            int compressed = reader.ReadInt32(), size = reader.ReadInt32(), nameSize = reader.ReadInt32();
            if (nameSize is < 2 or > 1024 || recordSize != nameSize + 20 || compressed <= 0 || size <= 0 ||
                offset < 8 || offset > file.Length - compressed || file.Position + nameSize > firstPayload)
                throw new InvalidDataException("Invalid game archive entry.");
            byte[] name = reader.ReadBytes(nameSize);
            if (name.Length != nameSize || name[^1] != 0 || name.AsSpan(0, nameSize - 1).Contains((byte)0))
                throw new InvalidDataException("Invalid archive asset name.");
            string key = Encoding.Latin1.GetString(name, 0, nameSize - 1).Replace('\\', '/');
            if (!_entries.TryAdd(key, new(offset, compressed, size))) throw new InvalidDataException("Duplicate archive asset.");
            firstPayload = Math.Min(firstPayload, offset);
            if (file.Position != start + recordSize || file.Position > firstPayload || file.Position > 64 * 1024 * 1024)
                throw new InvalidDataException("Archive index overlaps its content.");
        }
    }

    public byte[] Read(string assetName) => ReadEntry(assetName, 16 * 1024 * 1024);
    public byte[] ReadWorld(string assetName) => ReadEntry(assetName, 64 * 1024 * 1024);
    private byte[] ReadEntry(string assetName, int limit)
    {
        string name = assetName.Replace('\\', '/');
        if (name.StartsWith("gfx/", StringComparison.OrdinalIgnoreCase)) name = name[4..];
        if (!_entries.TryGetValue(name, out var entry)) throw new FileNotFoundException($"Asset '{name}' is not in {Path.GetFileName(_path)}.", name);
        if (entry.Size > limit || entry.CompressedSize > limit)
            throw new InvalidDataException("Archive asset exceeds the read limit.");
        using var file = File.OpenRead(_path); file.Position = entry.Offset;
        byte[] compressed = new byte[entry.CompressedSize]; file.ReadExactly(compressed);
        using var input = new MemoryStream(compressed);
        using var zip = new ZLibStream(input, CompressionMode.Decompress);
        byte[] output = new byte[entry.Size]; zip.ReadExactly(output);
        if (zip.ReadByte() != -1) throw new InvalidDataException("Archive asset size does not match its index.");
        return output;
    }
}
