"""Sync de ponta a ponta: o `sincronizar` real, com o yt-dlp simulado.

Roda a função inteira (cache -> busca de URL -> download -> state -> render ->
playlist -> histórico) sobre um perfil temporário. Só o que sai do computador é
falso: o yt-dlp (grava um MP3 de verdade), a busca de URLs, o teste de cookie, o
auto-update e a notificação do Windows. ffmpeg e mutagen são os reais.
"""
import shutil
import subprocess
import threading
import types
from pathlib import Path

import pytest

from soundvault import audio, config, disco, download, playlists, storage, sync
from soundvault.procutil import ytdlp_js_args

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="precisa de ffmpeg para gerar o MP3 de teste")

GB = 1024 ** 3
_subprocess_run_real = subprocess.run


@pytest.fixture(scope="module")
def mp3_modelo(tmp_path_factory):
    arq = tmp_path_factory.mktemp("modelo") / "modelo.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
                    "-af", "volume=-6dB", "-codec:a", "libmp3lame", "-q:a", "5", str(arq)], check=True)
    return arq


class YtDlpFalso:
    """Substitui subprocess.run SÓ para o yt-dlp (o ffmpeg dos renders segue real)."""

    def __init__(self, modelo: Path):
        self.modelo = modelo
        self.chamadas: list[list[str]] = []
        self.respostas: dict[str, str] = {}      # url -> stderr de erro (ausente = sucesso)

    def __call__(self, cmd, *args, **kwargs):
        if not cmd or cmd[0] != "yt-dlp":
            return _subprocess_run_real(cmd, *args, **kwargs)
        url = cmd[-1]
        self.chamadas.append(list(cmd))
        erro = self.respostas.get(url)
        if erro is None and "--output" in cmd:
            destino = Path(cmd[cmd.index("--output") + 1].replace("%(ext)s", "mp3"))
            shutil.copyfile(self.modelo, destino)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", erro or "ERROR: sem --output")

    def urls_baixadas(self) -> list[str]:
        return [c[-1] for c in self.chamadas]


@pytest.fixture
def ambiente(perfil, monkeypatch, mp3_modelo):
    """Perfil temporário + tudo que acessa a rede/Windows substituído."""
    ytdlp = YtDlpFalso(mp3_modelo)
    monkeypatch.setattr(download.subprocess, "run", ytdlp)
    monkeypatch.setattr(config, "RETRY_DELAY", 0)
    monkeypatch.setattr(config, "MAX_RETRIES", 2)
    monkeypatch.setattr(config, "RENDER_WORKERS", 2)
    monkeypatch.setattr(config, "NOTIFY_ON_FINISH", False)

    def update_falso():
        t = threading.Thread(target=lambda: None)
        t.start()
        return t
    monkeypatch.setattr(sync, "verificar_atualizar_ytdlp", update_falso)     # nunca roda `yt-dlp --update`
    monkeypatch.setattr(sync.cookies, "verificar_cookie_valido", lambda forcar=False: None)
    monkeypatch.setattr("soundvault.console_log.notificar_windows", lambda *a, **k: None)
    monkeypatch.setattr("os.system", lambda *a: 0)                            # o `cls` do início do Sync
    busca = {"resultado": None, "chamadas": []}

    def busca_falsa(chave):
        busca["chamadas"].append(chave)
        return busca["resultado"]
    monkeypatch.setattr(sync, "buscar_ytmusic_detalhado", busca_falsa)
    monkeypatch.setattr("soundvault.search.buscar_ytmusic_detalhado", busca_falsa)
    ytdlp.busca = busca                                                       # type: ignore[attr-defined]
    return ytdlp


def _montar(nomes, com_url=True, playlist="T"):
    """Cria a playlist e (opcionalmente) o cache com uma URL válida para cada música."""
    playlists.criar_playlist(playlist)
    playlists.caminho_playlist_txt(playlist).write_text("\n".join(nomes), encoding="utf-8")
    urls = {}
    for i, n in enumerate(nomes):
        vid = f"id{i:09d}"                                    # 11 caracteres
        urls[n] = f"https://www.youtube.com/watch?v={vid}"
        if com_url:
            storage.salvar_cache_entrada(n, {"url": urls[n], "id": vid})
    return urls


def _arquivos_pool():
    return sorted(p.name for p in config.DOWNLOAD_DIR.glob("*.mp3"))


def _arquivos_playlist(playlist="T"):
    return sorted(p.name for p in playlists.caminho_playlist_musicas(playlist).glob("*.mp3"))


def _nomes_no_state():
    return sorted(v["name"] for v in storage.carregar_state().values() if isinstance(v, dict) and not v.get("skipped"))


def _responder(monkeypatch, resposta):
    """Substitui o Prompt do rich (a resposta pode ser uma exceção para simular EOF)."""
    def ask(*a, **k):
        if isinstance(resposta, Exception):
            raise resposta
        return resposta
    monkeypatch.setattr(sync, "Prompt", types.SimpleNamespace(ask=ask))


def _sem_pergunta(monkeypatch):
    def ask(*a, **k):
        raise AssertionError("o Sync não deveria perguntar nada aqui")
    monkeypatch.setattr(sync, "Prompt", types.SimpleNamespace(ask=ask))


MUSICAS = ["Art1 - Faixa1", "Art2 - Faixa2", "Art3 - Faixa3"]


class TestFluxoCompleto:
    def test_baixa_renderiza_e_registra_tudo(self, ambiente):
        urls = _montar(MUSICAS)
        sync.sincronizar("T")

        assert sorted(ambiente.urls_baixadas()) == sorted(urls.values())      # baixou a URL de cada uma
        assert all(ytdlp_js_args() == [] or "--js-runtimes" in c for c in ambiente.chamadas)
        assert _arquivos_pool() == ["Faixa1 - Art1.mp3", "Faixa2 - Art2.mp3", "Faixa3 - Art3.mp3"]
        assert _nomes_no_state() == sorted(MUSICAS)
        assert _arquivos_playlist() == ["01 - Faixa1 - Art1.mp3", "02 - Faixa2 - Art2.mp3", "03 - Faixa3 - Art3.mp3"]
        assert set(playlists._ler_render_state("T")) == set(MUSICAS)          # renderizou com o ffmpeg real
        assert storage.carregar_falhas() == {}
        ultimo = storage.carregar_historico()[-1]
        assert (ultimo["sucesso"], ultimo["falhas"], ultimo["puladas"]) == (3, 0, 0)
        assert not config.LOCK_FILE.exists()                                  # lock sempre liberado

    def test_o_mp3_do_pool_recebe_titulo_e_artista(self, ambiente):
        from mutagen.id3 import ID3
        _montar(["Art1 - Faixa1"])
        sync.sincronizar("T")
        t = ID3(str(config.DOWNLOAD_DIR / "Faixa1 - Art1.mp3"))
        assert (str(t["TIT2"]), str(t["TPE1"])) == ("Faixa1", "Art1") and not t.getall("APIC")

    def test_segundo_sync_nao_faz_nada(self, ambiente, capsys):
        _montar(MUSICAS)
        sync.sincronizar("T")
        ambiente.chamadas.clear()
        renders_antes = dict(playlists._ler_render_state("T"))
        sync.sincronizar("T")
        assert ambiente.chamadas == []                                        # nada de yt-dlp
        assert playlists._ler_render_state("T") == renders_antes              # nada de render
        assert "já está sincronizado" in capsys.readouterr().out.lower()


class TestBuscaDeUrl:
    def test_musica_sem_url_e_buscada_e_entra_na_revisao(self, ambiente, capsys):
        urls = _montar(["Art1 - Faixa1"], com_url=False)
        ambiente.busca["resultado"] = {"url": urls["Art1 - Faixa1"], "id": "id000000000",
                                       "score": 55.0, "video": "Faixa1 (letra)"}
        sync.sincronizar("T")
        assert ambiente.busca["chamadas"] == ["Art1 - Faixa1"]
        e = storage.carregar_cache()["Art1 - Faixa1"]
        assert (e["auto"], e["score"], e["video"]) == (True, 55.0, "Faixa1 (letra)") and "revisado" not in e
        assert ambiente.urls_baixadas() == [urls["Art1 - Faixa1"]]
        assert "baixa confiança" in capsys.readouterr().out                   # avisa para usar a opção V

    def test_url_achada_com_boa_confianca_nao_gera_aviso(self, ambiente, capsys):
        urls = _montar(["Art1 - Faixa1"], com_url=False)
        ambiente.busca["resultado"] = {"url": urls["Art1 - Faixa1"], "id": "id000000000", "score": 95.0, "video": "v"}
        sync.sincronizar("T")
        assert "baixa confiança" not in capsys.readouterr().out

    def test_url_corrompida_no_cache_e_buscada_de_novo(self, ambiente):
        urls = _montar(["Art1 - Faixa1"], com_url=False)
        import json
        config.CACHE_FILE.write_text(json.dumps({"Art1 - Faixa1": {"url": "https://www.youtube.com/watch?v=_curto", "id": "_curto"}}),
                                     encoding="utf-8")
        ambiente.busca["resultado"] = {"url": urls["Art1 - Faixa1"], "id": "id000000000", "score": 90.0, "video": "v"}
        sync.sincronizar("T")
        assert ambiente.busca["chamadas"] == ["Art1 - Faixa1"]                # a URL ruim não foi usada
        assert ambiente.urls_baixadas() == [urls["Art1 - Faixa1"]]

    def test_nao_achada_fica_de_fora_sem_travar_as_outras(self, ambiente):
        urls = _montar(["Art1 - Faixa1", "Art2 - Faixa2"], com_url=False)
        storage.salvar_cache_entrada("Art2 - Faixa2", {"url": urls["Art2 - Faixa2"], "id": "id000000001"})
        sync.sincronizar("T")                                                 # a busca devolve None para a Faixa1
        assert _nomes_no_state() == ["Art2 - Faixa2"]


class TestFalhas:
    def test_video_indisponivel_sem_alternativa_e_pulado_e_nao_e_retentado(self, ambiente):
        urls = _montar(["Art1 - Faixa1", "Art2 - Faixa2"])
        ambiente.respostas[urls["Art1 - Faixa1"]] = "ERROR: [youtube] x: Video unavailable"
        sync.sincronizar("T")
        assert _nomes_no_state() == ["Art2 - Faixa2"]
        assert any(k.startswith("skip_") for k in storage.carregar_state())
        assert ambiente.urls_baixadas().count(urls["Art1 - Faixa1"]) == 1     # permanente: sem retentativas
        ultimo = storage.carregar_historico()[-1]
        assert (ultimo["sucesso"], ultimo["puladas"], ultimo["falhas"]) == (1, 1, 0)

        ambiente.chamadas.clear()
        sync.sincronizar("T")
        assert ambiente.chamadas == []                                        # a pulada não volta sozinha

    def test_falha_temporaria_vai_para_falhas_e_o_retry_conserta(self, ambiente):
        urls = _montar(["Art1 - Faixa1"])
        ambiente.respostas[urls["Art1 - Faixa1"]] = "ERROR: HTTP Error 503: Service Unavailable"
        sync.sincronizar("T")
        assert list(storage.carregar_falhas()) == ["Art1 - Faixa1"]
        assert ambiente.urls_baixadas().count(urls["Art1 - Faixa1"]) == config.MAX_RETRIES   # tentou e desistiu

        ambiente.respostas.clear()
        sync.sincronizar("T", apenas_falhas=True)
        assert storage.carregar_falhas() == {} and _nomes_no_state() == ["Art1 - Faixa1"]

    def test_falha_de_uma_nao_impede_as_outras_nem_o_render(self, ambiente):
        urls = _montar(MUSICAS)
        ambiente.respostas[urls["Art2 - Faixa2"]] = "ERROR: HTTP Error 503: Service Unavailable"
        sync.sincronizar("T")
        assert _nomes_no_state() == ["Art1 - Faixa1", "Art3 - Faixa3"]
        assert set(playlists._ler_render_state("T")) == {"Art1 - Faixa1", "Art3 - Faixa3"}
        assert list(storage.carregar_falhas()) == ["Art2 - Faixa2"]

    def test_o_lock_e_liberado_mesmo_com_erro_no_meio(self, ambiente, monkeypatch):
        _montar(MUSICAS)
        monkeypatch.setattr(sync.playlists, "reconciliar_links", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quebrou")))
        with pytest.raises(RuntimeError):
            sync.sincronizar("T")
        assert not config.LOCK_FILE.exists()


class TestRemocao:
    def test_musica_tirada_da_playlist_sai_do_pool_do_state_e_da_playlist(self, ambiente):
        _montar(MUSICAS)
        sync.sincronizar("T")
        playlists.caminho_playlist_txt("T").write_text("\n".join(MUSICAS[:2]), encoding="utf-8")
        sync.sincronizar("T")
        assert _arquivos_pool() == ["Faixa1 - Art1.mp3", "Faixa2 - Art2.mp3"]
        assert _nomes_no_state() == sorted(MUSICAS[:2])
        assert _arquivos_playlist() == ["01 - Faixa1 - Art1.mp3", "02 - Faixa2 - Art2.mp3"]

    def test_musica_de_outra_playlist_nao_e_apagada_do_pool(self, ambiente):
        _montar(MUSICAS, playlist="A")
        _montar(MUSICAS[:1], playlist="B")
        sync.sincronizar(None)                                                # todas as playlists
        playlists.caminho_playlist_txt("A").write_text("\n".join(MUSICAS[1:]), encoding="utf-8")
        sync.sincronizar("A")                                                 # tira a Faixa1 de A (B ainda usa)
        assert "Faixa1 - Art1.mp3" in _arquivos_pool()
        assert "01 - Faixa1 - Art1.mp3" in _arquivos_playlist("B")

    def test_muitas_remocoes_pedem_confirmacao_e_nao_apagam_se_recusar(self, ambiente, monkeypatch):
        cinco = [f"Art{i} - Faixa{i}" for i in range(5)]
        _montar(cinco)
        sync.sincronizar("T")
        playlists.caminho_playlist_txt("T").write_text(cinco[0], encoding="utf-8")   # 4 saem: > LIMITE
        _responder(monkeypatch, "N")
        sync.sincronizar("T")
        assert len(_arquivos_pool()) == 5                                     # nada foi apagado

    def test_muitas_remocoes_confirmadas_apagam(self, ambiente, monkeypatch):
        cinco = [f"Art{i} - Faixa{i}" for i in range(5)]
        _montar(cinco)
        sync.sincronizar("T")
        playlists.caminho_playlist_txt("T").write_text(cinco[0], encoding="utf-8")
        _responder(monkeypatch, "S")
        sync.sincronizar("T")
        assert _arquivos_pool() == ["Faixa0 - Art0.mp3"]


class TestEspacoEmDisco:
    @staticmethod
    def _livre(monkeypatch, livre):
        monkeypatch.setattr(disco.shutil, "disk_usage", lambda _p: types.SimpleNamespace(free=livre))

    def test_sem_espaco_e_usuario_recusa_nao_baixa_nada(self, ambiente, monkeypatch, capsys):
        _montar(MUSICAS)
        self._livre(monkeypatch, 50 * 1024 * 1024)                            # 50 MB
        _responder(monkeypatch, "N")
        sync.sincronizar("T")
        assert ambiente.chamadas == [] and _arquivos_pool() == []
        assert "espaço em disco" in capsys.readouterr().out.lower()
        assert not config.LOCK_FILE.exists()

    def test_sem_espaco_mas_usuario_confirma_segue(self, ambiente, monkeypatch):
        _montar(MUSICAS)
        self._livre(monkeypatch, 50 * 1024 * 1024)
        _responder(monkeypatch, "S")
        sync.sincronizar("T")
        assert len(_arquivos_pool()) == 3

    def test_sem_terminal_interativo_aborta_por_seguranca(self, ambiente, monkeypatch):
        _montar(MUSICAS)
        self._livre(monkeypatch, 50 * 1024 * 1024)
        _responder(monkeypatch, EOFError())                                   # agendado/pipe: ninguém responde
        sync.sincronizar("T")
        assert ambiente.chamadas == [] and _arquivos_pool() == []

    def test_espaco_apertado_so_avisa_e_segue_sem_perguntar(self, ambiente, monkeypatch, capsys):
        _montar(MUSICAS)
        self._livre(monkeypatch, disco.estimar(3, 3) + 2 * GB)                # sobra 2 GB: só um aviso
        _sem_pergunta(monkeypatch)
        sync.sincronizar("T")
        assert len(_arquivos_pool()) == 3
        assert "espaço em disco" in capsys.readouterr().out.lower()

    def test_com_folga_nao_diz_nada(self, ambiente, monkeypatch, capsys):
        _montar(MUSICAS)
        self._livre(monkeypatch, 500 * GB)
        _sem_pergunta(monkeypatch)
        sync.sincronizar("T")
        assert "espaço em disco" not in capsys.readouterr().out.lower()

    def test_nada_a_fazer_nao_bloqueia_mesmo_com_disco_cheio(self, ambiente, monkeypatch):
        _montar(MUSICAS)
        sync.sincronizar("T")
        self._livre(monkeypatch, 0)
        _sem_pergunta(monkeypatch)
        ambiente.chamadas.clear()
        sync.sincronizar("T")                                                 # nada novo: não grava nada
        assert ambiente.chamadas == []

    def test_conta_tambem_os_renders_pendentes_sem_downloads(self, ambiente, monkeypatch):
        """Trocar o preset não baixa nada mas re-renderiza tudo: também precisa de espaço."""
        _montar(MUSICAS)
        sync.sincronizar("T")
        playlists.definir_preset("T", "carro")
        self._livre(monkeypatch, 10 * 1024 * 1024)
        _responder(monkeypatch, "N")
        antes = dict(playlists._ler_render_state("T"))
        sync.sincronizar("T")
        assert playlists._ler_render_state("T") == antes                      # abortou: nada foi re-renderizado


def test_audio_continua_o_modulo_real(ambiente):
    """Garante que o teste não está usando um renderizador falso por engano."""
    assert audio.renderizar_audio.__module__ == "soundvault.audio"
