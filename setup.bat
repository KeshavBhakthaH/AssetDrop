@echo off
setlocal enabledelayedexpansion
title AssetDrop // Automated Setup & Installer

echo ==============================================================================
echo                 ASSETDROP: ONE-CLICK SETUP & INSTALLATION
echo ==============================================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3 is not installed or not in your PATH!
    echo Please install Python 3.10+ from https://python.org or via Microsoft Store.
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [1/4] Installing Python dependencies...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r "%~dp0requirements.txt"
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Some Python dependencies had installation warnings. Continuing...
) else (
    echo [✓] Python dependencies installed successfully.
)
echo.

:: 2. Check FFmpeg
echo [2/4] Checking FFmpeg installation...
where ffmpeg >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [✓] FFmpeg is already installed and available.
) else (
    echo [!] FFmpeg was not detected in PATH.
    echo Attempting automatic installation via Windows Package Manager (winget)...
    where winget >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    ) else (
        echo [NOTE] winget not found. Please install FFmpeg manually from https://ffmpeg.org
        echo or place ffmpeg.exe inside a 'bin' folder in this directory.
    )
)
echo.

:: 3. Configure Windows Firewall
echo [3/4] Configuring Windows Firewall for Port 8000...
call "%~dp0setup_firewall.bat" --no-pause
echo.

:: 4. Create Desktop Shortcut
echo [4/4] Creating Desktop Shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_desktop_shortcut.ps1"
echo.

echo ==============================================================================
echo             [SUCCESS] AssetDrop is configured and ready to use!
echo ==============================================================================
echo.
echo Launching AssetDrop...
start "" "%~dp0AssetDrop.exe"
