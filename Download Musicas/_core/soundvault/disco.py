"""Checagem de espaço em disco antes de um Sync.

O Sync grava cada música duas vezes: o MP3 cru no pool e uma cópia renderizada
(EQ) em cada playlist. Uma playlist grande (a `Sex` tem 152 músicas) pode
encher o disco no meio do caminho e deixar arquivos pela metade; melhor avisar
ANTES de começar.
"""
import shutil
from dataclasses import dataclass

from . import config

GB = 1024 ** 3
OK, AVISO, ERRO = "ok", "aviso", "erro"

MARGEM = 1.25                    # o render (VBR q2) pode ficar maior que o MP3 cru
MEDIA_PADRAO = 7 * 1024 * 1024   # usado quando o pool ainda está vazio
RESERVA_MINIMA = 1 * GB          # depois do Sync sempre tem que sobrar isto
FOLGA_AVISO = 5 * GB             # sobrou menos que isto -> avisa (mas deixa seguir)
_AMOSTRA = 300                   # quantos MP3 do pool entram na média


@dataclass(frozen=True)
class Espaco:
    status: str
    livre: int
    necessario: int
    n_downloads: int
    n_renders: int


def media_mp3() -> int:
    """Tamanho médio (bytes) dos MP3 do pool, ignorando temporários de download."""
    tamanhos = []
    for f in config.DOWNLOAD_DIR.glob("*.mp3"):
        if f.stem.startswith("__dl_"):
            continue
        try:
            tamanhos.append(f.stat().st_size)
        except OSError:
            continue
        if len(tamanhos) >= _AMOSTRA:
            break
    return sum(tamanhos) // len(tamanhos) if tamanhos else MEDIA_PADRAO


def estimar(n_downloads: int, n_renders: int, media: int | None = None) -> int:
    """Bytes a gravar: cada download (pool) e cada render (playlist) ocupa ~1 MP3."""
    media = media_mp3() if media is None else media
    return int((n_downloads + n_renders) * media * MARGEM)


def avaliar(n_downloads: int, n_renders: int, livre: int | None = None, media: int | None = None) -> Espaco:
    necessario = estimar(n_downloads, n_renders, media)
    if livre is None:
        livre = shutil.disk_usage(config.DOWNLOAD_DIR).free
    if necessario == 0:                      # nada a gravar: não há o que bloquear
        status = OK
    else:
        sobra = livre - necessario
        status = ERRO if sobra < RESERVA_MINIMA else AVISO if sobra < FOLGA_AVISO else OK
    return Espaco(status, livre, necessario, n_downloads, n_renders)


def descrever(e: Espaco) -> str:
    return (f"Espaço em disco: {e.livre / GB:.1f} GB livres; este Sync deve gravar cerca de "
            f"{e.necessario / GB:.1f} GB ({e.n_downloads} download(s) + {e.n_renders} render(s)).")
