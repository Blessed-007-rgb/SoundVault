import atexit
import os

from . import config
from .console_log import log, cprint


class LockError(Exception):
    pass


def adquirir_lock():
    if config.LOCK_FILE.exists():
        # Nota: a decisão (bloquear vs. remover como órfão) é calculada
        # ANTES de qualquer print/cprint. UnicodeEncodeError é subclasse de
        # ValueError em Python — se as chamadas de impressão do aviso de
        # "já em andamento" estivessem dentro deste try/except, um console
        # incapaz de exibir os símbolos ✗/⚠ mascarava um LockError real
        # como se fosse um lock órfão, e o programa seguia em frente.
        pid_ativo = None
        try:
            conteudo = config.LOCK_FILE.read_text().strip()
            pid_str = conteudo.split(":")[0]
            pid = int(pid_str)
            import psutil
            if psutil.pid_exists(pid):
                # Bug 19: PID pode ter sido reaproveitado pelo Windows para
                # um processo não relacionado. Confirma que ainda é python
                # antes de bloquear.
                nome_proc = ""
                try:
                    nome_proc = psutil.Process(pid).name().lower()
                except Exception:
                    pass
                if "python" in nome_proc:
                    pid_ativo = pid
                else:
                    config.LOCK_FILE.unlink(missing_ok=True)
                    log.warning(f"Lock órfão removido (PID {pid} pertence a '{nome_proc or 'processo desconhecido'}', não a este programa).")
            else:
                config.LOCK_FILE.unlink(missing_ok=True)
                log.warning(f"Lock órfão removido (PID {pid} não existe mais).")
        except (ValueError, ImportError, IndexError):
            config.LOCK_FILE.unlink(missing_ok=True)
            log.warning("Lock órfão removido (não foi possível verificar PID).")

        if pid_ativo is not None:
            cprint("\n[bold red]✗ Já existe uma execução em andamento.[/]")
            cprint(f"  PID: {pid_ativo} — feche o outro processo ou apague: [yellow]{config.LOCK_FILE}[/]")
            raise LockError("Lock ativo")

    # Bug 2: cria o arquivo atomicamente com O_CREAT|O_EXCL — se outro
    # processo criar o lock entre a checagem acima e esta linha, o open()
    # falha com FileExistsError em vez de as duas execuções seguirem juntas.
    try:
        fd = os.open(config.LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
    except FileExistsError:
        cprint("\n[bold red]✗ Já existe uma execução em andamento (lock criado no mesmo instante).[/]")
        raise LockError("Lock ativo (corrida)")


def liberar_lock():
    config.LOCK_FILE.unlink(missing_ok=True)


def _liberar_lock_atexit():
    config.LOCK_FILE.unlink(missing_ok=True)


atexit.register(_liberar_lock_atexit)
