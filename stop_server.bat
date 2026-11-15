@echo off
setlocal enabledelayedexpansion

echo ==============================================================================
echo [AssetDrop] Media Ingestion Server Process Stopper
echo ==============================================================================
echo [AssetDrop] Checking for active server listening on port 8000...

set FOUND=0
set KILLED_PIDS=

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    set PID=%%a
    if not "!PID!"=="" (
        if not "!PID!"=="0" (
            echo !KILLED_PIDS! | findstr /C:" !PID! " >nul
            if errorlevel 1 (
                echo [AssetDrop] Found active process listening on port 8000 [PID: !PID!]. Terminating...
                taskkill /F /PID !PID! >nul 2>&1
                if !errorlevel! equ 0 (
                    echo [AssetDrop] Successfully terminated process [PID: !PID!].
                ) else (
                    echo [AssetDrop] Process [PID: !PID!] has already stopped or terminated.
                )
                set KILLED_PIDS=!KILLED_PIDS! !PID! 
                set FOUND=1
            )
        )
    )
)

if !FOUND! equ 1 (
    echo [AssetDrop] AssetDrop server stopped successfully.
) else (
    echo [AssetDrop] No active server process found listening on port 8000.
)

echo ==============================================================================
exit /b 0
