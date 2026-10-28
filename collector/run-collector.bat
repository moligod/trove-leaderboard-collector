@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0collector_app.py"
) else (
  python "%~dp0collector_app.py"
)

if errorlevel 1 pause
