@echo off
rem ---------------------------------------------------------------------------
rem  Teste real com um dos seus projetos.
rem    Arraste a pasta do projeto para cima deste ficheiro, ou faca duplo clique
rem    e cole o caminho da pasta quando for pedido.
rem  Cria em Documentos\Behance Studio Tests: as 5 propostas, PDF, ficheiros
rem  para o Canva, RELATORIO.txt e um ZIP para enviar (sem os ficheiros originais).
rem    Teste_Real.bat "C:\pasta\do\projeto" --no-ai      sem a IA local
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo O Behance Studio ainda nao esta instalado. Execute primeiro setup_windows.bat.
    pause
    exit /b 1
)
set "FOLDER=%~1"
if "%FOLDER%"=="" (
    echo Cole o caminho da pasta do projeto ^(ex.: C:\Users\Nome\Desktop\Cliente^) e prima Enter:
    set /p "FOLDER=> "
)
set "FOLDER=%FOLDER:"=%"
if not exist "%FOLDER%\" (
    echo A pasta nao existe: %FOLDER%
    pause
    exit /b 1
)
set "PYTHONPATH=%~dp0src"
if "%~1"=="" (
    "%~dp0.venv\Scripts\python.exe" -m behance_studio real-test "%FOLDER%"
) else (
    "%~dp0.venv\Scripts\python.exe" -m behance_studio real-test "%FOLDER%" %2 %3 %4 %5
)
set "CODE=%errorlevel%"
echo.
pause
exit /b %CODE%
