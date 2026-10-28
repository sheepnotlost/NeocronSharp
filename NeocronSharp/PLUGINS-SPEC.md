# NeocronSharp plugin framework

## Goal

Load independently built .NET 9 C# modules from individual folders, and give
the user controls to inspect, enable, disable, configure and diagnose them.
Installed modules are trusted in-process code and can access the user's
computer; this framework is not a security sandbox. An unknown module starts
disabled and its assembly is not loaded merely to list it.

## Operation

- Discover `plugins/<folder>/plugin.json` manifests. A manifest supplies a
  stable ID, name, version, description, DLL filename and implementing type.
  Invalid manifests and duplicate IDs must be visible as errors without stopping
  other modules. Assembly paths must stay inside the plugin folder.
- The shared C# contract supplies `Start(context)` and `Stop()` lifecycle
  methods. `Start` receives per-plugin JSON settings and a file logger. A
  module is responsible for stopping its own work in `Stop`.
- The Plugins tab shows plugin metadata, status and errors; it offers refresh,
  enable/disable, and an editable JSON settings document with validation.
  Settings edits take effect on the next start of the module.
- Enabled choices persist across application restarts. Application shutdown
  stops running modules without clearing their enabled preference. Exceptions
  in plugin lifecycle methods are reported without crashing the host.
- Include one disabled-by-default sample C# plugin that logs its lifecycle and
  demonstrates settings. No game automation or network functions are provided.

## Architecture and validation

The public contract and plugin host live in `NeocronSharp.Core`. Each plugin
loads in a separate collectible AssemblyLoadContext with the host contract
shared. Unloading is attempted after stopping, but lingering plugin threads,
events, unmanaged resources or references can prevent a complete unload. The
manager does not claim to isolate failures or permissions from arbitrary code.

Settings, enabled choices and logs live under the app's existing `settings`
and `logs` folders. Empty or malformed plugin folders must not break startup.
Use the dependency-free test harness and a separately built test module to
verify discovery, settings persistence, start/stop, failure handling and
restart behavior; check the plugin tab in the desktop UI.

Build: `dotnet build NeocronSharp.sln -c Release`
Test: `dotnet run --project tests/NeocronSharp.Tests -c Release`
