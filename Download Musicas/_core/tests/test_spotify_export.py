"""Export do Spotify: só SpotAPI (o caminho por navegador/Playwright foi removido)."""
import pytest

from soundvault import playlists, spotify_export as se


def _item(titulo, *artistas):
    return {"itemV2": {"data": {"name": titulo, "artists": {"items": [{"profile": {"name": a}} for a in artistas]}}}}


class FakePlaylist:
    """Imita spotapi.PublicPlaylist: paginate_playlist() devolve páginas (chunks)."""
    paginas: list = []
    erro: Exception | None = None

    def __init__(self, url):
        self.url = url

    def paginate_playlist(self):
        if self.erro:
            raise self.erro
        yield from self.paginas


@pytest.fixture
def spotapi_falso(monkeypatch):
    FakePlaylist.paginas, FakePlaylist.erro = [], None
    monkeypatch.setattr(se, "PublicPlaylist", FakePlaylist)
    monkeypatch.setattr(se, "SPOTAPI_OK", True)
    return FakePlaylist


def test_o_caminho_do_navegador_foi_removido():
    for nome in ("extrair_playlist", "scroll_e_extrair", "esta_logado", "aguardar_login",
                 "verificar_dependencias", "SESSION_DIR", "SCROLL_WAIT"):
        assert not hasattr(se, nome), f"{nome} deveria ter sido removido junto com o Playwright"


class TestExtracao:
    def test_junta_artistas_com_virgula_e_pagina(self, spotapi_falso):
        spotapi_falso.paginas = [
            {"totalCount": 3, "items": [_item("Vida Loka", "Racionais MC's"), _item("Parceria", "A", "B", "C")]},
            {"items": [_item("Solo", "Eminem")]},
        ]
        resultado = se.extrair_via_spotapi("https://open.spotify.com/playlist/x")
        assert resultado is not None
        musicas, total = resultado
        assert musicas == ["Racionais MC's - Vida Loka", "A,B,C - Parceria", "Eminem - Solo"] and total == 3

    def test_ignora_itens_sem_titulo_ou_sem_artista(self, spotapi_falso):
        spotapi_falso.paginas = [{"totalCount": 4, "items": [
            _item("Boa", "X"), _item("", "Y"), _item("SemArtista"), {"itemV2": None}]}]
        resultado = se.extrair_via_spotapi("u")
        assert resultado is not None and resultado[0] == ["X - Boa"]

    def test_falha_devolve_none_sem_levantar(self, spotapi_falso):
        spotapi_falso.erro = RuntimeError("API mudou")
        assert se.extrair_via_spotapi("u") is None

    def test_sem_spotapi_devolve_none(self, monkeypatch):
        monkeypatch.setattr(se, "SPOTAPI_OK", False)
        assert se.extrair_via_spotapi("u") is None


URL = "https://open.spotify.com/playlist/PLAYLIST123"


def _rodar(monkeypatch, *argv):
    monkeypatch.setattr(se.sys, "argv", ["spotify_export", *argv])
    monkeypatch.setattr(se, "OUTPUT_FILE", se._PASTA_EXPORT / "_staging_teste.txt")
    se.main()


class TestMain:
    def test_exporta_e_copia_para_a_playlist(self, perfil, spotapi_falso, monkeypatch):
        playlists.criar_playlist("Treino")
        spotapi_falso.paginas = [{"totalCount": 2, "items": [_item("Um", "A"), _item("Dois", "B")]}]
        _rodar(monkeypatch, URL, "Treino")
        assert playlists.carregar_playlist("Treino") == ["A - Um", "B - Dois"]
        origem = se.carregar_source("Treino")
        assert origem is not None and origem["playlist_id"] == "PLAYLIST123"

    def test_sem_spotapi_para_com_instrucao_e_nao_altera_nada(self, perfil, monkeypatch, capsys):
        playlists.criar_playlist("Treino")
        playlists.caminho_playlist_txt("Treino").write_text("Original - Intacta\n", encoding="utf-8")
        monkeypatch.setattr(se, "SPOTAPI_OK", False)
        with pytest.raises(SystemExit) as e:
            _rodar(monkeypatch, URL, "Treino")
        assert e.value.code == 1 and "pip install spotapi" in capsys.readouterr().out
        assert playlists.carregar_playlist("Treino") == ["Original - Intacta"]

    def test_falha_da_api_nao_cai_em_navegador_e_nao_altera_nada(self, perfil, spotapi_falso, monkeypatch, capsys):
        playlists.criar_playlist("Treino")
        playlists.caminho_playlist_txt("Treino").write_text("Original - Intacta\n", encoding="utf-8")
        spotapi_falso.erro = RuntimeError("playlist privada")
        with pytest.raises(SystemExit) as e:
            _rodar(monkeypatch, URL, "Treino")
        saida = capsys.readouterr().out
        assert e.value.code == 1 and "SpotAPI nao conseguiu" in saida and "compartilhamento restrito" in saida
        assert playlists.carregar_playlist("Treino") == ["Original - Intacta"]

    def test_extracao_incompleta_nao_sobrescreve(self, perfil, spotapi_falso, monkeypatch, capsys):
        playlists.criar_playlist("Treino")
        playlists.caminho_playlist_txt("Treino").write_text("Original - Intacta\n", encoding="utf-8")
        spotapi_falso.paginas = [{"totalCount": 100, "items": [_item("So uma", "A")]}]   # 1% do esperado
        with pytest.raises(SystemExit):
            _rodar(monkeypatch, URL, "Treino")
        assert "extracao incompleta" in capsys.readouterr().out
        assert playlists.carregar_playlist("Treino") == ["Original - Intacta"]

    def test_url_invalida_para_antes_de_chamar_a_api(self, perfil, spotapi_falso, monkeypatch):
        with pytest.raises(SystemExit):
            _rodar(monkeypatch, "https://exemplo.com/nada")
