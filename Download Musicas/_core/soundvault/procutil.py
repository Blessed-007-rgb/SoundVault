import os
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
