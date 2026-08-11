import os
import subprocess
import threading
import time
from datetime import datetime

from . import config, cookies, search
from .console_log import log
from .playlist import parsear, nome_arquivo, checar_integridade, calcular_md5, sanitizar, classificar_erro, extrair_video_id, ERROS_REDE
from .storage import _state_lock, salvar_cache_entrada
from .tags import gravar_tags

_workers_ativos = 3
_rate_limit_lock = threading.Lock()
_rate_limit_hits = 0


def baixar(chave: str, url: str, video_id: str, state: dict) -> tuple[bool, str, str]:
    """
    Tenta baixar uma música.

    Retorna (sucesso, tipo_resultado, mensagem):
      (True,  'ok',        '')
      (False, 'auth',      motivo)   → cookie expirado
      (False, 'permanent', motivo)   → copyright/removido, não retentar
      (False, 'retry',     motivo)   → erro temporário, pode retentar
    """
    global _workers_ativos, _rate_limit_hits

    artista, titulo = parsear(chave)
    nf = nome_arquivo(artista, titulo)
    destino = config.DOWNLOAD_DIR / f"{nf}.mp3"

    # Cache antigo/importado (ex: TuneMyMusic) pode ter "id": "" mesmo com
    # a URL contendo o ID — sem esse fallback, baixar() baixava o arquivo
    # com sucesso mas nunca registrava em sync_state.json (todo `if
    # video_id:` abaixo ficava falso), fazendo a Auditoria reportar a
    # música como "faltando" pra sempre, mesmo já baixada.
    if not video_id:
        video_id = extrair_video_id(url)

    if video_id and video_id in state:
        return True, "ok", ""

    if checar_integridade(destino):
        if video_id and video_id not in state:
            with _state_lock:
                state[video_id] = {
                    "name": chave, "url": url,
                    "downloaded_at": datetime.now().isoformat()
                }
        return True, "ok", ""

    temp_id = threading.get_ident()
    temp_base = sanitizar(f"__dl_{nf}_{temp_id}")
    temp_tmpl = str(config.DOWNLOAD_DIR / f"{temp_base}.%(ext)s")

    _base_args = [
        "yt-dlp",
        "--format", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "--output", temp_tmpl,
        "--no-playlist",
        "--quiet",
        "--no-part",
    ]
    cmd_com_cookies = _base_args + (["--cookies", str(config.COOKIES_FILE)] if config.COOKIES_FILE.exists() else [])
    cmd_sem_cookies = _base_args[:]
    cmd = cmd_sem_cookies + [url]
    _cmd_com_cookies_url = cmd_com_cookies + [url]

    ultimo_erro = ""
    ultimo_tipo = "retry"

    # Bug 9: encoding explícito — sem isso, o Windows usa o codepage do
    # console (ex: cp1252), que pode não decodificar a saída UTF-8 do
    # yt-dlp (títulos acentuados, símbolos), lançando UnicodeDecodeError
    # não tratado e pulando toda a lógica de retry/classificação de erro.
    _subproc_kwargs = dict(
        capture_output=True, text=True, timeout=config.TIMEOUT_DL,
        encoding="utf-8", errors="replace",
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})
    )

    for tentativa in range(1, config.MAX_RETRIES + 1):
        try:
            result = subprocess.run(cmd, **_subproc_kwargs)
            if result.returncode != 0:
                _tipo_inicial = classificar_erro(result.stderr.strip())
                if _tipo_inicial in ("auth", "format") and cmd == cmd_sem_cookies + [url]:
                    log.debug(f"[AUTH FALLBACK] Tentando com cookies: {chave}")
                    result = subprocess.run(_cmd_com_cookies_url, **_subproc_kwargs)
        except subprocess.TimeoutExpired:
            ultimo_erro = f"Timeout após {config.TIMEOUT_DL}s"
            ultimo_tipo = "retry"
            if tentativa < config.MAX_RETRIES:
                time.sleep(config.RETRY_DELAY * tentativa)
            continue

        stderr = result.stderr.strip()
        tipo = classificar_erro(stderr)

        if tipo in ("permanent", "format"):
            motivo_original = stderr.split("\n")[-1] if stderr else "vídeo indisponível"
            log.warning(f"[COPYRIGHT] {chave} — tentando YouTube Music como alternativa...")
            alt_url = search.buscar_ytmusic(chave)
            if alt_url:
                log.info(f"[ALT] URL alternativa encontrada: {alt_url}")
                # Bug (achado nesta revisão): cmd_alt era montado a partir de
                # `cmd`, que é sempre cmd_sem_cookies — mesmo quando
                # cookies.txt existe. Isso deixava o fallback "sem cookies"
                # logo abaixo inatingível (_cookie_idx sempre -1) e a URL
                # alternativa nunca tentava com cookies, reduzindo a chance
                # de sucesso em vídeos que exigem login.
                if config.COOKIES_FILE.exists():
                    cmd_alt = cmd_com_cookies + [alt_url]
                    cmd_alt_anon = cmd_sem_cookies + [alt_url]
                else:
                    cmd_alt = cmd_sem_cookies + [alt_url]
                    cmd_alt_anon = None
                try:
                    r2 = subprocess.run(cmd_alt, **_subproc_kwargs)
                    if r2.returncode != 0 and cmd_alt_anon:
                        _tipo_alt = classificar_erro(r2.stderr.strip())
                        if _tipo_alt in ("format", "retry"):
                            log.info(f"[ALT] Tentando sem cookies (PO token fallback): {chave}")
                            r2 = subprocess.run(cmd_alt_anon, **_subproc_kwargs)
                    if r2.returncode == 0:
                        mp3 = config.DOWNLOAD_DIR / f"{temp_base}.mp3"
                        if not mp3.exists():
                            candidatos = sorted(config.DOWNLOAD_DIR.glob(f"{temp_base}.*"), key=lambda f: f.stat().st_mtime)
                            mp3 = candidatos[-1] if candidatos else None
                        if mp3:
                            # Bug 1: os.replace() em vez de mp3.rename() —
                            # no Windows, rename() falha com
                            # FileExistsError se `destino` já existir
                            # (arquivo corrompido de execução anterior),
                            # fazendo a música falhar pra sempre em todo
                            # Sync seguinte.
                            os.replace(mp3, destino)
                            if checar_integridade(destino):
                                gravar_tags(destino, artista, titulo, url_video=alt_url)
                                # video_id pode vir vazio quando a música original
                                # também tinha sido resolvida por busca automática
                                # (cache com "id": "") — sem extrair o ID da
                                # alt_url aqui, a música nunca seria registrada em
                                # sync_state.json e seria retentada em todo Sync.
                                alt_video_id = video_id or extrair_video_id(alt_url)
                                if alt_video_id:
                                    h = calcular_md5(destino)
                                    with _state_lock:
                                        state[alt_video_id] = {
                                            "name": chave, "url": alt_url,
                                            "hash": h,
                                            "downloaded_at": datetime.now().isoformat(),
                                            "alt_source": True,
                                        }
                                try:
                                    salvar_cache_entrada(chave, {"url": alt_url, "id": extrair_video_id(alt_url)})
                                    log.info(f"[CACHE] URL alternativa salva para: {chave}")
                                except Exception as _ce:
                                    log.warning(f"[CACHE] Falha ao salvar URL alternativa: {_ce}")
                                log.info(f"[ALT OK] {chave} baixada via YouTube Music")
                                return True, "ok", ""
                except Exception as e_alt:
                    log.warning(f"[ALT FALHOU] {chave}: {e_alt}")
            log.warning(f"[SKIP] {chave}: {motivo_original}")
            for t in config.DOWNLOAD_DIR.glob(f"{temp_base}.*"):
                t.unlink(missing_ok=True)
            return False, "permanent", motivo_original

        if tipo == "rate":
            with _rate_limit_lock:
                _rate_limit_hits += 1
                if _workers_ativos > 1:
                    _workers_ativos = max(1, _workers_ativos - 1)
                    log.warning(f"[429] Rate limit detectado — reduzindo para {_workers_ativos} worker(s)")
            delay = config.RETRY_DELAY * tentativa * 3
            time.sleep(delay)
            continue

        if tipo == "auth":
            log.warning(f"[AUTH] Cookie expirado detectado em: {chave}")
            for t in config.DOWNLOAD_DIR.glob(f"{temp_base}.*"):
                t.unlink(missing_ok=True)
            threading.Thread(target=cookies.solicitar_renovacao_cookies, daemon=True).start()
            return False, "auth", "Cookie expirado ou inválido"

        if result.returncode != 0:
            ultimo_erro = stderr.split("\n")[-1] if stderr else "erro desconhecido"
            ultimo_tipo = "retry"
            log.warning(f"Tentativa {tentativa}/{config.MAX_RETRIES} falhou: {chave} — {ultimo_erro}")
            if tentativa < config.MAX_RETRIES:
                _e_lower = ultimo_erro.lower()
                _backoff = config.RETRY_DELAY * tentativa * 3 if any(e in _e_lower for e in ERROS_REDE) else config.RETRY_DELAY * tentativa
                if _backoff > config.RETRY_DELAY * tentativa:
                    log.info(f"[REDE] Aguardando {_backoff}s antes de retentar (erro de rede)...")
                time.sleep(_backoff)
            continue

        mp3 = config.DOWNLOAD_DIR / f"{temp_base}.mp3"
        if not mp3.exists():
            candidatos = sorted(config.DOWNLOAD_DIR.glob(f"{temp_base}.*"), key=lambda f: f.stat().st_mtime)
            mp3 = candidatos[-1] if candidatos else None
        if not mp3:
            ultimo_erro = "arquivo não encontrado após download"
            continue

        try:
            os.replace(mp3, destino)  # bug 1
        except Exception as e:
            ultimo_erro = f"erro ao renomear: {e}"
            continue

        if not checar_integridade(destino):
            destino.unlink(missing_ok=True)
            ultimo_erro = "arquivo corrompido ou vazio"
            continue

        gravar_tags(destino, artista, titulo, url_video=url)

        if video_id:
            h = calcular_md5(destino)
            with _state_lock:
                state[video_id] = {
                    "name": chave,
                    "url": url,
                    "hash": h,
                    "downloaded_at": datetime.now().isoformat(),
                }

        log.info(f"OK: {chave}")
        return True, "ok", ""

    for t in config.DOWNLOAD_DIR.glob(f"{temp_base}.*"):
        t.unlink(missing_ok=True)
    log.error(f"FALHOU após {config.MAX_RETRIES} tentativas: {chave} — {ultimo_erro}")
    return False, ultimo_tipo, ultimo_erro
