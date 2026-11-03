import re
import sys
import logging
import subprocess
from typing import Any
from logging.handlers import RotatingFileHandler

# Corrige na raiz, em vez de remendar console.print() por console.print():
# num console legado sem UTF-8 de verdade (comum quando o processo roda
# via pipe/não-interativo, mesmo com chcp 65001), QUALQUER emoji/símbolo
# fora do cp1252 derrubava o programa com UnicodeEncodeError — inclusive
# o próprio handler de erro do __main__.py, ao tentar imprimir o
# traceback que contém a linha de código-fonte com o emoji. errors=
# "replace" troca o caractere problemático por "?" em vez de travar.
for _stream in (sys.stdout, sys.stderr):
    try:
        getattr(_stream, "reconfigure")(errors="replace")
    except (AttributeError, ValueError):
        pass  # stream sem reconfigure() (ex: redirecionado pra algo exótico) — ignora

try:
    from rich.console import Console, Group  # noqa: F401  (reexportados pros outros módulos)
    from rich.table import Table  # noqa: F401
    from rich.panel import Panel  # noqa: F401
    from rich.progress import Progress, SpinnerColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn, TextColumn  # noqa: F401
    from rich.prompt import Prompt  # noqa: F401
    from rich.text import Text  # noqa: F401
    from rich import box  # noqa: F401
    RICH_OK = True
except ImportError:
    RICH_OK = False

    class _SemRich:
        """Substituto quando o pacote 'rich' não está instalado. Todo ponto
        de uso do rich no projeto é protegido por `if RICH_OK:`, então isto
        nunca chega a ser instanciado — só mantém os nomes sempre definidos
        pra os módulos poderem importá-los daqui sem import condicional."""
        def __init__(self, *args, **kwargs):
            raise RuntimeError("O pacote 'rich' não está instalado (pip install rich).")

    Console = Group = Table = Panel = Progress = SpinnerColumn = _SemRich  # type: ignore
    BarColumn = MofNCompleteColumn = TimeElapsedColumn = TextColumn = _SemRich  # type: ignore
    Prompt = Text = box = _SemRich  # type: ignore

from . import config
from .procutil import sem_janela


class _ConsoleSimples:
    """console.print() sem rich: imprime o texto sem as marcações [cor]...[/]."""
    def print(self, *args, **kwargs):
        texto = " ".join(str(a) for a in args)
        print(re.sub(r'\[/?[^\]]+\]', '', texto))


# Any: é um rich.Console de verdade quando RICH_OK, ou o substituto simples.
console: Any = Console() if RICH_OK else _ConsoleSimples()
log = logging.getLogger("soundvault")
_logging_inicializado = False


def notificar_windows(titulo: str, mensagem: str):
    """Envia notificação toast no Windows via PowerShell. Não bloqueia."""
    if not config.NOTIFY_ON_FINISH:
        return
    try:
        titulo_s   = titulo.replace("'", "")
        mensagem_s = mensagem.replace("'", "")
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$n = New-Object System.Windows.Forms.NotifyIcon; "
            "$n.Icon = [System.Drawing.SystemIcons]::Information; "
            "$n.Visible = $true; "
            f"$n.ShowBalloonTip(3000, '{titulo_s}', '{mensagem_s}', "
            "[System.Windows.Forms.ToolTipIcon]::Info); "
            "Start-Sleep -Milliseconds 3500; $n.Dispose()"
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **sem_janela()
        )
    except Exception:
        pass  # notificação é opcional


def init_logging():
    """Inicializa (ou reinicializa) handlers de logging para o perfil ativo."""
    global _logging_inicializado
    root = logging.getLogger()
    for h in root.handlers[:]:
        try:
            h.close()
        except Exception:
            pass
        root.removeHandler(h)

    config.DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)

    class _SecaoFormatter(logging.Formatter):
        _ICONES = {
            "DEBUG":    "·",
            "INFO":     "✓",
            "WARNING":  "⚠",
            "ERROR":    "✗",
            "CRITICAL": "!!",
        }
        def format(self, record):
            icone = self._ICONES.get(record.levelname, " ")
            base = (
                f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} "
                f"{icone} [{record.levelname:<8}] "
                f"{record.funcName}:{record.lineno} — "
                f"{record.getMessage()}"
            )
            if record.exc_info:
                base += "\n" + self.formatException(record.exc_info)
            return base

    h = RotatingFileHandler(
        config.DEBUG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    h.setLevel(logging.DEBUG)
    h.setFormatter(_SecaoFormatter())

    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    _logging_inicializado = True


def cprint(msg, **kwargs):
    if RICH_OK:
        try:
            console.print(msg, **kwargs)
            return
        except UnicodeEncodeError:
            # Console legado do Windows (codepage cp1252 etc) não consegue
            # exibir símbolos como ✗/⚠/✓ — cai para texto puro em vez de
            # derrubar o programa inteiro por causa de um print decorativo.
            pass
    texto_puro = re.sub(r'\[/?[^\]]+\]', '', msg)
    print(texto_puro.encode("ascii", "replace").decode("ascii"))
