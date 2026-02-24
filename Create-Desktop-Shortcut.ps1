$ErrorActionPreference = "Stop"

$repoPath = "C:\Users\joelb\Hertz-and-Hearts"
$launcherPath = Join-Path $repoPath "Run-HnH.bat"
$docsPath = Join-Path $repoPath "docs"
$iconPath = Join-Path $docsPath "hnh_icon.ico"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Hertz & Hearts.lnk"

if (!(Test-Path $launcherPath)) {
    throw "Launcher not found: $launcherPath"
}

# If ICO is missing, try to create it from the image attached in Cursor assets.
if (!(Test-Path $iconPath)) {
    $pngPath = "C:\Users\joelb\.cursor\projects\c-Users-joelb-VNS-TA\assets\c__Users_joelb_AppData_Roaming_Cursor_User_workspaceStorage_20480001bfe1dc00afb6213de494a854_images_image-7addc6a9-c3f7-4125-9226-ead3f1980043.png"
    if (Test-Path $pngPath) {
        try {
            python -c "from PIL import Image; img=Image.open(r'$pngPath').convert('RGBA'); img.save(r'$iconPath', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
        } catch {
            Write-Warning "Could not auto-convert PNG to ICO via Python/Pillow. Shortcut will still be created."
        }
    }
}

$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = $repoPath
if (Test-Path $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
}
$shortcut.Save()

Write-Host "Created desktop shortcut:"
Write-Host "  $shortcutPath"
if (Test-Path $iconPath) {
    Write-Host "Using icon:"
    Write-Host "  $iconPath"
} else {
    Write-Host "Icon not found; Windows default icon is currently used."
}
