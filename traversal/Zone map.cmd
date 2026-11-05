@echo off
rem Double-click: one wasteland zone (cell) at full detail, every object named, with a coordinate grid.
title Zone map
cd /d "%~dp0"
if not exist bin\Release\net9.0\traversal.exe (
  echo Building Traversal...
  dotnet build -c Release -nologo -v q >logs\build.log 2>&1 || (echo Build failed, see logs\build.log & pause & exit /b 1)
)
set /p ZONE=Which zone? (its cell on the world map, for example J01):
echo Drawing %ZONE%...
"%~dp0..\runtime\python.exe" worldmap.py %ZONE% --open || (pause & exit /b 1)
