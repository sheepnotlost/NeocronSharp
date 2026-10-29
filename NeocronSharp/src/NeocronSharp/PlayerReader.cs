using System.Buffers.Binary;
using System.Diagnostics;
using System.Numerics;
using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;
using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed record PlayerSample(Vector3 Position, ulong Player, ulong World, ulong Physics, Vector3 Forward);

/// <summary>Read-only backend pinned to the inspected Evolution 2.5 client of 28 Oct 2026 (re-mapped from 2.5.902).</summary>
internal sealed partial class PlayerReader : IDisposable
{
    internal const string BuildLabel = "Evolution 2.5 (28 Oct 2026 client)";
    internal const string SupportedSha256 = "60bbdb55031f4cabb916ed46341a6920e150dc4dd6abfaa8ef08a947de4b01c1";
    public Process Process { get; }
    public nint Window { get; }
    public string Executable { get; }
    private readonly SafeProcessHandle _handle;
    private readonly ulong _base;

    public PlayerReader(string expectedExecutable)
    {
        var matches = System.Diagnostics.Process.GetProcessesByName("neocronclient");
        if (matches.Length != 1)
        {
            foreach (var item in matches) item.Dispose();
            throw new InvalidOperationException("Open exactly one Neocron Evolution client and log in first.");
        }
        Process = matches[0];
        try
        {
            Executable = Process.MainModule?.FileName ?? throw new InvalidOperationException("Cannot inspect the game module.");
            // The launcher may start its original install instead of the project copy.
            // Accept either location only when both are the exact inspected build.
            using (var reference = File.OpenRead(expectedExecutable))
                if (Convert.ToHexString(SHA256.HashData(reference)).ToLowerInvariant() != SupportedSha256)
                    throw new InvalidOperationException("The project client was updated. Revalidate its position layout before movement.");
            using var file = File.OpenRead(Executable);
            string hash = Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant();
            if (hash != SupportedSha256)
                throw new InvalidOperationException("Unsupported client build. Position offsets must be revalidated after game updates.");
            _base = (ulong)Process.MainModule!.BaseAddress;
            Window = Process.MainWindowHandle;
            if (Window == 0) throw new InvalidOperationException("The client has no game window.");
            _handle = Native.OpenProcess(0x410, false, Process.Id); // query information + VM read only
            if (_handle.IsInvalid) throw new System.ComponentModel.Win32Exception();
            if (!Read(_base + 0x24bc90, 8).SequenceEqual(new byte[] { 0x48, 0x8d, 0x81, 0xd8, 0, 0, 0, 0xc3 }))
                throw new InvalidOperationException("The live position getter does not match the inspected executable.");
            if (!Read(_base + 0x339540, 8).SequenceEqual(new byte[] { 0x48, 0x8d, 0x81, 0xf0, 0, 0, 0, 0xc3 }))
                throw new InvalidOperationException("The live orientation getter does not match the inspected executable.");
            ReadSample();
        }
        catch { _handle?.Dispose(); Process.Dispose(); throw; }
    }

    private byte[] Read(ulong address, int size)
    {
        var buffer = new byte[size];
        if (!Native.ReadProcessMemory(_handle, (nint)address, buffer, (nuint)size, out var read) || read != (nuint)size)
            throw new InvalidOperationException("Client telemetry became unreadable.");
        return buffer;
    }
    private ulong Pointer(ulong address) => BinaryPrimitives.ReadUInt64LittleEndian(Read(address, 8));
    public PlayerSample ReadSample()
    {
        if (Process.HasExited) throw new InvalidOperationException("The game closed.");
        ulong player = Pointer(_base + 0x6d7db0);
        ulong world = Pointer(_base + 0xd6c330);
        if (player < 0x10000 || world < 0x10000 || Pointer(player) != _base + 0x58f6f8 || Pointer(world) != _base + 0x610be8)
            throw new InvalidOperationException("A verified in-world player is unavailable. Log in and finish zoning.");
        ulong physics = Pointer(world + 0xa8);
        if (physics != player + 0x528 || Pointer(physics) != _base + 0x58f7a0 ||
            Pointer(Pointer(physics) + 0x98) != _base + 0x24bc90 || Pointer(Pointer(physics) + 0x88) != _base + 0x339540)
            throw new InvalidOperationException("Player physics identity changed. Finish zoning and restart the test.");
        byte[] bytes = Read(physics + 0xd8, 12);
        var position = new Vector3(BitConverter.ToSingle(bytes, 0), BitConverter.ToSingle(bytes, 4), BitConverter.ToSingle(bytes, 8));
        StraightLineRoute.RequireFinite(position);
        if (position == Vector3.Zero) throw new InvalidOperationException("Player coordinates are not initialized.");
        byte[] transformBytes = Read(physics + 0xf0, 48);
        var transform = new float[12];
        Buffer.BlockCopy(transformBytes, 0, transform, 0, 48);
        Vector3 forward = PointNavigation.ForwardFromTransform(transform);
        // Reject a torn read if the owning objects changed while the position was sampled.
        if (Pointer(_base + 0x6d7db0) != player || Pointer(_base + 0xd6c330) != world || Pointer(world + 0xa8) != physics)
            throw new InvalidOperationException("Player changed during telemetry sampling.");
        return new(position, player, world, physics, forward);
    }

    public void RequireForeground()
    {
        nint foreground = Native.GetForegroundWindow();
        Native.GetWindowThreadProcessId(foreground, out uint pid);
        if (foreground != Window || pid != Process.Id || !Native.IsWindow(Window) || Native.IsIconic(Window))
            throw new InvalidOperationException("Neocron lost focus. Movement stopped; it will not resume automatically.");
    }

    public void Dispose() { _handle.Dispose(); Process.Dispose(); }
}
