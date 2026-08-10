@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
if not exist "%SCRIPT_DIR%Logs" mkdir "%SCRIPT_DIR%Logs"
set "SOUNDVAULT_ROOT_DIR=%SCRIPT_DIR%.."
set "PYTHONPATH=%SCRIPT_DIR%..\_core;%PYTHONPATH%"
python -m soundvault %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================================
    echo  ERRO FATAL - verifique Logs\crash.log
    echo ============================================================
    pause
)
