@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "CONTROL_SCRIPT=%PROJECT_ROOT%scripts\jarvis-python-control.ps1"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "STARTUP_TIMEOUT_SECONDS=30"
set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
set "CHROME_X86_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
set "CHROME_USER_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
set "EDGE_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
set "EDGE_X86_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
set "EDGE_USER_EXE=%LocalAppData%\Microsoft\Edge\Application\msedge.exe"

if not exist "%PYTHON_EXE%" (
    echo ERRO: o ambiente Python do Jarvis nao esta configurado.
    echo Esperado: %PYTHON_EXE%
    echo Crie a .venv e instale requirements.txt antes de iniciar.
    exit /b 30
)

pushd "%PROJECT_ROOT%"
for /f "tokens=1,2" %%H in ('call "%PYTHON_EXE%" -c "from app.core.config import HOST, PORT; print(HOST, PORT)"') do (
    set "JARVIS_HOST=%%H"
    set "JARVIS_PORT=%%I"
)
popd
if not defined JARVIS_HOST (
    echo ERRO: nao foi possivel resolver a configuracao canonica do Jarvis.
    exit /b 31
)
set "HEALTH_URL=http://%JARVIS_HOST%:%JARVIS_PORT%/api/health"
set "JARVIS_URL=http://%JARVIS_HOST%:%JARVIS_PORT%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CONTROL_SCRIPT%" -Action Check
set "CHECK_RESULT=%ERRORLEVEL%"

if "%CHECK_RESULT%"=="10" goto OPEN_INTERFACE
if not "%CHECK_RESULT%"=="0" exit /b %CHECK_RESULT%

echo Iniciando Jarvis Python...
start "Jarvis Python" /D "%PROJECT_ROOT%" "%PYTHON_EXE%" run.py
if errorlevel 1 (
    echo ERRO: nao foi possivel iniciar o Jarvis pela .venv.
    exit /b 20
)

echo Aguardando o Jarvis responder em %HEALTH_URL%...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$deadline = [DateTime]::UtcNow.AddSeconds(%STARTUP_TIMEOUT_SECONDS%); do { try { $response = Invoke-WebRequest -Uri '%HEALTH_URL%' -Method Get -UseBasicParsing -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 250 } while ([DateTime]::UtcNow -lt $deadline); exit 1"
if errorlevel 1 (
    echo ERRO: Jarvis Python nao respondeu em %STARTUP_TIMEOUT_SECONDS% segundos.
    echo A interface nao sera aberta.
    exit /b 21
)

:OPEN_INTERFACE
echo Abrindo %JARVIS_URL%...
if exist "%CHROME_EXE%" (
    echo Usando Chrome em modo aplicativo.
    start "" "%CHROME_EXE%" --app="%JARVIS_URL%"
    goto BROWSER_OPENED
)
if exist "%CHROME_X86_EXE%" (
    echo Usando Chrome em modo aplicativo.
    start "" "%CHROME_X86_EXE%" --app="%JARVIS_URL%"
    goto BROWSER_OPENED
)
if exist "%CHROME_USER_EXE%" (
    echo Usando Chrome em modo aplicativo.
    start "" "%CHROME_USER_EXE%" --app="%JARVIS_URL%"
    goto BROWSER_OPENED
)
if exist "%EDGE_EXE%" (
    echo Usando Edge em modo aplicativo.
    start "" "%EDGE_EXE%" --app="%JARVIS_URL%"
    goto BROWSER_OPENED
)
if exist "%EDGE_X86_EXE%" (
    echo Usando Edge em modo aplicativo.
    start "" "%EDGE_X86_EXE%" --app="%JARVIS_URL%"
    goto BROWSER_OPENED
)
if exist "%EDGE_USER_EXE%" (
    echo Usando Edge em modo aplicativo.
    start "" "%EDGE_USER_EXE%" --app="%JARVIS_URL%"
    goto BROWSER_OPENED
)

echo Chrome ou Edge nao encontrado. Usando o navegador padrao.
cmd.exe /d /c start "" "%JARVIS_URL%"

:BROWSER_OPENED
if errorlevel 1 (
    echo ERRO: nao foi possivel abrir o navegador.
    exit /b 22
)

endlocal & exit /b 0
