@echo off
setlocal

echo ==============================================================================
echo [AssetDrop] Windows Defender Firewall Inbound Rule Configuration
echo ==============================================================================

:: Check for Administrative Privileges
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [AssetDrop] Administrator privileges required to configure firewall rules.
    echo [AssetDrop] Requesting elevation via UAC...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b 0
)

:: Elevated Execution: Add Inbound Rule for Port 8000
echo [AssetDrop] Running with Administrator privileges.
echo [AssetDrop] Configuring inbound rule for TCP port 8000...

:: Clean up any existing rule first to ensure idempotency
netsh advfirewall firewall delete rule name="AssetDrop Ingestion Server (Port 8000)" >nul 2>&1
netsh advfirewall firewall delete rule name="AssetDrop Media Server" >nul 2>&1

:: Add the inbound rule for TCP port 8000
netsh advfirewall firewall add rule name="AssetDrop Ingestion Server (Port 8000)" dir=in action=allow protocol=TCP localport=8000 profile=any

set RULE_ERR=%ERRORLEVEL%
if %RULE_ERR% equ 0 (
    echo ==============================================================================
    echo [AssetDrop] SUCCESS: Inbound rule for Port 8000 added to Windows Defender Firewall.
    echo [AssetDrop] Mobile devices on LAN and Tailscale can now connect to port 8000.
    echo ==============================================================================
) else (
    echo ==============================================================================
    echo [AssetDrop] ERROR: Failed to add firewall rule. Exit code: %RULE_ERR%
    echo ==============================================================================
)

:: Pause if run interactively, avoid blocking if run with --no-pause or non-interactive
if not "%~1"=="--no-pause" if not "%~1"=="--silent" (
    echo.
    pause
)

exit /b %RULE_ERR%
