@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"
set "H3_STOP_EXIT=%ERRORLEVEL%"
if not "%H3_STOP_EXIT%"=="0" pause
exit /b %H3_STOP_EXIT%
