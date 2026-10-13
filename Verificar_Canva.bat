@echo off
rem ---------------------------------------------------------------------------
rem  Compara o que o Canva mostra com o original.
rem    1. Importe no canva.com o .pptx exportado pelo Behance Studio.
rem    2. No Canva: Partilhar - Transferir - PNG - todas as paginas (da um ZIP).
rem    3. Execute este ficheiro e indique o .pptx e o ZIP transferido.
rem    Verificar_Canva.bat "design.pptx" "transferencia-do-canva.zip"
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo O Behance Studio ainda nao esta instalado. Execute primeiro setup_windows.bat.
    pause
    exit /b 1
)
set "DESIGN=%~1"
set "PAGES=%~2"
if "%DESIGN%"=="" (
    echo Arraste para esta janela o ficheiro .pptx exportado pelo Behance Studio e prima Enter:
    set /p "DESIGN=> "
)
if "%PAGES%"=="" (
    echo Arraste para esta janela o ZIP ^(ou PDF^) transferido do Canva e prima Enter:
    set /p "PAGES=> "
)
set "DESIGN=%DESIGN:"=%"
set "PAGES=%PAGES:"=%"
set "PYTHONPATH=%~dp0src"
"%~dp0.venv\Scripts\python.exe" -m behance_studio canva-verify "%DESIGN%" "%PAGES%"
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%
