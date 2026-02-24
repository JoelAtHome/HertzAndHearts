@echo off
setlocal
set "ROOT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%Create-Desktop-Shortcut.ps1"
if errorlevel 1 (
  echo.
  echo Failed to create desktop shortcut.
  pause
  exit /b 1
)
echo.
echo Desktop shortcut created successfully.
pause
exit /b 0
