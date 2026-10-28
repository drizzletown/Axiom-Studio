@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run_studio.py
) else (
  python run_studio.py
)
if errorlevel 1 pause
