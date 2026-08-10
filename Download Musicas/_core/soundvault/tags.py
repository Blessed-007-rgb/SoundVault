import os
import re
import subprocess
from pathlib import Path

try:
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, ID3NoHeaderError
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

from .console_log import log


def _baixar_thumbnail(url_video: str) -> bytes | None:
    """Baixa a thumbnail do YouTube e retorna os bytes da imagem."""
    m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url_video)
    if not m:
        return None
    vid = m.group(1)
    for qualidade in ("maxresdefault", "hqdefault", "mqdefault", "default"):
        thumb_url = f"https://img.youtube.com/vi/{vid}/{qualidade}.jpg"
        try:
            result = subprocess.run(
                ["yt-dlp", "--quiet", "--no-warnings", "-o", "-", thumb_url],
                capture_output=True, timeout=10,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})
            )
            if result.returncode == 0 and len(result.stdout) > 1000:
                return result.stdout
        except Exception:
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

        if "APIC:" not in tags and url_video:
            img_bytes = _baixar_thumbnail(url_video)
            if img_bytes:
                tags["APIC:"] = APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=img_bytes,
                )
                log.debug(f"Capa embutida: {caminho.name}")

        tags.save(str(caminho), v2_version=3)
    except Exception as e:
        log.warning(f"Tags falhou em '{caminho.name}': {e}")
