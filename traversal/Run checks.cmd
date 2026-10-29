@echo off
rem Double-click: offline checks of the traversal engine (no game input).
rem  1. the engine tests   2. the city-route simulation over every city-to-city leg
title Traversal checks
cd /d "%~dp0"
echo Building...
dotnet build -c Release -nologo -v q >logs\build.log 2>&1 || (echo Build failed, see logs\build.log & pause & exit /b 1)
echo.
echo === Engine tests ===
pushd tests
dotnet run -c Release 2>&1 | findstr /v /c:"baked in" /c:"sector map of"
set TESTS=%errorlevel%
popd
echo.
echo === City routes (simulated) ===
bin\Release\net9.0\traversal.exe simcity 2>&1 | findstr /v /c:"baked in" /c:"sector map of"
echo.
pause
