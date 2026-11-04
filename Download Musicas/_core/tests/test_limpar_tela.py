"""limpar_tela(): substitui o os.system("cls") (que abria um subprocesso e, fora de
terminal, jogava lixo/limpava a janela errada)."""
import ast
import io
from pathlib import Path

import pytest

from soundvault import console_log as cl

PACOTE = Path(cl.__file__).parent


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_fora_de_terminal_nao_faz_nada(monkeypatch):
    saida = io.StringIO()                                   # isatty() == False (pipe, arquivo, tarefa agendada)
    monkeypatch.setattr(cl.sys, "stdout", saida)
    limpou = []
    monkeypatch.setattr(cl.console, "clear", lambda *a, **k: limpou.append(1))
    cl.limpar_tela()
    assert limpou == [] and saida.getvalue() == ""


def test_em_terminal_com_rich_usa_o_clear_do_rich(monkeypatch):
    monkeypatch.setattr(cl.sys, "stdout", Tty())
    monkeypatch.setattr(cl, "RICH_OK", True)
    limpou = []
    monkeypatch.setattr(cl.console, "clear", lambda *a, **k: limpou.append(1))
    cl.limpar_tela()
    assert limpou == [1]


def test_em_terminal_sem_rich_empurra_o_conteudo_antigo_para_cima(monkeypatch):
    saida = Tty()
    monkeypatch.setattr(cl.sys, "stdout", saida)
    monkeypatch.setattr(cl, "RICH_OK", False)
    cl.limpar_tela()
    assert saida.getvalue().strip() == "" and saida.getvalue().count("\n") >= 20


def test_nunca_chama_os_system(monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("limpar_tela não deve usar os.system")
    monkeypatch.setattr("os.system", proibido)
    monkeypatch.setattr(cl.sys, "stdout", Tty())
    monkeypatch.setattr(cl.console, "clear", lambda *a, **k: None)
    cl.limpar_tela()


def test_stdout_estranho_nao_derruba(monkeypatch):
    class Quebrado:
        def isatty(self):
            raise ValueError("I/O operation on closed file")
        def write(self, _): return 0
    monkeypatch.setattr(cl.sys, "stdout", Quebrado())
    cl.limpar_tela()                                         # não pode lançar


def _chamadas_os_system(arquivo: Path):
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    return [n.lineno for n in ast.walk(arvore)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "system"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "os"]


@pytest.mark.parametrize("arquivo", sorted(PACOTE.glob("*.py")), ids=lambda p: p.name)
def test_nao_sobrou_os_system_no_pacote(arquivo):
    assert _chamadas_os_system(arquivo) == [], f"{arquivo.name} ainda usa os.system"


def test_no_windows_usa_a_api_do_console_e_nao_o_clear_do_rich(monkeypatch):
    """Regressão: no conhost sem VT o clear do rich deixava o texto antigo na tela."""
    monkeypatch.setattr(cl.sys, "stdout", Tty())
    monkeypatch.setattr(cl.os, "name", "nt")
    monkeypatch.setattr(cl, "_limpar_console_windows", lambda: True)
    limpou = []
    monkeypatch.setattr(cl.console, "clear", lambda *a, **k: limpou.append(1))
    cl.limpar_tela()
    assert limpou == []


def test_se_a_api_falhar_cai_no_clear_do_rich(monkeypatch):
    monkeypatch.setattr(cl.sys, "stdout", Tty())
    monkeypatch.setattr(cl.os, "name", "nt")
    monkeypatch.setattr(cl, "_limpar_console_windows", lambda: False)
    limpou = []
    monkeypatch.setattr(cl.console, "clear", lambda *a, **k: limpou.append(1))
    cl.limpar_tela()
    assert limpou == [1]


def test_api_do_console_sem_console_real_devolve_false():
    assert cl._limpar_console_windows() in (True, False)    # sob pytest (pipe) não pode lançar


def test_chamadas_da_api_do_console_declaram_argtypes():
    """Regressão: sem argtypes o ctypes passou o " " como ponteiro e encheu a tela de lixo."""
    import inspect
    fonte = inspect.getsource(cl._limpar_console_windows)
    for api in ("FillConsoleOutputCharacterW", "FillConsoleOutputAttribute",
                "SetConsoleCursorPosition", "GetConsoleScreenBufferInfo", "GetStdHandle"):
        assert f"{api}.argtypes" in fonte, api
