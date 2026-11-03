from soundvault.search import _pontuar_candidato, _separar_artistas


class TestSepararArtistas:
    def test_virgula_e_conectores(self):
        assert _separar_artistas("A,B & C feat. D ft. E x F") == ["A", "B", "C", "D", "E", "F"]

    def test_nomes_com_x_dentro_nao_sao_quebrados(self):
        assert _separar_artistas("Alex,Xuxa,Max") == ["Alex", "Xuxa", "Max"]

    def test_vazio(self):
        assert _separar_artistas("Solo") == ["Solo"]


class TestPontuar:
    def test_multiartista_com_uploader_de_um_deles(self):
        # regressão: o artista inteiro era comparado com o uploader e o
        # candidato correto era descartado (89 buscas sem resultado)
        s = _pontuar_candidato(
            "Mc Jacaré,Mc Lele JP,Mc Negão Original,DJ Japa NK", "Carnívoro",
            {"title": "CARNÍVORO", "uploader": "Japa NK"},
        )
        assert s is not None and s >= 70

    def test_titulo_dentro_de_titulo_maior(self):
        s = _pontuar_candidato(
            "Dj Caio Vieira,MC Meno K", "FAMOSINHA",
            {"title": "FAMOSINHA - Dj Caio Vieira · MC Meno K (LETRA)", "uploader": "Canal X"},
        )
        assert s is not None and s >= 70

    def test_musica_diferente_e_descartada(self):
        assert _pontuar_candidato(
            "Eminem", "Venom", {"title": "Receita de bolo de cenoura", "uploader": "Cozinha TV"},
        ) is None

    def test_artista_errado_e_descartado(self):
        assert _pontuar_candidato(
            "Eminem", "Venom", {"title": "Venom", "uploader": "Canal Aleatorio Qualquer"},
        ) is None

    def test_versoes_alternativas_entre_parenteses_sao_penalizadas(self):
        # regressão: o texto entre ()/[] era apagado antes da checagem
        base = _pontuar_candidato("Eminem", "Venom", {"title": "Venom - Eminem", "uploader": "Eminem"})
        assert base is not None
        for marca in ("(Remix)", "[Live]", "(Cover)", "(Sped Up)", "(Slowed + Reverb)"):
            s = _pontuar_candidato("Eminem", "Venom", {"title": f"Venom - Eminem {marca}", "uploader": "Eminem"})
            assert s is not None and s < base, marca

    def test_remix_pedido_nao_e_penalizado(self):
        a = _pontuar_candidato("X", "Song (Remix)", {"title": "Song (Remix) - X", "uploader": "X"})
        b = _pontuar_candidato("X", "Song (Remix)", {"title": "Song - X", "uploader": "X"})
        assert a is not None and b is not None and a >= b

    def test_palavra_proibida_so_vale_como_palavra_inteira(self):
        # "Alive" contém "live", "Discover" contém "cover": não são versões alternativas
        s_alive = _pontuar_candidato("Pearl Jam", "Alive", {"title": "Alive - Pearl Jam", "uploader": "Pearl Jam"})
        s_disc = _pontuar_candidato("Daft Punk", "Discovery", {"title": "Discovery - Daft Punk", "uploader": "Daft Punk"})
        assert s_alive is not None and s_alive > 90
        assert s_disc is not None and s_disc > 90

    def test_artista_curto_nao_casa_por_substring(self):
        # "dj" dentro de "adjetivo" não pode contar como o artista aparecendo no título
        assert _pontuar_candidato("DJ", "Adjetivo Lento", {"title": "Adjetivo Lento", "uploader": "Canal Zzz"}) is None

    def test_entrada_sem_titulo(self):
        assert _pontuar_candidato("A", "B", {"title": "", "uploader": "A"}) is None
