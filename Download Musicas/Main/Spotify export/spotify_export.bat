@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
title Spotify Export

echo.
echo ============================================================
echo   SPOTIFY EXPORT
echo ============================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado no PATH.
    echo Instale em https://python.org e marque "Add to PATH".
    pause
    exit /b 1
)

:: O export usa o SpotAPI (sem browser, sem login). Instala sozinho na
:: primeira vez; se nao conseguir, avisa em vez de seguir sem ele.
python -c "import spotapi" >nul 2>&1
if errorlevel 1 (
    echo Instalando spotapi ^(so na primeira vez^)...
    pip install spotapi
    if errorlevel 1 (
        echo ERRO: falha ao instalar o spotapi. Rode manualmente: pip install spotapi
        pause
        exit /b 1
    )
)

:: Link e playlist de destino — usa argumentos se foram passados
:: (atalho pra quem automatiza), senao pergunta interativamente.
set "URL=%~1"
if "%URL%"=="" (
    echo Cole o link da playlist do Spotify e pressione Enter:
    echo   Exemplo: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
    echo.
    set /p "URL=Link: "
)

set "NOME_PL=%~2"
if "%NOME_PL%"=="" (
    echo.
    echo Nome da playlist de destino no SoundVault ^(a que vai ser sincronizada
    echo depois - Enter deixa o programa listar as existentes^):
    set /p "NOME_PL=Nome: "
)

echo.

:: Executar o script (nucleo compartilhado)
set "SOUNDVAULT_ROOT_DIR=%SCRIPT_DIR%..\.."
set "PYTHONPATH=%SCRIPT_DIR%..\..\_core;%PYTHONPATH%"
if "%NOME_PL%"=="" (
    python -m soundvault.spotify_export "%URL%"
) else (
    python -m soundvault.spotify_export "%URL%" "%NOME_PL%"
)
if errorlevel 1 (
    echo.
    echo Ocorreu um erro durante a exportacao.
    echo Verifique o arquivo spotify_export_debug.log para detalhes.
)

echo.
pause
