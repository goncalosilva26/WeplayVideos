@echo off
rem Runs the automated test suite with this folder's own Python environment.
rem Extra arguments go to pytest, e.g.  run_tests.bat -k export -x
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m pip install -r requirements-dev.txt -q --disable-pip-version-check || goto :fail
set "PYTHONPATH=%~dp0src"
"%~dp0.venv\Scripts\python.exe" -m pytest %*
set "CODE=%errorlevel%"
echo.
if "%CODE%"=="0" (echo All tests passed.) else (echo Some tests failed - see above.)
pause
exit /b %CODE%

:fail
echo Could not install the test tools.
pause
exit /b 1
