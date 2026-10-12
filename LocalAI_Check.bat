@echo off
rem ---------------------------------------------------------------------------
rem  Check (and test) free local AI with Ollama.
rem    Double-click:              status, and a real test when the model is ready
rem    LocalAI_Check.bat --pull   also downloads the model if it is missing (~6 GB)
rem    LocalAI_Check.bat --folder "C:\path\to\images"   test on your own images
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Behance Studio is not set up yet. Run setup_windows.bat first.
    pause
    exit /b 1
)
set "PYTHONPATH=%~dp0src"
"%~dp0.venv\Scripts\python.exe" -m behance_studio ai-check --test %*
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%
