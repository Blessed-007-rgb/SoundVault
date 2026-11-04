"""Símbolos (✓ ⚠ ✗ e o spinner braille) que o console antigo do Windows (cmd.exe)
mostra como quadrados: nele são trocados por ASCII; no Windows Terminal ficam."""
import io
from typing import Any, cast

import pytest

from soundvault import console_log as cl


class TestDeteccao:
    @pytest.mark.parametrize("env,os_name,esperado", [
        ({}, "nt", True),                                    # cmd.exe / PowerShell clássico (conhost)
        ({"WT_SESSION": "abc"}, "nt", False),                # Windows Terminal: fonte com os símbolos
        ({"TERM_PROGRAM": "vscode"}, "nt", False),           # terminal do VS Code
        ({"ConEmuANSI": "ON"}, "nt", False),
        ({}, "posix", False),                                # Linux/macOS: nunca
        ({"SOUNDVAULT_ASCII": "1"}, "posix", True),          # forçar ligado
        ({"SOUNDVAULT_ASCII": "1", "WT_SESSION": "x"}, "nt", True),
        ({"SOUNDVAULT_ASCII": "0"}, "nt", False),            # forçar desligado (conhost com fonte boa)
    ])
    def test_precisa_ascii(self, env, os_name, esperado):
        assert cl.precisa_ascii(env, os_name) is esperado


class TestTraducao:
    def test_troca_os_simbolos_problematicos(self):
        assert cl.traduzir_simbolos("✓ ok ✗ erro ⚠ aviso ⊘ pulada ↺ retry ↳ filho") == "OK ok X erro ! aviso - pulada ~ retry > filho"

    def test_troca_os_emojis_decorativos(self):
        assert "🧹" not in cl.traduzir_simbolos("🧹 limpeza 🔗 links 🗑 lixo")

    def test_nao_mexe_em_acentos_nem_em_caracteres_de_caixa(self):
        texto = "Já está sincronizado — ação ┌──┐ │ └──┘ · ok"
        assert cl.traduzir_simbolos(texto) == texto

    def test_texto_comum_fica_igual(self):
        assert cl.traduzir_simbolos("Baixando... 4/12") == "Baixando... 4/12"


class TestFluxo:
    def test_traduz_ao_escrever_e_repassa_o_resto(self):
        destino = io.StringIO()
        fluxo = cl.FluxoSimples(destino)
        assert fluxo.write("✓ pronto\n") == len("✓ pronto\n")      # devolve o tamanho ORIGINAL
        fluxo.writelines(["⚠ a\n", "✗ b\n"])
        fluxo.flush()
        assert destino.getvalue() == "OK pronto\n! a\nX b\n"
        assert fluxo.isatty() is False and fluxo.closed is False   # atributos vêm do fluxo real

    def test_rich_imprime_atraves_do_fluxo(self):
        from rich.console import Console
        destino = io.StringIO()
        Console(file=cast(Any, cl.FluxoSimples(destino)), force_terminal=False, width=40).print("[green]✓[/] feito [red]✗[/]")
        assert destino.getvalue().strip() == "OK feito X"


class TestConfigurar:
    @pytest.fixture(autouse=True)
    def _isola(self, monkeypatch):
        monkeypatch.setattr(cl, "SIMBOLOS_SIMPLES", False)

    @staticmethod
    def _fluxos(monkeypatch):
        """Feito DENTRO do teste: o pytest reinstala sys.stdout ao entrar na fase de execução,
        então um patch feito em fixture seria descartado."""
        monkeypatch.setattr(cl.sys, "stdout", io.StringIO())
        monkeypatch.setattr(cl.sys, "stderr", io.StringIO())

    def test_ativa_e_envolve_stdout_e_stderr(self, monkeypatch):
        self._fluxos(monkeypatch)
        assert cl.configurar_simbolos(env={}, os_name="nt") is True
        assert isinstance(cl.sys.stdout, cl.FluxoSimples) and isinstance(cl.sys.stderr, cl.FluxoSimples)
        print("✓ oi")
        assert cl.sys.stdout._destino.getvalue() == "OK oi\n"
        assert cl.SIMBOLOS_SIMPLES is True

    def test_nao_ativa_no_windows_terminal(self, monkeypatch):
        self._fluxos(monkeypatch)
        assert cl.configurar_simbolos(env={"WT_SESSION": "1"}, os_name="nt") is False
        assert not isinstance(cl.sys.stdout, cl.FluxoSimples) and cl.SIMBOLOS_SIMPLES is False

    def test_e_idempotente(self, monkeypatch):
        self._fluxos(monkeypatch)
        cl.configurar_simbolos(env={}, os_name="nt")
        primeiro = cl.sys.stdout
        cl.configurar_simbolos(env={}, os_name="nt")
        assert cl.sys.stdout is primeiro                           # não embrulha duas vezes


class TestSpinner:
    def test_braille_no_console_moderno_e_linha_no_antigo(self, monkeypatch):
        monkeypatch.setattr(cl, "SIMBOLOS_SIMPLES", False)
        assert cl.nome_do_spinner() == "dots"
        monkeypatch.setattr(cl, "SIMBOLOS_SIMPLES", True)
        assert cl.nome_do_spinner() == "line"

    def test_o_spinner_de_linha_so_tem_ascii(self):
        from rich.spinner import Spinner
        assert all(ord(c) < 128 for c in "".join(Spinner("line").frames))


def test_o_programa_liga_a_configuracao_ao_iniciar(monkeypatch):
    from soundvault import __main__ as entrada
    chamadas = []
    monkeypatch.setattr(cl, "configurar_simbolos", lambda *a, **k: chamadas.append(1) or False)
    monkeypatch.setattr(entrada.sys, "argv", ["soundvault", "--help"])
    monkeypatch.setattr("builtins.input", lambda *_: "")
    entrada.main()
    assert chamadas == [1]
