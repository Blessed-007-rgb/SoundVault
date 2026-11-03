import json
import os
import threading
from pathlib import Path

from . import config
from .console_log import log
from .playlist import extrair_video_id

_state_lock = threading.Lock()
_cache_lock = threading.Lock()


def _escrever_texto_atomico(path: Path, conteudo: str, encoding: str = "utf-8"):
    """
    Escreve um arquivo de forma atômica: grava num .tmp e substitui o
    destino com os.replace() (atômico em Windows/Linux). Evita deixar o
    arquivo truncado/vazio se o processo for interrompido no meio da escrita.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(conteudo, encoding=encoding)
    os.replace(tmp, path)


def _escrever_json_atomico(path: Path, data):
    _escrever_texto_atomico(path, json.dumps(data, indent=4, ensure_ascii=False))


def carregar_historico() -> list:
    if not config.HIST_FILE.exists():
        return []
    try:
        with open(config.HIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def salvar_historico(entrada: dict):
    hist = carregar_historico()
    hist.append(entrada)
    hist = hist[-30:]
    _escrever_json_atomico(config.HIST_FILE, hist)


def carregar_state() -> dict:
    if not config.STATE_FILE.exists():
        return {}
    try:
        with open(config.STATE_FILE, "r", encoding="utf-8") as f:
            conteudo = f.read().strip()
            if not conteudo:
                log.warning("sync_state.json vazio — recriando.")
                return {}
            data = json.loads(conteudo)
            data.pop("downloaded", None)
            return data
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"sync_state.json corrompido ({e}) — fazendo backup e recriando.")
        # Bug 3: usar .replace() em vez de .rename() — no Windows, rename()
        # falha (silenciosamente engolido pelo except abaixo) se já existir
        # um .bak de uma corrupção anterior, descartando o arquivo sem backup.
        bak = config.STATE_FILE.with_suffix(".json.bak")
        try:
            config.STATE_FILE.replace(bak)
            log.info(f"Backup salvo em {bak}")
        except Exception:
            pass
        return {}


def salvar_state(state: dict):
    with _state_lock:
        _escrever_json_atomico(config.STATE_FILE, state)


def carregar_cache() -> dict:
    """
    Carrega o playlist_cache.json — mapa de URLs.
    Formato: {"Artista - Título": {"id": "VIDEO_ID", "url": "https://..."}}
    """
    if not config.CACHE_FILE.exists():
        return {}
    try:
        with open(config.CACHE_FILE, "r", encoding="utf-8-sig") as f:
            conteudo = f.read().strip()
            if not conteudo:
                log.warning("playlist_cache.json vazio.")
                return {}
            return json.loads(conteudo)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(f"playlist_cache.json corrompido ({e}) — fazendo backup e retornando vazio.")
        bak = config.CACHE_FILE.with_suffix(".json.bak")
        try:
            config.CACHE_FILE.replace(bak)
            log.info(f"Backup do cache corrompido salvo em {bak}")
        except Exception:
            pass
        return {}


def normalizar_entrada_cache(dados) -> dict | None:
    """
    Valida uma entrada do playlist_cache.json: a URL precisa conter um ID
    de vídeo de exatamente 11 caracteres. Devolve a entrada com "id"
    sempre igual ao ID extraído da URL (corrige id vazio/divergente), ou
    None se a URL for inválida/corrompida (ex.: ID com 12 caracteres).
    """
    if not isinstance(dados, dict):
        return None
    vid = extrair_video_id(str(dados.get("url", "")))
    if not vid:
        return None
    return {**dados, "id": vid}


def entrada_cache_valida(dados) -> bool:
    """True se a entrada tem URL com ID de vídeo válido E um id coerente."""
    if not isinstance(dados, dict):
        return False
    vid = extrair_video_id(str(dados.get("url", "")))
    return bool(vid) and dados.get("id", vid) in ("", vid)


def salvar_cache_entrada(chave: str, dados: dict) -> bool:
    """
    Atualiza uma única entrada do playlist_cache.json de forma atômica e
    thread-safe. Sem o lock, dois workers de download() em paralelo que
    acham URL alternativa quase ao mesmo tempo fariam
    carregar_cache→modificar→escrever sem exclusão mútua — o segundo a
    escrever sobrescreveria o cache inteiro sem a alteração do primeiro,
    perdendo a URL alternativa dele silenciosamente.
    """
    normalizada = normalizar_entrada_cache(dados)
    if normalizada is None:
        log.warning(f"[CACHE] Entrada recusada (URL/ID de vídeo inválido): {chave}")
        return False
    with _cache_lock:
        cache = carregar_cache()
        cache[chave] = normalizada
        _escrever_json_atomico(config.CACHE_FILE, cache)
    return True


def carregar_falhas() -> dict:
    if not config.FALHAS_FILE.exists():
        return {}
    try:
        with open(config.FALHAS_FILE, "r", encoding="utf-8") as f:
            conteudo = f.read().strip()
            if not conteudo:
                return {}
            return json.loads(conteudo)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def salvar_falhas(falhas: dict):
    if falhas:
        _escrever_json_atomico(config.FALHAS_FILE, falhas)
    elif config.FALHAS_FILE.exists():
        config.FALHAS_FILE.unlink()
