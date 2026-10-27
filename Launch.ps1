param([switch]$InstallDependencies, [switch]$CheckDependencies, [switch]$SmokeUi)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot 'runtime\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'The bundled runtime is missing. Extract the complete Neocron Macro Suite folder, including runtime, then run Launch.cmd.'
}
$env:TCL_LIBRARY = Join-Path $PSScriptRoot 'runtime\tcl\tcl8.6'
$env:TK_LIBRARY = Join-Path $PSScriptRoot 'runtime\tcl\tk8.6'
if ($InstallDependencies -or $CheckDependencies) {
    # Keep the old installer entry point compatible; the libraries are now included.
    & $taskPython (Join-Path $PSScriptRoot 'verify_dependencies.py')
} else {
    & $taskPython (Join-Path $PSScriptRoot 'verify_dependencies.py') --quiet
    if ($LASTEXITCODE -ne 0) { throw 'The portable bundle is incomplete. Extract a fresh complete copy of the folder.' }
    if ($SmokeUi) {
        & $taskPython (Join-Path $PSScriptRoot 'app.py') --smoke-ui
    } else {
        & $taskPython (Join-Path $PSScriptRoot 'app.py')
    }
}
if ($LASTEXITCODE -ne 0) { throw "Neocron Macro Suite exited with code $LASTEXITCODE." }
