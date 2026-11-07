@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"

if not exist "%PROJECT_ROOT%run.py" (
    echo ERRO: run.py nao encontrado em %PROJECT_ROOT%
    exit /b 10
)

where git >nul 2>&1
if errorlevel 1 (
    echo ERRO: Git nao encontrado.
    exit /b 11
)

if not exist "%PYTHON_EXE%" (
    echo ERRO: ambiente .venv ausente. Execute INSTALAR-JARVIS.bat.
    exit /b 12
)

cd /d "%PROJECT_ROOT%"

for /f "delims=" %%L in ('git status --porcelain --untracked-files^=normal') do (
    echo ERRO: existem alteracoes locais. Atualizacao cancelada para preservar seus arquivos.
    git status --short
    exit /b 13
)

call "%PROJECT_ROOT%Desligar JARVIS.bat" >nul 2>&1

echo Atualizando codigo com fast-forward...
git pull --ff-only
if errorlevel 1 (
    echo ERRO: nao foi possivel atualizar sem reescrever o historico local.
    exit /b 14
)

echo Atualizando dependencias Python...
"%PYTHON_EXE%" -m pip install -r "%PROJECT_ROOT%requirements.txt" --disable-pip-version-check
if errorlevel 1 exit /b 20

echo Atualizando runtime Node auxiliar...
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

echo JARVIS atualizado com seguranca.
endlocal & exit /b 0
