@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" -VerifyOnly
set "H3_CHECK_EXIT=%ERRORLEVEL%"
pause
exit /b %H3_CHECK_EXIT%
