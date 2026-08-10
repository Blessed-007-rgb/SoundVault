import os
from pathlib import Path

# ROOT_DIR vem de SOUNDVAULT_ROOT_DIR (setado pelo .bat) ou do diretório de
# trabalho atual (play.bat já faz `cd /d "%~dp0"` antes de chamar o Python,
# então cwd = pasta do perfil = ROOT_DIR/NomeDoPerfil).
_env_root = os.environ.get("SOUNDVAULT_ROOT_DIR")
if _env_root:
    ROOT_DIR = Path(_env_root).resolve()
else:
    ROOT_DIR = Path.cwd().resolve().parent

DEFAULT_PROFILE = "Main"


def resolver_perfil(nome: str) -> Path:
    p = ROOT_DIR / nome
    p.mkdir(parents=True, exist_ok=True)
    (p / "Musicas").mkdir(exist_ok=True)
    (p / "Logs").mkdir(exist_ok=True)
    return p


def ativar_perfil(nome: str):
    """
    Muda o perfil ativo atualizando todas as variáveis globais de caminho.

    IMPORTANTE: usa 'global' explicitamente — sem isso, as funções que leem
    DOWNLOAD_DIR, CACHE_FILE etc. no momento da chamada (não da definição)
    continuariam vendo o perfil padrão mesmo após trocar com --profile.
    """
    global BASE_DIR, DOWNLOAD_DIR, CACHE_FILE, STATE_FILE
    global LOGS_DIR, DEBUG_FILE, HIST_FILE, FALHAS_FILE
    global COOKIES_FILE, LOCK_FILE

    base = resolver_perfil(nome)
    BASE_DIR     = base
    DOWNLOAD_DIR = base / "Musicas"
    CACHE_FILE   = base / "playlist_cache.json"
    STATE_FILE   = base / "sync_state.json"
    LOGS_DIR     = base / "Logs"
    DEBUG_FILE   = base / "Logs" / "DEBUG.log"
    HIST_FILE    = base / "Logs" / "historico.json"
    FALHAS_FILE  = base / "Logs" / "falhas.json"
    COOKIES_FILE = base / "cookies.txt"
    LOCK_FILE    = base / ".lock"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (base / "Logs").mkdir(parents=True, exist_ok=True)


# Perfil ativo — sobrescrito por --profile na CLI (ver __main__.py)
BASE_DIR     = resolver_perfil(DEFAULT_PROFILE)
DOWNLOAD_DIR = BASE_DIR / "Musicas"
CACHE_FILE   = BASE_DIR / "playlist_cache.json"
STATE_FILE   = BASE_DIR / "sync_state.json"
LOGS_DIR     = BASE_DIR / "Logs"
DEBUG_FILE   = LOGS_DIR / "DEBUG.log"
HIST_FILE    = LOGS_DIR / "historico.json"
FALHAS_FILE  = LOGS_DIR / "falhas.json"
COOKIES_FILE = BASE_DIR / "cookies.txt"
LOCK_FILE    = BASE_DIR / ".lock"

BASE_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

WORKERS       = 3
MAX_RETRIES   = 5
RETRY_DELAY   = 3
TIMEOUT_DL    = 300
NOTIFY_ON_FINISH  = True
COOKIE_HEALTH_CHECK_INTERVAL_H = 12
# Intervalo mínimo entre testes reais de autenticação do cookies.txt antes
# de um Sync (health-check) — testar em todo Sync gastaria alguns segundos
# à toa quando o cookie provavelmente ainda está válido.
NORMALIZAR_VOLUME = True
PEAK_TARGET       = -3.0
# -3.0 dBFS (não -1.0): a recodificação com perdas pra MP3 (libmp3lame)
# gera picos "entre amostras" que podem exceder o pico medido antes da
# codificação — com só 1dB de margem, esse overshoot come toda a
# redução e o pico final fica preso no teto (0 dBFS) de forma
# inconsistente entre faixas. -3dB é a margem padrão recomendada pra
# evitar isso (confirmado empiricamente: com -1dB o pico não abaixava
# do teto; a partir de -2/-3dB passou a refletir o ganho real).
EQ_ATIVO          = True


def verificar_dependencias():
    """
    Verifica se yt-dlp, Node.js e FFmpeg estão instalados e acessíveis no PATH.
    Retorna (tudo_ok: bool, faltando: list[(nome, critico, instrucao)]).
    Não imprime nada aqui — quem chama decide como exibir.
    """
    import shutil
    deps = [
        ("yt-dlp",  "yt-dlp",  True,  "pip install yt-dlp"),
        ("node",    "Node.js", True,  "https://nodejs.org"),
        ("ffmpeg",  "FFmpeg",  True,  "https://ffmpeg.org/download.html"),
    ]
    faltando = []
    tudo_ok = True
    for cmd, nome, critico, instrucao in deps:
        if shutil.which(cmd) is None:
            faltando.append((nome, critico, instrucao))
            if critico:
                tudo_ok = False
    return tudo_ok, faltando
