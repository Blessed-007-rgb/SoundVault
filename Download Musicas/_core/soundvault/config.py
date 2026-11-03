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
# Renders de EQ/loudnorm simultâneos (ffmpeg usa ~1 núcleo por job). Deixa
# 1 núcleo livre pro resto do sistema; mínimo 1.
RENDER_WORKERS = max(1, (os.cpu_count() or 2) - 1)
MAX_RETRIES   = 5
RETRY_DELAY   = 3
TIMEOUT_DL    = 300
NOTIFY_ON_FINISH  = True
COOKIE_HEALTH_CHECK_INTERVAL_H = 12
# Intervalo mínimo entre testes reais de autenticação do cookies.txt antes
# de um Sync (health-check) — testar em todo Sync gastaria alguns segundos
# à toa quando o cookie provavelmente ainda está válido.
NORMALIZAR_VOLUME = True
# Parâmetros de EQ/loudness (antes PEAK_TARGET/EQ_ATIVO fixos aqui) agora
# vivem por preset em eq_presets.py, escolhidos por playlist — ver
# playlists.ler_preset()/definir_preset() e audio.renderizar_audio().


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


# ── Cookies: arquivo cookies.txt OU direto de um navegador ──────────────────
# Alternativa a exportar cookies.txt na mão: o yt-dlp lê os cookies do navegador
# (--cookies-from-browser). Escolha por perfil via `--cookies-browser NOME` (grava
# em perfil.json). Firefox é o mais confiável; Chrome/Edge recentes criptografam
# os cookies de um jeito que o yt-dlp muitas vezes não consegue ler no Windows.
NAVEGADORES_COOKIES = ("firefox", "chrome", "edge", "brave", "opera", "vivaldi", "chromium", "whale")


def arquivo_perfil() -> Path:
    return BASE_DIR / "perfil.json"


def navegador_cookies() -> str | None:
    """Navegador configurado pra fornecer os cookies, ou None (usa o cookies.txt)."""
    import json
    try:
        nome = json.loads(arquivo_perfil().read_text(encoding="utf-8")).get("cookies_do_navegador")
    except (OSError, ValueError, AttributeError):
        return None
    return nome if nome in NAVEGADORES_COOKIES else None


def definir_navegador_cookies(nome: str | None) -> None:
    """Grava (ou, com None, remove) o navegador de cookies deste perfil."""
    import json
    if nome is not None and nome not in NAVEGADORES_COOKIES:
        raise ValueError(f"Navegador desconhecido: {nome}. Opções: {', '.join(NAVEGADORES_COOKIES)}")
    arq = arquivo_perfil()
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            dados = {}
    except (OSError, ValueError):
        dados = {}
    if nome is None:
        dados.pop("cookies_do_navegador", None)
    else:
        dados["cookies_do_navegador"] = nome
    tmp = arq.with_name(arq.name + ".tmp")
    tmp.write_text(json.dumps(dados, indent=4, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, arq)


_CABECALHOS_COOKIES = ("# Netscape HTTP Cookie File", "# HTTP Cookie File")


def cookies_txt_valido() -> bool:
    """True se COOKIES_FILE é um arquivo de cookies no formato Netscape (o único que
    o yt-dlp lê): cabeçalho na 1ª linha e ao menos um cookie de 7 colunas separadas
    por TAB. Barra o erro comum de copiar o TEXTO de uma página (ex.: robots.txt)
    para dentro do arquivo em vez de exportar com a extensão."""
    try:
        with open(COOKIES_FILE, encoding="utf-8", errors="replace") as f:
            linhas = [linha.rstrip("\r\n") for linha in f]
    except OSError:
        return False
    if not linhas or not linhas[0].startswith(_CABECALHOS_COOKIES):
        return False
    # cookies HttpOnly vêm prefixados com "#HttpOnly_" e também contam
    return any(
        linha.count("\t") >= 6 and (not linha.startswith("#") or linha.startswith("#HttpOnly_"))
        for linha in linhas if linha
    )


def _arquivo_cookies_usavel() -> bool:
    return COOKIES_FILE.exists() and cookies_txt_valido()


def cookies_disponiveis() -> bool:
    return navegador_cookies() is not None or _arquivo_cookies_usavel()


def cookies_args() -> list[str]:
    """Argumentos de CLI do yt-dlp pra autenticar (vazio se não há cookies)."""
    nav = navegador_cookies()
    if nav:
        return ["--cookies-from-browser", nav]
    return ["--cookies", str(COOKIES_FILE)] if _arquivo_cookies_usavel() else []


def cookies_params() -> dict:
    """Mesma coisa pra API Python do yt-dlp (YoutubeDL(params))."""
    nav = navegador_cookies()
    if nav:
        return {"cookiesfrombrowser": (nav,)}
    return {"cookiefile": str(COOKIES_FILE)} if _arquivo_cookies_usavel() else {}
