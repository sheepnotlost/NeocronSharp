using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using NeocronSharp.Core;

namespace NeocronSharp;

/// <summary>--telemetry [interval_ms]: no window; one JSON object per line on stdout per sample (see TelemetryLine),
/// flushed after every line. Read-only like every other mode: it never writes process memory, sends input or focuses
/// windows. Failed samples become {"ok":false} lines and sampling continues; a closed or restarted client is
/// reconnected about once a second. Exits cleanly when stdin reaches end of input, stdout closes, or on Ctrl+C.</summary>
internal static class TelemetryStream
{
    public const int DefaultIntervalMilliseconds = 100;
    private const int ReconnectMilliseconds = 1000;
    private const int StdInput = -10, StdOutput = -11, AttachParent = -1;
    [DllImport("kernel32.dll")] private static extern nint GetStdHandle(int which);
    [DllImport("kernel32.dll")] private static extern nint GetConsoleWindow();
    [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool AttachConsole(int processId);

    private static bool HasHandle(int which) { nint handle = GetStdHandle(which); return handle != 0 && handle != -1; }

    public static int Run(string[] args)
    {
        int interval = DefaultIntervalMilliseconds;
        int index = Array.IndexOf(args, "--telemetry");
        if (index + 1 < args.Length && !args[index + 1].StartsWith("--", StringComparison.Ordinal))
        {
            if (!int.TryParse(args[index + 1], System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out interval) ||
                interval is < 10 or > 60000)
            {
                if (GetConsoleWindow() == 0) AttachConsole(AttachParent);
                Console.Error.WriteLine("Usage: NeocronSharp.exe --telemetry [interval_ms]   (10..60000, default 100)");
                return 2;
            }
        }

        // This is a WinExe. Keep a redirected stdout as-is; only when there is none, borrow the parent's console.
        // Attaching afterwards lets Ctrl+C in that console reach this process.
        bool hadOutput = HasHandle(StdOutput);
        if (!hadOutput && GetConsoleWindow() == 0) AttachConsole(AttachParent);
        using var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false), 4096) { AutoFlush = false, NewLine = "\n" };
        if (hadOutput && GetConsoleWindow() == 0) AttachConsole(AttachParent);

        using var stop = new ManualResetEventSlim(false);
        ConsoleCancelEventHandler cancel = (_, e) => { e.Cancel = true; stop.Set(); };
        Console.CancelKeyPress += cancel;
        // Watch stdin only when a parent actually gave us one that is not an interactive console.
        if (HasHandle(StdInput) && Console.IsInputRedirected)
            new Thread(() =>
            {
                try
                {
                    using var input = Console.OpenStandardInput();
                    var buffer = new byte[256];
                    while (input.Read(buffer, 0, buffer.Length) > 0) { }
                }
                catch (Exception) { }
                stop.Set();
            }) { IsBackground = true, Name = "Telemetry stdin watch" }.Start();

        PlayerReader? reader = null;
        string connectError = "Not connected yet.";
        var clock = Stopwatch.StartNew();
        long nextConnect = 0, nextSample = 0;
        try
        {
            while (!stop.IsSet)
            {
                string line;
                if (reader == null && clock.ElapsedMilliseconds >= nextConnect)
                {
                    try { reader = new PlayerReader(ProjectPaths.Client); }
                    catch (Exception error) { connectError = error.Message; nextConnect = clock.ElapsedMilliseconds + ReconnectMilliseconds; }
                }
                if (reader != null)
                {
                    try { line = TelemetryLine.Sample(reader.ReadCoordinates()); }
                    catch (Exception error)
                    {
                        line = TelemetryLine.Error(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), error.Message);
                        bool exited; try { exited = reader.Process.HasExited; } catch (Exception) { exited = true; }
                        if (exited) { reader.Dispose(); reader = null; connectError = "The game closed."; nextConnect = clock.ElapsedMilliseconds + ReconnectMilliseconds; }
                    }
                }
                else line = TelemetryLine.Error(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), "Not connected: " + connectError);

                output.WriteLine(line);
                output.Flush();

                // Fixed cadence without bursts after a slow read; while disconnected, one line per reconnect attempt.
                long now = clock.ElapsedMilliseconds;
                nextSample += interval;
                if (nextSample <= now) nextSample = now + interval;
                long wake = reader == null ? Math.Max(nextSample, nextConnect) : nextSample;
                if (wake > now) stop.Wait((int)Math.Min(wake - now, int.MaxValue));
            }
        }
        catch (IOException) { }            // stdout closed by the reader: nothing left to report to
        catch (ObjectDisposedException) { }
        finally
        {
            Console.CancelKeyPress -= cancel;
            reader?.Dispose();
        }
        return 0;
    }
}
