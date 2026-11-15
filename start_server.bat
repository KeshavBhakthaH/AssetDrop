@echo off
setlocal
echo ==============================================================================
echo [AssetDrop] Starting Media Ingestion Daemon on Port 8000...
echo ==============================================================================
cd /d "%~dp0"
python server.py
pause
