@echo off
rem Double-click: draws the wasteland world map from the game's files and opens it (about a minute).
title World map
cd /d "%~dp0"
if not exist bin\Release\net9.0\traversal.exe (
  echo Building Traversal...
  dotnet build -c Release -nologo -v q >logs\build.log 2>&1 || (echo Build failed, see logs\build.log & pause & exit /b 1)
)
echo Drawing the world map...
"%~dp0..\runtime\python.exe" worldmap.py --open || (pause & exit /b 1)
