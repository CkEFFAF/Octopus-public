@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Copy beside launch.py and runtime/ in the portable package.
rem First launch guides enrollment; later launches reuse saved identity.
set "DEVICE_ROOT=%~dp0"
set "DEVICE_PY=%DEVICE_ROOT%runtime\python.exe"
if not exist "%DEVICE_PY%" (
  echo start-device.bat: portable Python is missing beside this launcher.
  exit /b 1
)
if not exist "%DEVICE_ROOT%launch.py" (
  echo start-device.bat: launch.py is missing beside this launcher.
  exit /b 1
)
set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
if "%~1"=="" (
  "%DEVICE_PY%" "%DEVICE_ROOT%launch.py" device join --state "%DEVICE_ROOT%device-state"
) else (
  "%DEVICE_PY%" "%DEVICE_ROOT%launch.py" device connect --state "%DEVICE_ROOT%device-state" %*
)
exit /b %ERRORLEVEL%
