@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem First: start.bat --home "D:\OctopData" --host 0.0.0.0 --port 8188
rem Later: start.bat --home "D:\OctopData" (bind address and port are remembered).
set "ROOT=%~dp0"
if not exist "%ROOT%runtime\python.exe" (
  echo Portable Python is missing. Extract the entire package.
  exit /b 1
)
"%ROOT%runtime\python.exe" "%ROOT%portable-start.py" %*
exit /b %ERRORLEVEL%
