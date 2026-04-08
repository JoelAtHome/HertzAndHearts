param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "Installing build dependencies..."
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e .[build]

Write-Host "Building app bundle via PyInstaller..."
& $PythonExe -m PyInstaller Hertz-and-Hearts.spec --clean --noconfirm

Write-Host "Resolving release version label..."
$pep440 = & $PythonExe -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])'
$pep440 = "$pep440".Trim()
$public = & $PythonExe -c "import re; v='$pep440'; m=re.fullmatch(r'(\d+\.\d+\.\d+)b(\d+)', v); print(f'{m.group(1)}-beta' if m and m.group(2)=='0' else f'{m.group(1)}-beta.{m.group(2)}' if m else v)"
$public = "$public".Trim()

Write-Host "Creating portable ZIP..."
$zipPath = "dist/Hertz-and-Hearts-$public-windows-x64.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "dist/Hertz-and-Hearts/*" -DestinationPath $zipPath -Force

Write-Host "Windows package created: $zipPath"
Write-Host "Optional installer: run installer.iss with Inno Setup (iscc)."
