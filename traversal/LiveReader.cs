using System.Buffers.Binary;

namespace NeocronSharp;

internal sealed partial class PlayerReader
{
    /// <summary>Current sector (world id), as EntityReader.ReadSector reads it; null while zoning.</summary>
    internal int? ReadSectorId(ulong world)
    {
        // WORLDCLIENT's +0x30 dispatch subobject returns its +0x234 for
        // message 0x2779: complete-object offset +0x264 (28 Oct 2026 client).
        int id = BinaryPrimitives.ReadInt32LittleEndian(Read(world + 0x264, 4));
        return id is <= 0 or > 65535 ? null : id;
    }

    /// <summary>
    /// The sector map's rotation in degrees, from the HUD compass (the same chain as
    /// EntityReader.ReadSector); null until the HUD has loaded. Each sector's map has its
    /// own rotation, so map pixels only become world positions with this value.
    /// </summary>
    internal int? ReadMapRotation(ulong world)
    {
        ulong console = Pointer(world + 0x80);
        if (console < 0x10000 || Pointer(console) != _base + 0x58b3e8) return null;
        ulong ui = Pointer(console + 0x30);
        if (ui < 0x10000 || Pointer(ui) != _base + 0x58b468) return null;
        ulong compass = Pointer(ui + 0x148);
        if (compass < 0x10000 || Pointer(compass) != _base + 0x595c98) return null;
        int value = BinaryPrimitives.ReadInt32LittleEndian(Read(compass + 0x1bc, 4));
        return value is >= -3600 and <= 3600 ? value : null;
    }
}
