@echo off
rem Build the Windows distribution: dist\BehanceStudio (portable folder) and,
rem when Inno Setup 6 is installed, dist\installer\BehanceStudio-Setup-<version>.exe.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The development environment is missing. Run setup_windows.bat first.
  exit /b 1
)
set "PY=.venv\Scripts\python.exe"
echo [1/4] Installing packaging tools...
"%PY%" -m pip install --disable-pip-version-check -q -r requirements-build.txt || goto :fail
for /f "tokens=1,2" %%a in ('"%PY%" tools\version_info.py') do (
  set "APPVER=%%a"
  set "NUMVER=%%b"
)
echo [2/4] Building Behance Studio %APPVER% with PyInstaller (this takes a few minutes)...
"%PY%" -m PyInstaller packaging\BehanceStudio.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller || goto :fail
echo [3/4] Checking the build...
"dist\BehanceStudio\BehanceStudio-cli.exe" doctor || goto :fail
echo [4/4] Creating the installer...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo Inno Setup 6 was not found: the portable folder dist\BehanceStudio is ready.
  echo Install Inno Setup 6 from https://jrsoftware.org/isinfo.php and run this script again for an installer.
  exit /b 0
)
"%ISCC%" /Qp /DAppVersion=%APPVER% /DNumericVersion=%NUMVER% packaging\BehanceStudio.iss || goto :fail
echo Done: dist\installer\BehanceStudio-Setup-%APPVER%.exe
exit /b 0
:fail
echo Build failed. See the messages above.
exit /b 1
