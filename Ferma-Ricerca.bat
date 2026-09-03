@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\search.ps1" -Action stop %*
if errorlevel 1 pause
