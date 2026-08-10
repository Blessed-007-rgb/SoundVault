@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================================
echo   SOUNDVAULT - ESCOLHA UM PERFIL
echo ============================================================
echo.

set count=0
for /d %%D in (*) do (
    if exist "%%D\play*.bat" (
        set /a count+=1
        for %%F in ("%%D\play*.bat") do (
            echo   !count! - %%D  ^(%%~nxF^)
            set "bat[!count!]=%%F"
        )
    )
)

if %count%==0 (
    echo Nenhum perfil encontrado. Crie uma pasta com um play*.bat dentro.
    pause
    exit /b 1
)

echo.
set /p escolha="Escolha o numero do perfil: "
if not defined bat[%escolha%] (
    echo Escolha invalida.
    pause
    exit /b 1
)
call "!bat[%escolha%]!"
