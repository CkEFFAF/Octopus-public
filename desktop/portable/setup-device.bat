@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Guided setup/add another manager, or commands: setup-device.bat controllers
set "ROOT=%~dp0"
if "%~1"=="" (
  "%ROOT%runtime\python.exe" "%ROOT%launch.py" device setup --state "%ROOT%device-state"
) else (
  "%ROOT%runtime\python.exe" "%ROOT%launch.py" device %* --state "%ROOT%device-state"
)
if errorlevel 1 pause
