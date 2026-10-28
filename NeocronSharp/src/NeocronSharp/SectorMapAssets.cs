using NeocronSharp.Core;

namespace NeocronSharp;

internal sealed class SectorMapAssets : IDisposable
{
    internal string Install { get; }
    internal SectorMapCatalog Catalog { get; }
    private readonly GamePakArchive _archive;
    private readonly Dictionary<int, Bitmap> _images = new();
    internal SectorMapAssets(string install)
    { Install = install; Catalog = new(install); _archive = new(Path.Combine(install, "gfx.pak")); }
    internal Bitmap Image(SectorMapDefinition definition)
    {
        if (_images.TryGetValue(definition.BitmapId, out var cached)) return cached;
        byte[] bytes = GameMapFiles.Read(Install, definition.AssetPath, _archive.Read);
        using var stream = new MemoryStream(bytes);
        using var image = System.Drawing.Image.FromStream(stream);
        if (image.Width is < 16 or > 4096 || image.Height is < 16 or > 4096) throw new InvalidDataException("Invalid sector-map image size.");
        var bitmap = new Bitmap(image);
        // These are small map images; bound the cache without ever disposing the
        // current displayed bitmap during painting (all calls occur on UI thread).
        if (_images.Count >= 16)
        {
            var oldest = _images.First(); _images.Remove(oldest.Key); oldest.Value.Dispose();
        }
        _images.Add(definition.BitmapId, bitmap); return bitmap;
    }
    public void Dispose() { foreach (var image in _images.Values) image.Dispose(); _images.Clear(); }
}
