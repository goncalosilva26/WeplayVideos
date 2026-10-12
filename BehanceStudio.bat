@echo off
rem ---------------------------------------------------------------------------
rem  Behance Studio launcher.
rem  Always uses this folder's own Python environment (.venv), never a global
rem  Python. Any arguments are passed on (e.g. a project folder to open).
rem  Use BehanceStudio_debug.bat to see console output when troubleshooting.
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Behance Studio is not installed yet. Starting the setup...
    call "%~dp0setup_windows.bat"
    if not exist "%~dp0.venv\Scripts\pythonw.exe" exit /b 1
)

set "PYTHONPATH=%~dp0src"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m behance_studio %*
exit /b 0
