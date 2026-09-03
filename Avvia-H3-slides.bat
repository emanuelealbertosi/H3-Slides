@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "H3_START_EXIT=%ERRORLEVEL%"
if not "%H3_START_EXIT%"=="0" pause
exit /b %H3_START_EXIT%
