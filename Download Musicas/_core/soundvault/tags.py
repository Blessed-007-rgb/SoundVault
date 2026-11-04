from pathlib import Path
from typing import Any

ID3: Any = None
TIT2: Any = None
TPE1: Any = None
TALB: Any = None
ID3NoHeaderError: Any = None
try:
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, ID3NoHeaderError
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

from .console_log import log


def gravar_tags(caminho: Path, artista: str, titulo: str):
    """Grava título, artista e álbum (= artista) no MP3. Não embute capa."""
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
        tags.save(str(caminho), v2_version=3)
    except Exception as e:
        log.warning(f"Tags falhou em '{caminho.name}': {e}")
