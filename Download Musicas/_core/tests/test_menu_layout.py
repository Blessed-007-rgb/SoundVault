"""Layout do menu: centraliza conforme a largura da janela e encolhe quando ela é estreita."""
import io

import pytest

from soundvault import menu

rich = pytest.importorskip("rich")


def _desenhar(monkeypatch, largura):
    from rich.console import Console
    saida = io.StringIO()
    c = Console(file=saida, width=largura, force_terminal=False, legacy_windows=False)
    monkeypatch.setattr(menu, "console", c)
    monkeypatch.setattr(menu, "limpar_tela", lambda: None)
    menu._desenhar_menu()
    return saida.getvalue().splitlines()


def _borda_superior(linhas):
    return next(l for l in linhas if "SOUNDVAULT" in l)


def test_janela_larga_centraliza(perfil, monkeypatch):
    linha = _borda_superior(_desenhar(monkeypatch, 180))
    assert len(linha) - len(linha.lstrip()) >= 20          # margem à esquerda


def test_janela_estreita_cabe_sem_estourar(perfil, monkeypatch):
    linhas = _desenhar(monkeypatch, 64)
    assert max(len(l.rstrip()) for l in linhas) <= 64


def test_menu_nao_muda_de_largura_alem_do_necessario(perfil, monkeypatch):
    a = _borda_superior(_desenhar(monkeypatch, 150)).strip()
    b = _borda_superior(_desenhar(monkeypatch, 200)).strip()
    assert a == b                                           # só a margem muda, não o painel
