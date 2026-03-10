param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "Installing build dependencies..."
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e .[build]

Write-Host "Building app bundle via PyInstaller..."
& $PythonExe -m PyInstaller Hertz-and-Hearts.spec --clean --noconfirm

Write-Host "Creating portable ZIP..."
$zipPath = "dist/Hertz-and-Hearts-windows-x64.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "dist/Hertz-and-Hearts/*" -DestinationPath $zipPath -Force

Write-Host "Windows package created: $zipPath"
Write-Host "Optional installer: run installer.iss with Inno Setup (iscc)."
