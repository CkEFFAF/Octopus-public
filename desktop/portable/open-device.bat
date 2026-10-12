@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem 0006: double-click first-run (GUI when available); later launches reconnect.
set "DEVICE_ROOT=%~dp0"
set "DEVICE_PY=%DEVICE_ROOT%runtime\python.exe"
if not exist "%DEVICE_PY%" (
  echo open-device.bat: portable Python is missing beside this launcher.
  exit /b 1
)
if not exist "%DEVICE_ROOT%launch.py" (
  echo open-device.bat: launch.py is missing beside this launcher.
  exit /b 1
)
set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
"%DEVICE_PY%" "%DEVICE_ROOT%launch.py" device first-run --state "%DEVICE_ROOT%device-state" %*
set "ERR=%ERRORLEVEL%"
if %ERR% neq 0 pause
exit /b %ERR%
