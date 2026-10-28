namespace NeocronSharp;

internal sealed class BufferedGrid : DataGridView
{
    internal BufferedGrid() { DoubleBuffered = true; }
}
