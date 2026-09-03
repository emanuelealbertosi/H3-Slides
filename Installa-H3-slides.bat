@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" %*
set "H3_SETUP_EXIT=%ERRORLEVEL%"
pause
exit /b %H3_SETUP_EXIT%
