"""Cookies lidos direto do navegador (--cookies-from-browser) como alternativa ao cookies.txt."""
import json

import pytest

from soundvault import config, cookies, download


class TestConfig:
    def test_padrao_sem_navegador_e_sem_arquivo(self, perfil):
        assert config.navegador_cookies() is None
        assert not config.cookies_disponiveis()
        assert config.cookies_args() == [] and config.cookies_params() == {}

    def test_arquivo_cookies_txt(self, perfil):
        config.COOKIES_FILE.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tA\tb\n", encoding="utf-8")
        assert config.cookies_disponiveis()
        assert config.cookies_args() == ["--cookies", str(config.COOKIES_FILE)]
        assert config.cookies_params() == {"cookiefile": str(config.COOKIES_FILE)}

    def test_navegador_tem_prioridade_sobre_o_arquivo(self, perfil):
        config.COOKIES_FILE.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tA\tb\n", encoding="utf-8")
        config.definir_navegador_cookies("firefox")
        assert config.cookies_args() == ["--cookies-from-browser", "firefox"]
        assert config.cookies_params() == {"cookiesfrombrowser": ("firefox",)}

    def test_navegador_funciona_sem_cookies_txt(self, perfil):
        config.definir_navegador_cookies("edge")
        assert config.cookies_disponiveis() and not config.COOKIES_FILE.exists()

    def test_remover_volta_para_o_arquivo(self, perfil):
        config.definir_navegador_cookies("firefox")
        config.definir_navegador_cookies(None)
        assert config.navegador_cookies() is None

    def test_navegador_desconhecido_e_recusado(self, perfil):
        with pytest.raises(ValueError):
            config.definir_navegador_cookies("netscape")
        assert config.navegador_cookies() is None

    def test_perfil_json_corrompido_ou_com_valor_estranho_e_ignorado(self, perfil):
        config.arquivo_perfil().write_text("{ quebrado", encoding="utf-8")
        assert config.navegador_cookies() is None
        config.arquivo_perfil().write_text(json.dumps({"cookies_do_navegador": "internet-explorer"}), encoding="utf-8")
        assert config.navegador_cookies() is None

    def test_preserva_outras_chaves_do_perfil(self, perfil):
        config.arquivo_perfil().write_text(json.dumps({"outra": 1}), encoding="utf-8")
        config.definir_navegador_cookies("brave")
        assert json.loads(config.arquivo_perfil().read_text(encoding="utf-8")) == {"outra": 1, "cookies_do_navegador": "brave"}

    def test_cada_perfil_tem_o_seu(self):
        config.ativar_perfil("pa")
        config.definir_navegador_cookies("firefox")
        config.ativar_perfil("pb")
        assert config.navegador_cookies() is None


def test_download_usa_cookies_do_navegador_no_fallback(perfil, monkeypatch):
    config.definir_navegador_cookies("firefox")
    comandos = []

    class R:
        returncode, stdout = 1, ""
        stderr = "ERROR: Sign in to confirm you're not a bot"

    def falso_run(cmd, **kw):
        comandos.append(cmd)
        return R()
    monkeypatch.setattr(download.subprocess, "run", falso_run)
    monkeypatch.setattr(download.cookies, "solicitar_renovacao_cookies", lambda: None)
    download.baixar("A - B", "https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk", {})
    assert any("--cookies-from-browser" in c and "firefox" in c for c in comandos)   # tentou com os cookies do navegador
    assert any("--cookies-from-browser" not in c for c in comandos)                  # e primeiro sem cookie nenhum


class _Res:
    def __init__(self, rc, err=""):
        self.returncode, self.stderr, self.stdout = rc, err, ""


class TestSaudeDoCookie:
    def _rodar(self, monkeypatch, resultado):
        monkeypatch.setattr(cookies.subprocess, "run", lambda *a, **k: resultado)
        return cookies.verificar_cookie_valido(forcar=True)

    def test_sem_nenhum_cookie_e_inconclusivo(self, perfil, monkeypatch):
        assert self._rodar(monkeypatch, _Res(0)) is None

    def test_navegador_ok(self, perfil, monkeypatch):
        config.definir_navegador_cookies("firefox")
        assert self._rodar(monkeypatch, _Res(0)) is True

    def test_navegador_rejeitado_pelo_youtube(self, perfil, monkeypatch):
        config.definir_navegador_cookies("firefox")
        assert self._rodar(monkeypatch, _Res(1, "ERROR: Sign in to confirm you're not a bot")) is False

    @pytest.mark.parametrize("erro", [
        "ERROR: Could not copy Chrome cookie database",
        "ERROR: Failed to decrypt with DPAPI",
        "ERROR: could not find firefox cookies database in C:/Users/x",
    ])
    def test_nao_conseguir_ler_o_navegador_nao_conta_como_valido(self, perfil, monkeypatch, erro):
        """Regressão em potencial: erro que não é 'auth' era tratado como cookie válido."""
        config.definir_navegador_cookies("chrome")
        assert self._rodar(monkeypatch, _Res(1, erro)) is None


class TestComandoCli:
    def test_configura_e_testa(self, perfil, monkeypatch):
        monkeypatch.setattr(cookies, "verificar_cookie_valido", lambda forcar=False: True)
        assert cookies.configurar_cookies_navegador("Firefox") == 0
        assert config.navegador_cookies() == "firefox"

    def test_falha_no_teste_devolve_1_mas_mantem_a_escolha(self, perfil, monkeypatch):
        monkeypatch.setattr(cookies, "verificar_cookie_valido", lambda forcar=False: None)
        assert cookies.configurar_cookies_navegador("chrome") == 1
        assert config.navegador_cookies() == "chrome"

    def test_nenhum_remove(self, perfil):
        config.definir_navegador_cookies("firefox")
        assert cookies.configurar_cookies_navegador("nenhum") == 0
        assert config.navegador_cookies() is None

    def test_nome_invalido(self, perfil):
        assert cookies.configurar_cookies_navegador("netscape") == 1

    def test_limpa_a_saude_em_cache_do_cookies_txt(self, perfil, monkeypatch):
        cookies._arquivo_health().write_text(json.dumps({"checado_em": "2099-01-01T00:00:00", "valido": True}), encoding="utf-8")
        monkeypatch.setattr(cookies, "verificar_cookie_valido", lambda forcar=False: True)
        cookies.configurar_cookies_navegador("firefox")
        assert not cookies._arquivo_health().exists()

    def test_flag_da_cli(self, perfil, monkeypatch):
        from soundvault import __main__ as entrada
        recebido = []
        monkeypatch.setattr(entrada.sys, "argv", ["soundvault", "--cookies-browser", "firefox"])
        monkeypatch.setattr("soundvault.cookies.configurar_cookies_navegador", lambda n: recebido.append(n) or 0)
        monkeypatch.setattr("builtins.input", lambda *_: "")
        entrada.main()
        assert recebido == ["firefox"]

    def test_flag_sem_valor_mostra_uso(self, perfil, monkeypatch, capsys):
        from soundvault import __main__ as entrada
        monkeypatch.setattr(entrada.sys, "argv", ["soundvault", "--cookies-browser"])
        with pytest.raises(SystemExit) as e:
            entrada.main()
        assert e.value.code == 1 and "Uso: --cookies-browser" in capsys.readouterr().out


ROBOTS = "User-agent: *\nDisallow: /api/\nAllow: /watch\n" * 3
COOKIE_OK = "# Netscape HTTP Cookie File\n# https://curl.haxx.se/rfc/cookie_spec.html\n\n" \
            ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tPREF\tf1=50000000\n"
COOKIE_HTTPONLY = "# Netscape HTTP Cookie File\n#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc\n"


class TestFormatoDoCookiesTxt:
    """Regressão: o usuário colou o TEXTO do robots.txt dentro do cookies.txt."""

    @pytest.mark.parametrize("conteudo,esperado", [
        (COOKIE_OK, True),
        (COOKIE_HTTPONLY, True),                                  # cookies HttpOnly vêm com '#HttpOnly_'
        ("# HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tA\tb\n", True),
        (ROBOTS, False),                                          # o caso real
        ("", False),
        ("# Netscape HTTP Cookie File\n# só comentários\n", False),  # cabeçalho sem nenhum cookie
        (".youtube.com\tTRUE\t/\tTRUE\t0\tA\tb\n", False),         # linhas ok mas sem cabeçalho (o yt-dlp recusa)
    ])
    def test_validacao(self, perfil, conteudo, esperado):
        config.COOKIES_FILE.write_text(conteudo, encoding="utf-8")
        assert config.cookies_txt_valido() is esperado

    def test_arquivo_ausente(self, perfil):
        assert config.cookies_txt_valido() is False

    def test_arquivo_invalido_e_ignorado_nos_argumentos_do_ytdlp(self, perfil):
        config.COOKIES_FILE.write_text(ROBOTS, encoding="utf-8")
        assert config.cookies_args() == [] and config.cookies_params() == {}
        assert not config.cookies_disponiveis()                    # downloads seguem SEM cookies, sem erro

    def test_arquivo_valido_continua_sendo_usado(self, perfil):
        config.COOKIES_FILE.write_text(COOKIE_OK, encoding="utf-8")
        assert config.cookies_args() == ["--cookies", str(config.COOKIES_FILE)]

    def test_detecta_corrompido(self, perfil):
        assert cookies.cookies_txt_corrompido() is False           # sem arquivo: não é "corrompido"
        config.COOKIES_FILE.write_text(ROBOTS, encoding="utf-8")
        assert cookies.cookies_txt_corrompido() is True
        config.COOKIES_FILE.write_text(COOKIE_OK, encoding="utf-8")
        assert cookies.cookies_txt_corrompido() is False
        config.COOKIES_FILE.write_text(ROBOTS, encoding="utf-8")
        config.definir_navegador_cookies("firefox")                # com navegador configurado o arquivo é irrelevante
        assert cookies.cookies_txt_corrompido() is False

    def test_doctor_aponta_o_erro_e_a_correcao(self, perfil):
        from soundvault import doctor
        config.COOKIES_FILE.write_text(ROBOTS, encoding="utf-8")
        c = doctor.checar_cookies(rede=True)
        assert c.status == doctor.ERRO and "NÃO é um arquivo de cookies" in c.detalhe
        assert "Export" in c.dica and "não copie" in c.dica
