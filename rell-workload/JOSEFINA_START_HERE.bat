@echo off
title Rell Workload Tracker
echo.
echo  ===================================================
echo   RELL WORKLOAD TRACKER
echo  ===================================================
echo.

:: Change to the directory where this .bat file lives
cd /d "%~dp0"

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed or not in PATH.
    echo.
    echo  Please ask your IT team to install Python 3.11+
    echo  or download it from: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: First-time setup: create virtual environment if it doesn't exist
if not exist ".venv\Scripts\activate.bat" (
    echo  First-time setup: creating Python environment...
    python -m venv .venv
    if errorlevel 1 (
        echo  ERROR: Could not create Python environment.
        pause
        exit /b 1
    )
    echo  Installing required packages...
    .venv\Scripts\pip.exe install -r requirements.txt --quiet
    if errorlevel 1 (
        echo  ERROR: Package installation failed.
        pause
        exit /b 1
    )
    echo  Setup complete!
    echo.
)

:: Launch the server (browser opens automatically)
echo  Starting Workload Tracker...
echo  Your browser will open automatically.
echo.
echo  To stop the app: close this window or press Ctrl+C
echo.
.venv\Scripts\python.exe run_web.py

:: If server stops, pause so the user can see any error
pause
