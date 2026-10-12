@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem 0010 transition wrapper: filing-period hub via OCTOP_DEVICE_SERVER.
rem Product DEFAULT stays https://octop.effaf.me ? do not hardcode IP into package constants.
set "OCTOP_DEVICE_SERVER=http://111.228.42.228:8188"
call "%~dp0open-device.bat" %*
exit /b %ERRORLEVEL%
