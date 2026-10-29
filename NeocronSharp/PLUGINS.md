# Using plugins

Open NeocronSharp and select **Plugins**. The plugins that come with NeocronSharp
(the In-game NPC counter and the example) are enabled on a fresh download: their
`plugin.json` says `"enabledByDefault": true`. Any plugin you add yourself starts
disabled. Your own Enable/Disable choice always wins over the default. To try the
example, select it, adjust its greeting if desired, choose **Save settings**,
then **Enable**. The plugin starts and writes a message in the recent log. Use
**Disable** to stop it. Settings saved while a plugin is running apply when it
next starts, so disable and enable it again to apply changes. Enabled choices
persist when NeocronSharp closes and are started when the main window opens.

## In-game NPC counter

The **In-game NPC counter** plugin shows the count of NPCs currently loaded by
the client. It appears under the compass while the game is focused and live tracker data is available;
it hides when you switch away, pause the tracker, zone, minimize, or lose data.
The panel is click-through and does not send game input. Keep NeocronSharp open
while using it. The panel is an external Windows overlay, not a native Neocron
UI element, and exclusive fullscreen may prevent it from appearing. Use
windowed or borderless mode if needed.

In the Plugins tab, select the counter to enable/disable it. Its JSON settings
are `offsetX` (distance from the left, in pixels), `offsetY`
(distance from the top), and `opacity` (0.35 to 1). Save and restart the plugin
to apply changes. The default position is X 62, Y 270, below the compass in the
provided screenshot; adjust it if the game HUD uses a different scale. The
count covers loaded NPCs, not everyone in the zone.

Plugins execute C# code inside NeocronSharp with the same permissions as the
app. Install only plugins you trust. Disabled plugins are listed from their
manifest without executing their DLL.

## Adding a plugin

Create a folder in `NeocronSharp/plugins` containing `plugin.json`, the
plugin's .NET 9 DLL, and any private DLL dependencies. Select **Refresh list**
to discover it. Newly discovered IDs start disabled. The manifest format is:

```json
{
  "id": "author.myplugin",
  "name": "My plugin",
  "version": "1.0.0",
  "description": "What this plugin does",
  "assembly": "MyPlugin.dll",
  "type": "MyPlugin.MainPlugin"
}
```

The ID must be unique and use letters, numbers, periods, underscores or
hyphens. The assembly value is a filename in the plugin folder. The type must
be public, have a public parameterless constructor and implement
`NeocronSharp.Core.INeocronPlugin`. Reference `NeocronSharp.Core` when building;
the host supplies the contract at runtime. See `examples/HelloPlugin` for a
complete project and manifest. Build it with:

```
dotnet build examples/HelloPlugin/HelloPlugin.csproj -c Release
```

The lifecycle is `Start(IPluginContext context)` followed by `Stop()` when the
user disables the plugin or closes the main app. The context provides
`ReadSettings()`, `WriteSettings(json)`, `Log(message)`, and `PluginId`.
Plugins can optionally use `IGameTelemetryContext.ReadGameTelemetry()` to
receive a read-only snapshot, or null when live data is unavailable.
Settings must be a JSON object. Plugins should stop threads and unsubscribe
events in `Stop`; unload cannot be guaranteed while a plugin retains resources.
Exceptions from `Start` and `Stop` are displayed and logged; plugins still run
in-process, so arbitrary failures or hangs cannot be completely isolated.

Settings and enabled preferences are in `settings/plugins` and
`settings/plugins-enabled.json`; logs are in `logs/plugins`. Refresh the list
to see current log output. Follow, packet and navigation APIs are not provided.
