import urllib.request
from pathlib import Path

from typing import Any

ID3: Any = None
TIT2: Any = None
TPE1: Any = None
TALB: Any = None
APIC: Any = None
ID3NoHeaderError: Any = None
try:
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, ID3NoHeaderError
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

from .console_log import log
from .playlist import extrair_video_id


def _baixar_thumbnail(url_video: str) -> bytes | None:
    """Baixa a thumbnail do YouTube e retorna os bytes da imagem."""
    vid = extrair_video_id(url_video)
    if not vid:
        return None
    # urllib em vez de `yt-dlp -o -`: o yt-dlp não baixa URL de imagem direta
    # (trata img.youtube.com/vi/... como página e responde HTTP 404), então
    # nenhuma capa chegava a ser embutida — falha silenciosa em 100% dos MP3.
    for qualidade in ("maxresdefault", "hqdefault", "mqdefault", "default"):
        thumb_url = f"https://img.youtube.com/vi/{vid}/{qualidade}.jpg"
        try:
            req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                dados = resp.read()
            if len(dados) > 1000:
                return dados
        except Exception as e:
            log.debug(f"Thumbnail {qualidade} indisponível para {vid}: {e}")
            continue
    return None


def gravar_tags(caminho: Path, artista: str, titulo: str, url_video: str = ""):
    log.debug(f"gravar_tags: {caminho.name}")
    if not MUTAGEN_OK:
        return
    try:
        try:
            tags = ID3(str(caminho))
        except ID3NoHeaderError:
            tags = ID3()
        tags["TIT2"] = TIT2(encoding=3, text=titulo)
        tags["TPE1"] = TPE1(encoding=3, text=artista)
        tags["TALB"] = TALB(encoding=3, text=artista)

        # A chave real do frame é "APIC:<descrição>" (ex.: "APIC:Cover"),
        # então `"APIC:" not in tags` era sempre verdadeiro e cada regravação
        # empilhava uma capa duplicada. getall() acha qualquer APIC.
        if not tags.getall("APIC") and url_video:
            img_bytes = _baixar_thumbnail(url_video)
            if img_bytes:
                tags.add(APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=img_bytes,
                ))
                log.debug(f"Capa embutida: {caminho.name}")

        tags.save(str(caminho), v2_version=3)
    except Exception as e:
        log.warning(f"Tags falhou em '{caminho.name}': {e}")
