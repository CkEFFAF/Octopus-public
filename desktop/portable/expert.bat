@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Noninteractive expert client for local coding agents, using this device installation.
set "EXPERT_ROOT=%~dp0"
if not exist "%EXPERT_ROOT%runtime\python.exe" (
  echo Portable Python is missing beside expert.bat. 1>&2
  exit /b 1
)
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONPATH="
"%EXPERT_ROOT%runtime\python.exe" "%EXPERT_ROOT%launch.py" device expert --state "%EXPERT_ROOT%device-state" %*
exit /b %ERRORLEVEL%
