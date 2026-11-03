"""Ctrl+C nunca pode virar traceback — nem na pausa final do menu, nem em
inputs soltos."""
import pytest

from soundvault import __main__ as entrada
from soundvault import menu


def test_ctrl_c_na_pausa_final_do_menu_volta_ao_menu(monkeypatch, capsys):
    escolhas = iter(["H", "0"])
    monkeypatch.setattr(menu, "exibir_menu", lambda: next(escolhas))
    monkeypatch.setattr(menu, "mostrar_help", lambda: None)
    monkeypatch.setattr(menu.config, "verificar_dependencias", lambda: (True, []))

    def input_ctrl_c(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", input_ctrl_c)
    menu.menu()  # não pode propagar KeyboardInterrupt


def test_ctrl_c_em_qualquer_ponto_do_main_encerra_limpo(monkeypatch, capsys):
    monkeypatch.setattr(entrada.sys, "argv", ["soundvault"])

    def menu_interrompido():
        raise KeyboardInterrupt
    monkeypatch.setattr("soundvault.menu.menu", menu_interrompido)
    with pytest.raises(SystemExit) as e:
        entrada.main()
    assert e.value.code == 130
    assert "Traceback" not in capsys.readouterr().out
