"""Fila de revisão das URLs achadas automaticamente (menu V)."""
import yt_dlp

from soundvault import cache_maint, config, playlists, search, storage


def _auto(url_id, score, video="Vídeo X", **extra):
    return {"url": f"https://www.youtube.com/watch?v={url_id}", "id": url_id,
            "auto": True, "score": score, "video": video, **extra}


def _respostas(monkeypatch, *valores):
    it = iter(valores)
    monkeypatch.setattr(cache_maint, "_perguntar", lambda *_: next(it))


class TestFila:
    def test_so_baixa_confianca_nao_revisada_e_ordenada(self):
        cache = {
            "A - Boa": _auto("aaaaaaaaaaa", 92),
            "B - Fraca": _auto("bbbbbbbbbbb", 55),
            "C - Media": _auto("ccccccccccc", 71),
            "D - Revisada": _auto("ddddddddddd", 40, revisado=True),
            "E - Manual": {"url": "https://youtu.be/eeeeeeeeeee", "id": "eeeeeeeeeee"},
        }
        assert [n for n, _ in cache_maint.pendentes_de_revisao(cache)] == ["B - Fraca", "C - Media"]
        assert [n for n, _ in cache_maint.pendentes_de_revisao(cache, incluir_todas=True)] == ["B - Fraca", "C - Media", "A - Boa"]


class TestRevisar:
    def test_aceitar_marca_como_revisada(self, perfil, monkeypatch):
        storage.salvar_cache_entrada("A - B", _auto("aaaaaaaaaaa", 50))
        _respostas(monkeypatch, "")  # Enter
        cache_maint.revisar_urls_automaticas()
        assert storage.carregar_cache()["A - B"]["revisado"] is True
        assert cache_maint.pendentes_de_revisao(storage.carregar_cache()) == []

    def test_rejeitar_limpa_url_guarda_o_video_e_apaga_o_download(self, perfil, monkeypatch):
        playlists.criar_playlist("P")
        playlists.caminho_playlist_txt("P").write_text("A - B\n", encoding="utf-8")
        storage.salvar_cache_entrada("A - B", _auto("aaaaaaaaaaa", 50))
        pool = config.DOWNLOAD_DIR / "B - A.mp3"
        pool.write_bytes(b"x" * 20000)
        render = playlists.caminho_playlist_musicas("P") / "01 - B - A.mp3"
        render.write_bytes(b"r")
        playlists._salvar_render_state("P", {"A - B": {"preset": "padrao", "hash": "h", "file": render.name}})
        storage.salvar_state({"aaaaaaaaaaa": {"name": "A - B"}, "outro": {"name": "C - D"}})

        _respostas(monkeypatch, "r", "s")  # rejeitar + confirmar a exclusão
        cache_maint.revisar_urls_automaticas()

        e = storage.carregar_cache()["A - B"]
        assert e["url"] == "" and e["rejeitados"] == ["aaaaaaaaaaa"]
        assert not storage.entrada_cache_valida(e)               # o Sync vai buscar de novo
        assert not pool.exists() and not render.exists()
        assert playlists._ler_render_state("P") == {}
        assert list(storage.carregar_state()) == ["outro"]       # só o registro dessa música saiu

    def test_rejeitar_sem_confirmar_nao_apaga_nada(self, perfil, monkeypatch):
        storage.salvar_cache_entrada("A - B", _auto("aaaaaaaaaaa", 50))
        pool = config.DOWNLOAD_DIR / "B - A.mp3"
        pool.write_bytes(b"x" * 20000)
        _respostas(monkeypatch, "r", "n")
        cache_maint.revisar_urls_automaticas()
        assert pool.exists() and storage.carregar_cache()["A - B"]["url"].endswith("aaaaaaaaaaa")

    def test_colar_outra_url(self, perfil, monkeypatch):
        storage.salvar_cache_entrada("A - B", _auto("aaaaaaaaaaa", 50))
        _respostas(monkeypatch, "u", "https://youtu.be/zzzzzzzzzzz")  # sem MP3 baixado -> sem confirmação
        cache_maint.revisar_urls_automaticas()
        e = storage.carregar_cache()["A - B"]
        assert e["id"] == "zzzzzzzzzzz" and e["revisado"] is True and e["rejeitados"] == ["aaaaaaaaaaa"]

    def test_url_invalida_e_pulada_sem_mudar_nada(self, perfil, monkeypatch):
        storage.salvar_cache_entrada("A - B", _auto("aaaaaaaaaaa", 50))
        _respostas(monkeypatch, "u", "lixo")
        cache_maint.revisar_urls_automaticas()
        assert storage.carregar_cache()["A - B"]["id"] == "aaaaaaaaaaa"

    def test_sair_interrompe_sem_alterar(self, perfil, monkeypatch):
        storage.salvar_cache_entrada("A - B", _auto("aaaaaaaaaaa", 50))
        _respostas(monkeypatch, "q")
        cache_maint.revisar_urls_automaticas()
        assert "revisado" not in storage.carregar_cache()["A - B"]

    def test_fim_de_entrada_sai_limpo(self, perfil, monkeypatch):
        storage.salvar_cache_entrada("A - B", _auto("aaaaaaaaaaa", 50))
        _respostas(monkeypatch, None)  # EOF / Ctrl+C
        cache_maint.revisar_urls_automaticas()


class TestRejeitadosNaBusca:
    class _FakeYDL:
        candidatos: list = []
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extract_info(self, q, download=False): return {"entries": list(self.candidatos)}

    def test_busca_pula_video_rejeitado_e_preserva_a_lista(self, perfil, monkeypatch):
        storage.salvar_cache_entrada("G.A - pros menor", {"url": "", "id": "", "rejeitados": ["ruimruimrui"]})
        self._FakeYDL.candidatos = [
            {"id": "ruimruimrui", "title": "pros menor - G.A", "uploader": "G.A"},
            {"id": "boaboaboaboa", "title": "pros menor - G.A (letra)", "uploader": "G.A"},
        ]
        monkeypatch.setattr(yt_dlp, "YoutubeDL", self._FakeYDL)
        det = search.buscar_ytmusic_detalhado("G.A - pros menor")
        assert det is not None and det["id"] == "boaboaboaboa" and 0 < det["score"] <= 100
        entrada = search.entrada_de_busca(det, storage.carregar_cache()["G.A - pros menor"])
        assert entrada["auto"] is True and entrada["rejeitados"] == ["ruimruimrui"]
        # e o salvar_cache_entrada também preserva a lista, mesmo sem 'anterior'
        storage.salvar_cache_entrada("G.A - pros menor", {k: v for k, v in entrada.items() if k != "rejeitados"})
        assert storage.carregar_cache()["G.A - pros menor"]["rejeitados"] == ["ruimruimrui"]

    def test_entrada_de_busca_tem_os_campos_da_revisao(self):
        e = search.entrada_de_busca({"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "id": "aaaaaaaaaaa", "score": 61.5, "video": "V"})
        assert (e["auto"], e["score"], e["video"]) == (True, 61.5, "V") and "rejeitados" not in e


def test_stub_de_rejeicao_e_aceito_mas_nao_conta_como_url_valida():
    stub = {"url": "", "id": "", "rejeitados": ["abc"]}
    assert storage.normalizar_entrada_cache(stub) == stub
    assert not storage.entrada_cache_valida(stub)
    assert storage.normalizar_entrada_cache({"url": ""}) is None
