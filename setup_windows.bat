@echo off
rem ---------------------------------------------------------------------------
rem  Behance Studio - one-time setup for Windows 10/11
rem
rem  Creates a private Python environment in .venv (inside this folder),
rem  installs the pinned dependencies and the Chromium rendering engine.
rem  Nothing is installed system-wide and no system files are changed.
rem  Safe to run again: it repairs or updates an existing installation.
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Behance Studio setup

echo.
echo   BEHANCE STUDIO - setup
echo   ======================
echo.

rem --- 1. Find a supported Python (3.12, 3.13 or 3.14) -------------------------
set "PYEXE="
where py >nul 2>&1
if not errorlevel 1 (
    for %%V in (3.13 3.14 3.12) do (
        if not defined PYEXE (
            py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
        )
    )
)
if not defined PYEXE (
    python -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] <= (3, 14) else 1)" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo   [!] Python 3.12, 3.13 or 3.14 ^(64-bit^) was not found.
    echo.
    echo       Install Python 3.13 from https://www.python.org/downloads/windows/
    echo       ^(tick "Add python.exe to PATH" or keep the "py" launcher option^),
    echo       then run this setup again.
    echo.
    start "" "https://www.python.org/downloads/windows/"
    pause
    exit /b 1
)
for /f "tokens=2" %%I in ('%PYEXE% -V 2^>^&1') do set "PYVER=%%I"
echo   Using Python %PYVER%  (%PYEXE%)

rem --- 2. Private environment ---------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1 || (
        echo   The existing .venv is broken; recreating it...
        rmdir /s /q ".venv"
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo   Creating the private environment in .venv ...
    %PYEXE% -m venv ".venv" || goto :fail
)
set "VPY=%~dp0.venv\Scripts\python.exe"

echo   Installing dependencies (this can take a few minutes the first time)...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q || goto :fail
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check || goto :fail
"%VPY%" -m pip install -e . --no-deps --disable-pip-version-check -q
if errorlevel 1 echo   Optional editable install skipped - the launcher does not need it.

rem --- 3. Rendering engine ------------------------------------------------------
echo.
echo   Installing the Chromium rendering engine (about 150 MB)...
"%VPY%" -m playwright install chromium
if errorlevel 1 (
    echo   [!] Chromium could not be downloaded. Behance Studio will use
    echo       Microsoft Edge instead, which is part of Windows 10/11.
)

rem --- 4. Check -----------------------------------------------------------------
echo.
set "PYTHONPATH=%~dp0src"
"%VPY%" -m behance_studio doctor
if errorlevel 1 (
    echo   [!] No rendering browser was found. Install Microsoft Edge or Google
    echo       Chrome, or run this setup again with an internet connection.
)

rem --- 5. Optional desktop shortcut ---------------------------------------------
echo.
choice /c YN /n /m "  Create a desktop shortcut? [Y/N] "
if errorlevel 2 goto :done
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Behance Studio.lnk'));" ^
  "$s.TargetPath = '%~dp0BehanceStudio.bat'; $s.WorkingDirectory = '%~dp0';" ^
  "$s.IconLocation = '%~dp0src\behance_studio\resources\icons\app.ico'; $s.WindowStyle = 7; $s.Save()"
if errorlevel 1 (echo   Could not create the shortcut.) else (echo   Shortcut created on the desktop.)

:done
echo.
echo   Setup complete. Start Behance Studio with BehanceStudio.bat
echo.
pause
exit /b 0

:fail
echo.
echo   [!] Setup failed. Check your internet connection and try again.
echo       If the problem continues, send the messages above to support.
echo.
pause
exit /b 1
