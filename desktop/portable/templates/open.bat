@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Double-click for the full Windows manager UI, using saved settings.
"%~dp0runtime\python.exe" "%~dp0portable-start.py" --background --open %*
if errorlevel 1 pause
