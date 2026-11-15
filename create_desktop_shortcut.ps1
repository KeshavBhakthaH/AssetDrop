$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $DesktopPath "AssetDrop.lnk"
$TargetDir = "D:\AssetDrop"
$TargetPath = Join-Path $TargetDir "AssetDrop.exe"
$IconPath = Join-Path $TargetDir "static\icons\favicon.ico"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = $TargetDir
$Shortcut.IconLocation = "$IconPath,0"
$Shortcut.Description = "AssetDrop - Cross-Device Media Ingestion Workstation"
$Shortcut.Save()

Write-Host "Created desktop shortcut at: $ShortcutPath"
