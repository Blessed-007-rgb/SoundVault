"""Leitura da escolha do menu que acompanha o redimensionamento da janela.

O `input()`/`Prompt.ask` bloqueia até o Enter, então o menu desenhado numa largura
ficava torto quando a janela era maximizada ou encolhida. Aqui lemos tecla a tecla
(msvcrt, só Windows) e, se o tamanho do terminal mudar enquanto esperamos, redesenhamos
o menu e o texto já digitado. Fora do Windows/terminal quem chama usa o Prompt normal.
"""
import os
import shutil
import sys
import time


def ao_vivo_disponivel() -> bool:
    """True se dá para ler tecla a tecla: Windows, stdin e stdout em terminal de verdade."""
    if os.name != "nt":
        return False
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        import msvcrt  # noqa: F401
    except (ImportError, AttributeError, ValueError):
        return False
    return True


def _tamanho_do_terminal() -> tuple[int, int]:
    t = shutil.get_terminal_size()
    return t.columns, t.lines


def _escrever_stdout(texto: str) -> None:
    sys.stdout.write(texto)
    sys.stdout.flush()


def ler_escolha(validas, default, desenhar, *, kbhit=None, getwch=None, tamanho=None,
                dormir=time.sleep, escrever=None) -> str:
    """Devolve a opção escolhida (em maiúsculas). `desenhar(texto_digitado)` limpa a tela,
    desenha o menu e o prompt já com o texto digitado (sem quebra de linha no fim).
    Enter vazio = `default`; opção fora de `validas` redesenha e pergunta de novo.
    Ctrl+C levanta KeyboardInterrupt."""
    if kbhit is None or getwch is None:
        import msvcrt
        kbhit = kbhit or msvcrt.kbhit
        getwch = getwch or msvcrt.getwch
    tamanho = tamanho or _tamanho_do_terminal
    escrever = escrever or _escrever_stdout
    validas = {v.upper() for v in validas}

    buf = ""
    desenhar(buf)
    ultimo = tamanho()
    while True:
        if kbhit():
            ch = getwch()
            if ch in ("\r", "\n"):
                resposta = (buf or str(default)).strip().upper()
                if resposta in validas:
                    escrever("\n")
                    return resposta
                buf = ""
                desenhar(buf)
            elif ch == "\x03":
                raise KeyboardInterrupt
            elif ch in ("\x00", "\xe0"):
                getwch()                      # tecla especial (seta, F1...): descarta o código
            elif ch in ("\b", "\x7f"):
                if buf:
                    buf = buf[:-1]
                    escrever("\b \b")
            elif ch.isprintable():
                buf += ch
                escrever(ch)
        else:
            dormir(0.05)
            atual = tamanho()
            if atual != ultimo:
                ultimo = atual
                desenhar(buf)
