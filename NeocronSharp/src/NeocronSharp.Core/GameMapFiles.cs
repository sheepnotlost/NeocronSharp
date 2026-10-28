namespace NeocronSharp.Core;

public static class GameMapFiles
{
    public static byte[] Read(string install, string asset, Func<string, byte[]> fromArchive)
    {
        string root = Path.GetFullPath(install).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string file = Path.GetFullPath(Path.Combine(root, asset.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar)));
        if (!file.StartsWith(root, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Map asset escapes the installation directory.");
        string packed = Path.Combine(Path.GetDirectoryName(file)!, "pak_" + Path.GetFileName(file));
        string? local = File.Exists(packed) ? packed : File.Exists(file) ? file : null;
        byte[] bytes;
        if (local == null) bytes = fromArchive(asset);
        else
        {
            if (new FileInfo(local).Length > 16 * 1024 * 1024) throw new InvalidDataException("Local map asset exceeds the read limit.");
            byte[] data = File.ReadAllBytes(local);
            bytes = data.Length > 2 && data[0] == 'B' && data[1] == 'M' ? data : NpcDefinitions.DecodeBytes(data);
        }
        if (bytes.Length < 26 || bytes.Length > 16 * 1024 * 1024 || bytes[0] != 'B' || bytes[1] != 'M')
            throw new InvalidDataException("The map asset is not a supported bitmap.");
        return bytes;
    }
}
