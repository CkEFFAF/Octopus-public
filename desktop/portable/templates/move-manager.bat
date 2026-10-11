@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if "%~1"=="" (
  "runtime\python.exe" -X utf8 "launch.py" backup move
) else (
  "runtime\python.exe" -X utf8 "launch.py" backup %*
)
set "OCTOP_MOVE_EXIT=%errorlevel%"
popd
if "%~1"=="" pause
exit /b %OCTOP_MOVE_EXIT%
