using System.Buffers.Binary;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed partial class PlayerReader
{
    internal CoordinateFix ReadCoordinates()
    {
        var initial = ReadSample();
        var sector = ReadSector(initial.World) ?? throw new InvalidOperationException("The current sector is unavailable. Finish zoning.");
        var sample = ReadSample();
        int finalSector = BinaryPrimitives.ReadInt32LittleEndian(Read(sample.World + 0x258, 4));
        if (sample.World != initial.World || sample.Player != initial.Player || sample.Physics != initial.Physics || finalSector != sector.WorldId)
            throw new InvalidOperationException("The sector changed during sampling. Retrying.");
        return new(DateTimeOffset.UtcNow, Environment.TickCount64, Process.Id, sample.World, sample.Physics, sector.WorldId,
            sector.MapRotationDegrees, sample.Position, sample.Forward);
    }
}
