@echo off
rem Starts Behance Studio with a console window that shows log messages.
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Behance Studio is not installed yet. Run setup_windows.bat first.
    pause
    exit /b 1
)
set "PYTHONPATH=%~dp0src"
set "BEHANCE_STUDIO_CONSOLE_LOG=1"
"%~dp0.venv\Scripts\python.exe" -m behance_studio %*
echo.
echo Behance Studio exited with code %errorlevel%.
pause
