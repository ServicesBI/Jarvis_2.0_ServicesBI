@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "VENV_PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "SYSTEM_PYTHON="

if not exist "%PROJECT_ROOT%run.py" (
    echo ERRO: execute este instalador na raiz do repositorio JARVIS.
    exit /b 10
)

where node >nul 2>&1
if errorlevel 1 (
    echo ERRO: Node.js nao encontrado. Instale uma versao LTS para os runtimes auxiliares.
    exit /b 11
)

if not exist "%VENV_PYTHON%" (
    where py >nul 2>&1
    if not errorlevel 1 set "SYSTEM_PYTHON=py -3"
    if not defined SYSTEM_PYTHON (
        where python >nul 2>&1
        if not errorlevel 1 set "SYSTEM_PYTHON=python"
    )
    if not defined SYSTEM_PYTHON (
        echo ERRO: Python 3 nao encontrado.
        exit /b 12
    )

    echo Criando ambiente Python isolado...
    %SYSTEM_PYTHON% -m venv "%PROJECT_ROOT%.venv"
    if errorlevel 1 exit /b 13
)

echo Instalando dependencias Python...
"%VENV_PYTHON%" -m pip install -r "%PROJECT_ROOT%requirements.txt" --disable-pip-version-check
if errorlevel 1 exit /b 20

cd /d "%PROJECT_ROOT%"
echo Instalando runtime Node auxiliar...
call npm install --omit=dev --no-audit
if errorlevel 1 exit /b 21

if exist "%PROJECT_ROOT%launcher\package.json" (
    pushd "%PROJECT_ROOT%launcher"
    call npm install --no-audit
    if errorlevel 1 (popd & exit /b 22)
    popd
)

if exist "%PROJECT_ROOT%pet\package.json" (
    pushd "%PROJECT_ROOT%pet"
    call npm install --no-audit
    if errorlevel 1 (popd & exit /b 23)
    popd
)

if not exist "%PROJECT_ROOT%.env" (
    copy /Y "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" >nul
    echo .env criado a partir de .env.example. Preencha somente as credenciais necessarias.
)

echo Instalacao concluida. Use Ligar JARVIS.bat para iniciar.
endlocal & exit /b 0
