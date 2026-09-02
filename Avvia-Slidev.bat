@echo off
cd /d "%~dp0"
set "PATH=%~dp0runtime\node;%PATH%"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0runtime\browsers"
"%~dp0runtime\node\node.exe" "%~dp0node_modules\@slidev\cli\bin\slidev.mjs" "%~dp0examples\slides.md" --port 3031 --bind 127.0.0.1
if errorlevel 1 pause
