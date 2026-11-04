import os
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
    from rich.progress import Progress, SpinnerColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn, TimeRemainingColumn, TextColumn  # noqa: F401
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
    BarColumn = MofNCompleteColumn = TimeElapsedColumn = TimeRemainingColumn = TextColumn = _SemRich  # type: ignore
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


# ── Símbolos para consoles antigos ──────────────────────────────────────────
# O console clássico do Windows (cmd.exe / PowerShell, o "conhost") usa fontes sem
# alguns símbolos Unicode: ✓ ⚠ ✗ e o spinner braille do rich aparecem como quadrados.
# Nele os trocamos por ASCII; no Windows Terminal e no VS Code os símbolos ficam.
# Para forçar: variável de ambiente SOUNDVAULT_ASCII=1 (liga) ou 0 (desliga).
SIMBOLOS_SIMPLES = False

_TABELA_ASCII = str.maketrans({
    "✓": "OK", "✗": "X", "⚠": "!", "⊘": "-", "↺": "~", "↳": ">",
    "🧹": "*", "🔗": "@", "🗑": "x",
})


def precisa_ascii(env, os_name: str) -> bool:
    """True se o console provavelmente não tem fonte para os símbolos Unicode."""
    forcado = env.get("SOUNDVAULT_ASCII")
    if forcado in ("0", "1"):
        return forcado == "1"
    if os_name != "nt":
        return False
    moderno = "WT_SESSION" in env or env.get("TERM_PROGRAM") == "vscode" or "ConEmuANSI" in env
    return not moderno


def traduzir_simbolos(texto: str) -> str:
    return texto.translate(_TABELA_ASCII)


class FluxoSimples:
    """Envolve stdout/stderr e troca os símbolos problemáticos por ASCII ao escrever.
    Todo o resto (isatty, encoding, fileno...) vem do fluxo de verdade."""

    def __init__(self, destino):
        self._destino = destino

    def write(self, texto):
        self._destino.write(traduzir_simbolos(texto))
        return len(texto)

    def writelines(self, linhas):
        for linha in linhas:
            self.write(linha)

    def __getattr__(self, nome):
        return getattr(self._destino, nome)


def configurar_simbolos(env=None, os_name: str | None = None) -> bool:
    """Liga a troca de símbolos se o console precisar. Idempotente. Devolve se ligou."""
    global SIMBOLOS_SIMPLES
    env = os.environ if env is None else env
    os_name = os.name if os_name is None else os_name
    if not precisa_ascii(env, os_name):
        return False
    for nome in ("stdout", "stderr"):
        fluxo = getattr(sys, nome)
        if not isinstance(fluxo, FluxoSimples):
            setattr(sys, nome, FluxoSimples(fluxo))
    SIMBOLOS_SIMPLES = True
    return True


def nome_do_spinner() -> str:
    """Spinner do rich: braille no console moderno, uma barrinha ASCII girando no antigo."""
    return "line" if SIMBOLOS_SIMPLES else "dots"


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


def limpar_tela() -> None:
    """Limpa o terminal. No lugar do antigo os.system("cls"): não abre subprocesso e só
    age em terminal interativo (em pipe/arquivo/tarefa agendada não escreve nada)."""
    try:
        if not sys.stdout.isatty():
            return
    except (AttributeError, ValueError):
        return
    if RICH_OK:
        console.clear()
    else:
        print("\n" * 40)


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
