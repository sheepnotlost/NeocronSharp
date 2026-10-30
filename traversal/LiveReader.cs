using System.Buffers.Binary;
using System.Diagnostics;
using System.Numerics;
using NeocronSharp.Core;

namespace NeocronSharp;

/// <summary>
/// One-off read failures: the client caught mid-update (a torn orientation, the player object swapped
/// for a moment, one failed memory read). They pass within a read or two, so a walk retries them for
/// up to <see cref="Window"/> seconds before failing. Zone changes are not among them: those fail
/// with their own messages ("A verified in-world player is unavailable", "physics identity changed",
/// "coordinates are not initialized"), and a real teleport still reads fine and is caught by the
/// walk's own jump and sector checks.
/// </summary>
internal static class ReadTolerance
{
    public const double Window = 1.0;
    private static readonly string[] Transient =
    {
        "Player orientation is not a valid rotation transform",
        "Player changed during telemetry sampling",
        "Client telemetry became unreadable",
        "Invalid player coordinates",
    };

    public static bool IsTransient(Exception e) =>
        e is InvalidOperationException && Transient.Any(m => e.Message.StartsWith(m, StringComparison.Ordinal));

    /// <summary>
    /// <paramref name="read"/>, retried while it fails transiently, for up to <paramref name="window"/>
    /// seconds by <paramref name="seconds"/>; then (or on any other failure) its error stands.
    /// </summary>
    public static T Retry<T>(Func<T> read, Func<double> seconds, Action<int> sleep, double window = Window)
    {
        double first = double.NaN;
        while (true)
        {
            try { return read(); }
            catch (Exception e) when (IsTransient(e))
            {
                double now = seconds();
                if (double.IsNaN(first)) first = now;
                if (now - first >= window) throw;
                sleep(15);
            }
        }
    }
}

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

    /// <summary><see cref="ReadSample"/>, with one-off read failures retried for up to about 1 s (<see cref="ReadTolerance"/>).</summary>
    internal PlayerSample ReadSteady()
    {
        var clock = Stopwatch.StartNew();
        return ReadTolerance.Retry(ReadSample, () => clock.Elapsed.TotalSeconds, Thread.Sleep);
    }

    /// <summary>
    /// The player's position and world without the orientation (which may not read while seated in a
    /// vehicle); the same identity checks as <see cref="ReadSample"/>.
    /// </summary>
    internal (Vector3 Position, ulong World) ReadPosition()
    {
        if (Process.HasExited) throw new InvalidOperationException("The game closed.");
        ulong player = Pointer(_base + 0x6d7db0);
        ulong world = Pointer(_base + 0xd6c330);
        if (player < 0x10000 || world < 0x10000 || Pointer(player) != _base + 0x58f6f8 || Pointer(world) != _base + 0x610be8)
            throw new InvalidOperationException("A verified in-world player is unavailable. Log in and finish zoning.");
        ulong physics = Pointer(world + 0xa8);
        if (physics != player + 0x528 || Pointer(physics) != _base + 0x58f7a0)
            throw new InvalidOperationException("Player physics identity changed. Finish zoning and restart the test.");
        byte[] bytes = Read(physics + 0xd8, 12);
        var position = new Vector3(BitConverter.ToSingle(bytes, 0), BitConverter.ToSingle(bytes, 4), BitConverter.ToSingle(bytes, 8));
        StraightLineRoute.RequireFinite(position);
        if (position == Vector3.Zero) throw new InvalidOperationException("Player coordinates are not initialized.");
        if (Pointer(_base + 0x6d7db0) != player || Pointer(_base + 0xd6c330) != world || Pointer(world + 0xa8) != physics)
            throw new InvalidOperationException("Player changed during telemetry sampling.");
        return (position, world);
    }

    /// <summary>
    /// The class (vtable RVA) of the subway trains in the actor registry. Seen live on 29 Oct 2026 in
    /// world 1000: 11 of them (keys 245-255, as the 11 SubwayTrain spawns), moving along the track.
    /// </summary>
    internal const ulong TrainClass = 0x592c38;

    internal sealed record RegistryActor(int Key, ulong Physics, ulong TableRva, Vector3? Position, Vector3? Forward);

    /// <summary>The subway trains in the current world, by registry key, with their positions (over the track).</summary>
    internal IReadOnlyList<(int Key, Vector3 Position)> ReadTrains() =>
        ReadRegistryActors().Where(a => a.TableRva == TrainClass && a.Position != null).Select(a => (a.Key, a.Position!.Value)).ToList();

    /// <summary>
    /// Read-only: every node of the world's actor registry, whatever its class (EntityReader keeps only
    /// NPCs and characters): its key, class, and position when it has the position getter.
    /// </summary>
    internal IReadOnlyList<RegistryActor> ReadRegistryActors()
    {
        var player = ReadPosition();
        ulong manager = Pointer(player.World + 0x58);
        if (manager < 0x10000 || Pointer(manager) != _base + 0x588418)
            throw new InvalidOperationException("World actors unavailable. Finish logging in or zoning.");
        ulong registry = Pointer(manager + 0x68);
        var header = Read(registry, 12);
        ulong buckets = BinaryPrimitives.ReadUInt64LittleEndian(header);
        int count = BinaryPrimitives.ReadInt32LittleEndian(header.AsSpan(8));
        if (count is < 1 or > 4096 || buckets < 0x10000) throw new InvalidOperationException("Unsupported actor registry.");
        var heads = Read(buckets, count * 8);
        var seen = new HashSet<ulong>();
        var list = new List<RegistryActor>();
        for (int b = 0; b < count; b++)
        {
            ulong node = BinaryPrimitives.ReadUInt64LittleEndian(heads.AsSpan(b * 8));
            int chain = 0;
            while (node >= 0x10000 && ++chain <= 128 && seen.Add(node) && seen.Count <= 8192)
            {
                var data = Read(node, 32);
                if (BinaryPrimitives.ReadUInt64LittleEndian(data) != _base + 0x5b23d0) break;
                int key = BinaryPrimitives.ReadInt32LittleEndian(data.AsSpan(8));
                ulong physics = BinaryPrimitives.ReadUInt64LittleEndian(data.AsSpan(16));
                ulong next = BinaryPrimitives.ReadUInt64LittleEndian(data.AsSpan(24));
                Vector3? at = null, forward = null;
                ulong table = 0;
                if (physics >= 0x10000 && physics % 8 == 0)
                {
                    try
                    {
                        table = Pointer(physics);
                        if (Pointer(table + 0x98) == _base + 0x24bc90)
                        {
                            var xyz = Read(physics + 0xd8, 12);
                            var p = new Vector3(BitConverter.ToSingle(xyz, 0), BitConverter.ToSingle(xyz, 4), BitConverter.ToSingle(xyz, 8));
                            if (float.IsFinite(p.X) && float.IsFinite(p.Y) && float.IsFinite(p.Z) && p != Vector3.Zero) at = p;
                            var m = Read(physics + 0xf0, 48);
                            var f = new float[12];
                            Buffer.BlockCopy(m, 0, f, 0, 48);
                            try { forward = PointNavigation.ForwardFromTransform(f); } catch (InvalidOperationException) { }
                        }
                    }
                    catch (InvalidOperationException) { }
                }
                list.Add(new(key, physics, table >= _base ? table - _base : table, at, forward));
                node = next;
            }
        }
        return list;
    }

    /// <summary>Read-only: raw floats of an actor's physics object, for probing.</summary>
    internal float[] ReadActorFloats(ulong physics, int offset, int count)
    {
        var bytes = Read(physics + (ulong)offset, count * 4);
        var f = new float[count];
        Buffer.BlockCopy(bytes, 0, f, 0, count * 4);
        return f;
    }
}
