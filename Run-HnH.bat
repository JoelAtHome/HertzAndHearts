@echo off
setlocal

rem Launch Hertz & Hearts from repository root.
set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%"

rem Self-heal desktop shortcut after folder moves.
if exist "%ROOT_DIR%Create-Desktop-Shortcut.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%Create-Desktop-Shortcut.ps1" >nul 2>&1
)

set "PYTHON_EXE="
if exist "%ROOT_DIR%venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT_DIR%venv\Scripts\python.exe"
) else (
    where py >nul 2>&1
    if %ERRORLEVEL%==0 (
        set "PYTHON_EXE=py -3"
    ) else (
        set "PYTHON_EXE=python"
    )
)

echo Starting Hertz ^& Hearts...
%PYTHON_EXE% -m hnh.app
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Hertz & Hearts exited with code %EXIT_CODE%.
    pause
)

popd
exit /b %EXIT_CODE%
