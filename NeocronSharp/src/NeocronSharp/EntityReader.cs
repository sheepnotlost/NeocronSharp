using NeocronSharp.Core;
using System.Buffers.Binary;

namespace NeocronSharp;

internal sealed partial class PlayerReader
{
    private NpcDefinitions? _definitions;
    private PlayerDefinitions? _players;
    public EntitySnapshot ReadEntities()
    {
        _definitions ??= NpcDefinitions.Load(Path.GetDirectoryName(Executable)!);
        _players ??= PlayerDefinitions.Load(Path.GetDirectoryName(Executable)!);
        var player = ReadSample();
        var sector = ReadSector(player.World);
        ulong manager = Pointer(player.World + 0x58);
        if (manager < 0x10000 || Pointer(manager) != _base + 0x588418)
            throw new InvalidOperationException("World actors unavailable. Finish logging in or zoning.");
        ulong registry = Pointer(manager + 0x68);
        var capture = Evolution902Actors.Read(Read, _base, player.World, registry, player.Physics);
        var finalPlayer = ReadSample();
        if (finalPlayer.World != player.World || finalPlayer.Player != player.Player || finalPlayer.Physics != player.Physics ||
            Pointer(player.World + 0x58) != manager || Pointer(manager + 0x68) != registry || ReadSector(player.World) != sector)
            throw new InvalidOperationException("World changed during actor sampling. Retrying.");
        return new(DateTimeOffset.UtcNow, player.World, registry, finalPlayer.Position, finalPlayer.Forward,
            capture.Entities.Select(e => _players.Enrich(_definitions.Enrich(e))).ToArray(), capture.RegistryEntries, sector);
    }

    private SectorTelemetry? ReadSector(ulong world)
    {
        // WORLDCLIENT's +0x30 dispatch subobject returns its +0x234 for
        // message 0x2779 at RVA 0x54c057: complete-object offset +0x264.
        int id = BinaryPrimitives.ReadInt32LittleEndian(Read(world + 0x264, 4));
        if (id is <= 0 or > 65535) return null;
        int? angle = null;
        ulong console = Pointer(world + 0x80);
        if (console >= 0x10000 && Pointer(console) == _base + 0x58b3e8)
        {
            ulong ui = Pointer(console + 0x30);
            if (ui >= 0x10000 && Pointer(ui) == _base + 0x58b468)
            {
                ulong compass = Pointer(ui + 0x148);
                if (compass >= 0x10000 && Pointer(compass) == _base + 0x595c98)
                {
                    int candidate = BinaryPrimitives.ReadInt32LittleEndian(Read(compass + 0x1bc, 4));
                    if (candidate is >= -3600 and <= 3600) angle = candidate;
                }
            }
        }
        return new(id, angle);
    }
}
