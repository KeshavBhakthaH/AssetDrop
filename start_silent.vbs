' ==============================================================================
' AssetDrop: Cross-Device Media Ingestion Engine (v2.0)
' Windows Silent Background Launcher
' ==============================================================================
' Purpose: Headlessly launches the Uvicorn FastAPI server on 0.0.0.0:8000
'          without opening a command prompt or console window (zero window popup).
' Window Style: 0 (vbHide - completely invisible)
' Wait Mode: False (returns immediately, process runs in background)
' ==============================================================================

Option Explicit

Dim WshShell, fso, scriptDir
Set WshShell = WScript.CreateObject("WScript.Shell")
Set fso = WScript.CreateObject("Scripting.FileSystemObject")

' Dynamically determine directory where this script resides (AssetDrop root)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' Headlessly launch pythonw with Uvicorn
' Host 0.0.0.0 binds to all local network interfaces (Wi-Fi, Ethernet, Tailscale)
' Launch via cmd.exe /c with window style 0 (hidden) to ensure Windows Store execution aliases resolve seamlessly
WshShell.Run "cmd.exe /c pythonw -m uvicorn server:app --host 0.0.0.0 --port 8000", 0, False

Set WshShell = Nothing
Set fso = Nothing
