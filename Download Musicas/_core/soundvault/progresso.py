"""Barra de progresso da equalização (render) das playlists.

Uso:
    with barra_de_render("Equalizando Treino") as cb:
        playlists.reconciliar_links("Treino", cb)

`cb(feito, total)` é chamado por reconciliar_links a cada música renderizada. A
barra só aparece quando há algo pra renderizar (sem piscar à toa quando tudo já
está pronto) e some sozinha ao terminar. O rich só aceita UM display ao vivo por
vez: não abra esta barra dentro de outro `Progress`.
"""
import time
from contextlib import contextmanager
from collections.abc import Generator
from typing import Any

from .console_log import (
    BarColumn, MofNCompleteColumn, Progress, RICH_OK, SpinnerColumn, TextColumn,
    TimeElapsedColumn, TimeRemainingColumn, console, nome_do_spinner,
)


class _Barra:
    def __init__(self, descricao: str):
        self.descricao = descricao
        self._prog: Any = None
        self._task: Any = None
        self._ultimo_print = 0.0

    def __call__(self, feito: int, total: int) -> None:
        if RICH_OK:
            if self._prog is None:
                self._prog = Progress(
                    SpinnerColumn(nome_do_spinner()), TextColumn("[bold blue]{task.description}"),
                    BarColumn(bar_width=34), MofNCompleteColumn(), TimeElapsedColumn(), TimeRemainingColumn(),
                    console=console, transient=True,
                )
                self._prog.start()
                self._task = self._prog.add_task(self.descricao, total=total)
            self._prog.update(self._task, completed=feito, total=total)
        else:
            # Sem rich: uma linha a cada ~5 s e na conclusão, pra não inundar o log.
            agora = time.monotonic()
            if feito == 0 or feito == total or agora - self._ultimo_print >= 5:
                print(f"  {self.descricao}: {feito}/{total}")
                self._ultimo_print = agora

    def fechar(self) -> None:
        if self._prog is not None:
            self._prog.stop()
            self._prog = None


@contextmanager
def barra_de_render(descricao: str) -> Generator[_Barra]:
    barra = _Barra(descricao)
    try:
        yield barra
    finally:
        barra.fechar()
