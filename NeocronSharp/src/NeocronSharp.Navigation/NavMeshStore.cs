using System.Security.Cryptography;
using System.Text;
using DotRecast.Recast.Toolset;
using NeocronSharp.Core;

namespace NeocronSharp.Navigation;

/// <summary>Navmeshes per world id: kept in memory, cached on disk as
/// <c>world-{id}-{bsp sha256[..16]}-{settings hash[..8]}.navmesh</c>, baked only when neither has one.
/// A changed BSP file or changed build settings gives a new key; older files for that world are removed.</summary>
public sealed class NavMeshStore
{
    private readonly EnvironmentCatalog _catalog;
    private readonly string _cacheDirectory;
    private readonly RcNavMeshBuildSettings _settings;
    private readonly Dictionary<int, NavWorld> _loaded = new();

    /// <summary>Where the last <see cref="Get"/> came from: "memory", "cache" or "bake".</summary>
    public string LastSource { get; private set; } = "";

    public NavMeshStore(EnvironmentCatalog catalog, string cacheDirectory, RcNavMeshBuildSettings? settings = null)
    { _catalog = catalog; _cacheDirectory = cacheDirectory; _settings = settings ?? NavWorld.DefaultSettings(); }

    public string? WorldName(int worldId) => _catalog.Areas.FirstOrDefault(a => a.WorldId == worldId)?.Name;

    public static string CacheFileName(int worldId, string sourceSha256, RcNavMeshBuildSettings settings)
    {
        string settingsHash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(NavWorld.Fingerprint(settings))))[..8];
        return $"world-{worldId}-{sourceSha256[..16]}-{settingsHash}.navmesh".ToLowerInvariant();
    }

    public NavWorld Get(int worldId)
    {
        if (_loaded.TryGetValue(worldId, out var known)) { LastSource = "memory"; return known; }
        var world = _catalog.Load(worldId, out string sha);
        string path = Path.Combine(_cacheDirectory, CacheFileName(worldId, sha, _settings));
        NavWorld? nav = null;
        if (File.Exists(path))
        {
            try { using var stream = File.OpenRead(path); nav = NavWorld.Load(world, stream, _settings); LastSource = "cache"; }
            catch (Exception error) when (error is IOException or InvalidDataException or IndexOutOfRangeException or ArgumentException) { nav = null; }
        }
        if (nav == null)
        {
            nav = NavWorld.Build(world, _settings); LastSource = "bake";
            try
            {
                Directory.CreateDirectory(_cacheDirectory);
                foreach (string stale in Directory.GetFiles(_cacheDirectory, $"world-{worldId}-*.navmesh")) File.Delete(stale);
                string temporary = path + ".tmp";
                using (var stream = File.Create(temporary)) nav.Save(stream);
                File.Move(temporary, path, overwrite: true);
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }   // an unwritable cache only costs a re-bake
        }
        _loaded[worldId] = nav;
        return nav;
    }
}
