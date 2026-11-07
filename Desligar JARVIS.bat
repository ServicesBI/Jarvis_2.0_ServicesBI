@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "CONTROL_SCRIPT=%PROJECT_ROOT%scripts\jarvis-python-control.ps1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CONTROL_SCRIPT%" -Action Stop
set "STOP_RESULT=%ERRORLEVEL%"

endlocal & exit /b %STOP_RESULT%
