"""Duas músicas diferentes apontando pro mesmo vídeo: antes, a segunda recebia
'sucesso' sem arquivo e ficava faltando pra sempre."""
import shutil
import subprocess

import pytest

from soundvault import config, download, search, storage

FFMPEG = shutil.which("ffmpeg")


def _mp3(destino, segundos=8):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
         "-codec:a", "libmp3lame", "-q:a", "2", str(destino)],
        check=True,
    )


@pytest.mark.skipif(not FFMPEG, reason="precisa de ffmpeg pra gerar o MP3")
def test_baixar_reaproveita_audio_quando_video_ja_pertence_a_outra_musica(perfil, monkeypatch):
    dono, nova = "Dono - Faixa A", "Outro - Faixa B"
    _mp3(config.DOWNLOAD_DIR / "Faixa A - Dono.mp3")
    url = "https://www.youtube.com/watch?v=PRUdEka4vY0"
    state = {"PRUdEka4vY0": {"name": dono, "url": url}}

    def sem_rede(*a, **k):
        raise AssertionError("não deveria chamar yt-dlp: o áudio já existe")
    monkeypatch.setattr(download.subprocess, "run", sem_rede)
    monkeypatch.setattr(download, "gravar_tags", lambda *a, **k: None)

    ok, tipo, _ = download.baixar(nova, url, "PRUdEka4vY0", state)

    assert (ok, tipo) == (True, "ok")
    assert (config.DOWNLOAD_DIR / "Faixa B - Outro.mp3").exists()
    assert "PRUdEka4vY0" in state and state["PRUdEka4vY0"]["name"] == dono  # dono intacto
    novos = [v for k, v in state.items() if k.startswith("dup_")]
    assert len(novos) == 1 and novos[0]["name"] == nova and novos[0]["duplicate_of"] == "PRUdEka4vY0"


@pytest.mark.skipif(not FFMPEG, reason="precisa de ffmpeg pra gerar o MP3")
def test_segunda_chamada_nao_duplica_registro(perfil, monkeypatch):
    _mp3(config.DOWNLOAD_DIR / "Faixa A - Dono.mp3")
    url = "https://www.youtube.com/watch?v=PRUdEka4vY0"
    state = {"PRUdEka4vY0": {"name": "Dono - Faixa A", "url": url}}
    monkeypatch.setattr(download, "gravar_tags", lambda *a, **k: None)
    download.baixar("Outro - Faixa B", url, "PRUdEka4vY0", state)
    n = len(state)
    assert download.baixar("Outro - Faixa B", url, "PRUdEka4vY0", state)[0] is True
    assert len(state) == n


def test_registro_do_proprio_dono_continua_sendo_sucesso(perfil):
    state = {"abcdefghijk": {"name": "A - B", "url": "u"}}
    assert download.baixar("A - B", "https://youtu.be/abcdefghijk", "abcdefghijk", state) == (True, "ok", "")


class _FakeYDL:
    candidatos = []

    def __init__(self, *a, **k): ...
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, query, download=False): return {"entries": list(self.candidatos)}


def test_busca_ignora_video_que_pertence_a_outra_musica(perfil, monkeypatch):
    import yt_dlp
    storage.salvar_cache_entrada("Santos - Ritmada seu canalha", {"url": "https://youtu.be/PRUdEka4vY0"})
    _FakeYDL.candidatos = [
        {"id": "PRUdEka4vY0", "title": "pros menor da nova - G.A", "uploader": "G.A"},   # já é de outra música
        {"id": "ZZZZZZZZZZZ", "title": "pros menor da nova - G.A (audio)", "uploader": "G.A"},
    ]
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    assert search.buscar_ytmusic("G.A,Veigh - pros menor da nova") == "https://www.youtube.com/watch?v=ZZZZZZZZZZZ"


def test_busca_aceita_video_de_variante_com_mesmo_titulo(perfil, monkeypatch):
    import yt_dlp
    storage.salvar_cache_entrada("A,B - Mega Push", {"url": "https://youtu.be/8WOtOtgw4JU"})
    _FakeYDL.candidatos = [{"id": "8WOtOtgw4JU", "title": "Mega Push - A", "uploader": "A"}]
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    assert search.buscar_ytmusic("A - Mega Push") == "https://www.youtube.com/watch?v=8WOtOtgw4JU"
