import time

from soundvault import audio, config, playlists, progresso


def _montar(perfil, n_musicas):
    playlists.criar_playlist("T")
    nomes = [f"Art{i} - Musica{i}" for i in range(n_musicas)]
    playlists.caminho_playlist_txt("T").write_text("\n".join(nomes), encoding="utf-8")
    for nome in nomes:
        titulo, artista = nome.split(" - ")[1], nome.split(" - ")[0]
        (config.DOWNLOAD_DIR / f"{titulo} - {artista}.mp3").write_bytes(b"x" * 20000)


def _render_falso(monkeypatch, falhar=()):
    def f(origem, destino, preset):
        time.sleep(0.05)
        if origem.stem in falhar:
            return False
        destino.write_bytes(b"r")
        return True
    monkeypatch.setattr(audio, "renderizar_audio", f)


class TestCallback:
    def test_reporta_de_zero_ate_o_total_sem_pular(self, perfil, monkeypatch):
        _montar(perfil, 6)
        _render_falso(monkeypatch)
        monkeypatch.setattr(config, "RENDER_WORKERS", 3)
        eventos = []
        playlists.reconciliar_links("T", lambda feito, total: eventos.append((feito, total)))
        assert eventos[0] == (0, 6) and eventos[-1] == (6, 6)
        assert [e[0] for e in eventos] == list(range(7))   # monotônico, de 1 em 1
        assert {e[1] for e in eventos} == {6}

    def test_falha_de_render_tambem_conta_como_andamento(self, perfil, monkeypatch):
        _montar(perfil, 3)
        _render_falso(monkeypatch, falhar={"Musica1 - Art1"})
        eventos = []
        criados, _, _ = playlists.reconciliar_links("T", lambda f, t: eventos.append((f, t)))
        assert criados == 2 and eventos[-1] == (3, 3)  # a barra termina mesmo com falha

    def test_nada_a_renderizar_nao_chama_o_callback(self, perfil, monkeypatch):
        _montar(perfil, 2)
        _render_falso(monkeypatch)
        playlists.reconciliar_links("T")                # 1ª vez renderiza tudo
        eventos = []
        playlists.reconciliar_links("T", lambda f, t: eventos.append((f, t)))
        assert eventos == []                            # tudo pronto -> sem barra

    def test_callback_e_opcional(self, perfil, monkeypatch):
        _montar(perfil, 2)
        _render_falso(monkeypatch)
        assert playlists.reconciliar_links("T")[0] == 2


class TestBarra:
    def test_sem_rich_imprime_inicio_e_fim(self, monkeypatch, capsys):
        monkeypatch.setattr(progresso, "RICH_OK", False)
        with progresso.barra_de_render("Equalizando X") as cb:
            cb(0, 3)
            cb(1, 3)   # dentro de 5 s do anterior: não imprime
            cb(3, 3)
        linhas = [l.strip() for l in capsys.readouterr().out.strip().splitlines()]
        assert linhas == ["Equalizando X: 0/3", "Equalizando X: 3/3"]

    def test_barra_so_abre_quando_chamada(self, monkeypatch):
        abertas = []
        monkeypatch.setattr(progresso, "Progress", lambda *a, **k: abertas.append(1) or _FakeProgress())
        with progresso.barra_de_render("X"):
            pass
        assert abertas == []        # nunca renderizou -> nunca abriu a barra

    def test_barra_atualiza_e_fecha_mesmo_com_excecao(self, monkeypatch):
        falsa = _FakeProgress()
        monkeypatch.setattr(progresso, "RICH_OK", True)
        monkeypatch.setattr(progresso, "Progress", lambda *a, **k: falsa)
        try:
            with progresso.barra_de_render("X") as cb:
                cb(0, 4)
                cb(2, 4)
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            pass
        assert falsa.iniciada and falsa.parada          # Ctrl+C não deixa a barra presa na tela
        assert falsa.ultimo == dict(completed=2, total=4)


class _FakeProgress:
    iniciada = parada = False
    ultimo: dict = {}

    def start(self): self.iniciada = True
    def stop(self): self.parada = True
    def add_task(self, descricao, total): return 0
    def update(self, task, **kw): self.ultimo = kw
