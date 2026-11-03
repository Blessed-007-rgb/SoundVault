import os
import shutil
import subprocess
from typing import Any


def sem_janela() -> dict[str, Any]:
    """Kwargs de subprocess pra não abrir uma janela de console por processo
    no Windows (yt-dlp/ffmpeg/powershell); vazio nos outros sistemas.

    Antes isto era repetido inline como
    `**({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})`
    em 7 lugares, e o tipo misto desse dict gerava ~185 erros de tipagem."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def runtimes_js() -> list[str]:
    """Runtimes JavaScript instalados que o yt-dlp pode usar além do deno.

    O yt-dlp só habilita o `deno` por padrão; com apenas o Node.js instalado
    (que o README manda instalar) ele roda SEM runtime JS, avisa "No supported
    JavaScript runtime" e perde formatos — causa provável de erros como
    "Requested format is not available" e "The page needs to be reloaded"."""
    return [r for r in ("node", "bun") if shutil.which(r)]


def ytdlp_js_args() -> list[str]:
    """Flags de linha de comando: ['--js-runtimes', 'node', ...] (vazio se não há)."""
    args: list[str] = []
    for r in runtimes_js():
        args += ["--js-runtimes", r]
    return args


def ytdlp_js_params() -> dict[str, Any]:
    """Opções equivalentes pra API Python (YoutubeDL(params))."""
    extras = runtimes_js()
    if not extras:
        return {}
    return {"js_runtimes": {"deno": {}, **{r: {} for r in extras}}}
