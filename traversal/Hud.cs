using System.Diagnostics;
using System.IO.Pipes;
using System.Text;

namespace NavmeshPrototype;

/// <summary>
/// Route panel drawn in-game by the NeocronHook overlay (\\.\pipe\NeocronHook).
/// Purely cosmetic: if the overlay is not loaded, or the pipe misbehaves, every
/// call quietly does nothing and steering carries on unaffected.
/// </summary>
internal sealed class Hud : IDisposable
{
    // Clear of the game's top-left Location/Compass panel.
    private const int X = 300, Y = 28, Width = 620, LineHeight = 20;
    private const string Background = "b0101418";
    private NamedPipeClientStream? _pipe;
    private StreamReader? _replies;
    private readonly Stopwatch _sinceFailure = new();
    private readonly Stopwatch _sinceUpdate = Stopwatch.StartNew();
    private int _lines;

    public bool Connected => _pipe?.IsConnected == true;
    public string? LastError { get; private set; }

    private bool Ensure()
    {
        if (Connected) return true;
        // A missing overlay must cost the steering loop nothing: try rarely, and only briefly.
        if (_sinceFailure.IsRunning && _sinceFailure.ElapsedMilliseconds < 5000) return false;
        try
        {
            Drop();
            _pipe = new NamedPipeClientStream(".", "NeocronHook", PipeDirection.InOut, PipeOptions.Asynchronous);
            _pipe.Connect(30);
            _replies = new StreamReader(_pipe, new UTF8Encoding(false), false, 256, leaveOpen: true);
            _sinceFailure.Reset();
            return true;
        }
        catch (Exception e) when (e is IOException or TimeoutException or UnauthorizedAccessException)
        {
            LastError = $"connect: {e.GetType().Name}: {e.Message}";
            Drop(); _sinceFailure.Restart(); return false;
        }
    }

    private void Send(string line)
    {
        if (!Ensure()) return;
        try
        {
            var bytes = Encoding.UTF8.GetBytes(line.Replace('\n', ' ') + "\n");
            // Never let a stuck overlay stall steering (W may be held): cap each exchange.
            using var timeout = new CancellationTokenSource(250);
            _pipe!.WriteAsync(bytes, timeout.Token).AsTask().GetAwaiter().GetResult();
            if (_replies!.ReadLineAsync(timeout.Token).AsTask().GetAwaiter().GetResult() == null) throw new IOException("Overlay closed the pipe.");
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException or InvalidOperationException or OperationCanceledException)
        {
            LastError = $"send: {e.GetType().Name}: {e.Message}";
            Drop(); _sinceFailure.Restart();
        }
    }

    /// <summary>Live progress: throttled to 5 Hz so the steering loop is never slowed.</summary>
    public void Show(string color, string title, params string[] lines)
    {
        if (_sinceUpdate.ElapsedMilliseconds < 200) return;
        Post(color, title, lines);
    }

    /// <summary>Draw now (state changes and final messages).</summary>
    public void Post(string color, string title, params string[] lines)
    {
        _sinceUpdate.Restart();
        Send($"BOX nav_bg {X} {Y} {Width} {8 + LineHeight * (lines.Length + 1)} {Background}");
        Send($"TEXT nav_0 {X + 8} {Y + 3} {color} {title}");
        for (int i = 0; i < lines.Length; i++) Send($"TEXT nav_{i + 1} {X + 8} {Y + 3 + LineHeight * (i + 1)} ffd8e8e0 {lines[i]}");
        for (int i = lines.Length; i < _lines; i++) Send($"DEL nav_{i + 1}");
        _lines = lines.Length;
    }

    public const string Green = "ff60ff9a", Amber = "ffffc040", Red = "ffff6060", Cyan = "ff7fd0ff";

    private void Drop()
    {
        try { _replies?.Dispose(); } catch (IOException) { }
        try { _pipe?.Dispose(); } catch (IOException) { }
        _replies = null; _pipe = null;
    }

    public void Dispose() => Drop();
}
