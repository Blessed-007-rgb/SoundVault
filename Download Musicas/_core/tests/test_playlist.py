import pytest

from soundvault.playlist import (
    carregar_playlist, classificar_erro, detectar_colisoes, extrair_video_id,
    nome_arquivo, parsear, sanitizar,
)


class TestExtrairVideoId:
    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=xLQ1QkGB6bk",
        "https://music.youtube.com/watch?v=xLQ1QkGB6bk&list=PLabc",
        "https://youtu.be/xLQ1QkGB6bk?t=5",
        "https://www.youtube.com/watch?feature=share&v=xLQ1QkGB6bk",
    ])
    def test_urls_validas(self, url):
        assert extrair_video_id(url) == "xLQ1QkGB6bk"

    def test_id_com_12_caracteres_e_rejeitado(self):
        # regressão: "_xLQ1QkGB6bk" virava "_xLQ1QkGB6b" e o download falhava
        assert extrair_video_id("https://www.youtube.com/watch?v=_xLQ1QkGB6bk") == ""

    @pytest.mark.parametrize("url", ["", "lixo", "https://www.youtube.com/watch?v=abc", "https://exemplo.com/"])
    def test_urls_invalidas(self, url):
        assert extrair_video_id(url) == ""

    def test_id_com_hifen_e_underscore(self):
        assert extrair_video_id("https://youtu.be/_-aB3_-xYz9") == "_-aB3_-xYz9"


class TestClassificarErro:
    @pytest.mark.parametrize("msg,esperado", [
        ("ERROR: [youtube] x: This video is unavailable", "permanent"),
        ("ERROR: [youtube] x: This video is not available", "permanent"),
        ("ERROR: Video unavailable", "permanent"),
        ("This video contains content, copyright claim", "permanent"),
        ("ERROR: Sign in to confirm you're not a bot", "auth"),
        ("Requested format is not available", "format"),
        ("The page needs to be reloaded.", "format"),
        ("HTTP Error 429: Too Many Requests", "rate"),
        ("HTTP Error 503: Service Unavailable", "retry"),
        ("Connection reset by peer", "retry"),
        ("", "retry"),
    ])
    def test_classificacao(self, msg, esperado):
        assert classificar_erro(msg) == esperado

    def test_403_nao_e_cookie_expirado(self):
        # 403 costuma ser throttling/PO token; tratar como auth disparava
        # o aviso de "cookie expirado" à toa
        assert classificar_erro("HTTP Error 403: Forbidden") == "retry"


class TestNomes:
    def test_parsear(self):
        assert parsear("A,B - Título - Remix") == ("A,B", "Título - Remix")
        assert parsear("SemSeparador") == ("SemSeparador", "SemSeparador")

    def test_sanitizar_remove_caracteres_proibidos_no_windows(self):
        assert sanitizar('a\\b/c*d?e:f"g<h>i|j') == "abcdefghij"

    def test_nome_arquivo(self):
        assert nome_arquivo("Artista", "Título?") == "Título - Artista"

    def test_colisoes(self):
        r = detectar_colisoes(["A - B?C", "A - BC", "X - Y"])
        assert list(r.values()) == [["A - B?C", "A - BC"]]

    def test_nomes_de_arquivo_cabem_no_limite_de_componente_do_windows(self):
        """Nenhuma chave realista pode gerar um nome >255 chars. Cobre o pior
        caso: ~10 artistas, prefixo numérico, sufixo .render.mp3."""
        artistas = ",".join(f"MC Artista Numero {i}" for i in range(10))
        arq = f"001 - {nome_arquivo(artistas, 'SET BOCA 09 (feat. ' + artistas + ')')}.render.mp3"
        assert len(arq) <= 255, f"{len(arq)} chars — nomes assim falhariam no Windows"


def test_carregar_playlist_ignora_comentarios_vazios_e_bom(tmp_path):
    f = tmp_path / "p.txt"
    f.write_bytes("﻿# comentário\n\nA - B\n  C - D  \n".encode("utf-8"))
    assert carregar_playlist(f) == ["A - B", "C - D"]
    assert carregar_playlist(tmp_path / "nao_existe.txt") == []
