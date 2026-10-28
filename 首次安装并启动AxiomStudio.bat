@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
)
if not exist .venv\Scripts\python.exe (
  echo Python 3.10+ and python venv are required.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency install failed.
  pause
  exit /b 1
)
.venv\Scripts\python.exe scripts\release_selftest.py
if errorlevel 1 (
  echo Release selftest failed; server will not start.
  pause
  exit /b 1
)
.venv\Scripts\python.exe run_studio.py
if errorlevel 1 pause
