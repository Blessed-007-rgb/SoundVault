"""Leitura da escolha do menu que redesenha quando a janela é redimensionada."""
import pytest

from soundvault import entrada


class Teclado:
    """Teclas simuladas; cada item é uma tecla, ou None = 'nada digitado neste instante'."""
    def __init__(self, passos):
        self.passos = list(passos)
        self.atual = None

    def kbhit(self):
        while self.passos and self.passos[0] is None:
            self.passos.pop(0)
            return False
        return bool(self.passos)

    def getwch(self):
        return self.passos.pop(0)


def _ler(passos, validas=("1", "2", "0", "E"), tamanhos=None, default="1"):
    t = Teclado(passos)
    desenhos, ecos = [], []
    tamanhos = list(tamanhos or [(120, 30)])

    def tamanho():
        return tamanhos.pop(0) if len(tamanhos) > 1 else tamanhos[0]

    resp = entrada.ler_escolha(
        validas, default, lambda buf: desenhos.append(buf),
        kbhit=t.kbhit, getwch=t.getwch, tamanho=tamanho,
        dormir=lambda s: None, escrever=ecos.append,
    )
    return resp, desenhos, "".join(ecos)


def test_digita_e_confirma():
    resp, desenhos, _ = _ler(["2", "\r"])
    assert resp == "2" and desenhos == [""]


def test_enter_vazio_usa_o_padrao():
    assert _ler(["\r"])[0] == "1"


def test_maiuscula_minuscula_normaliza():
    assert _ler(["e", "\r"])[0] == "E"


def test_backspace_apaga_o_ultimo_caractere():
    resp, _, ecos = _ler(["x", "\x08", "2", "\r"])
    assert resp == "2" and "\b \b" in ecos


def test_opcao_invalida_redesenha_e_pede_de_novo():
    resp, desenhos, _ = _ler(["9", "\r", "0", "\r"])
    assert resp == "0" and len(desenhos) == 2          # desenho inicial + após a opção inválida


def test_ctrl_c_vira_keyboardinterrupt():
    with pytest.raises(KeyboardInterrupt):
        _ler(["\x03"])


def test_teclas_especiais_sao_ignoradas():
    # setas/F-keys chegam como prefixo \xe0 (ou \x00) + código
    assert _ler(["\xe0", "H", "2", "\r"])[0] == "2"


def test_redimensionar_redesenha_mantendo_o_que_foi_digitado():
    # digita "2", janela muda de tamanho enquanto espera, depois Enter
    resp, desenhos, _ = _ler(["2", None, None, "\r"], tamanhos=[(120, 30), (120, 30), (170, 40)])
    assert resp == "2"
    assert desenhos == ["", "2"]                        # redesenho recebeu o texto já digitado


def test_sem_mudanca_de_tamanho_nao_redesenha():
    _, desenhos, _ = _ler(["1", None, None, None, "\r"], tamanhos=[(120, 30)])
    assert desenhos == [""]
