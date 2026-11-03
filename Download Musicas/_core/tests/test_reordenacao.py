"""Entrar músicas novas desloca o prefixo numérico (rodízio por artista) de várias
antigas. Elas devem ser RENOMEADAS, nunca re-renderizadas (cada render leva ~8 s)."""
import pytest

from soundvault import audio, config, playlists


@pytest.fixture
def ambiente(perfil, monkeypatch):
    renders = []

    def render_falso(origem, destino, preset):
        renders.append(origem.stem)
        destino.write_bytes(b"render:" + origem.stem.encode())   # conteúdo identifica a música
        return True

    monkeypatch.setattr(audio, "renderizar_audio", render_falso)
    monkeypatch.setattr(config, "RENDER_WORKERS", 2)
    playlists.criar_playlist("T")
    return renders


def _musicas(*nomes):
    """Cria o MP3 cru no pool e escreve o playlist.txt."""
    playlists.caminho_playlist_txt("T").write_text("\n".join(nomes), encoding="utf-8")
    for n in nomes:
        artista, titulo = n.split(" - ", 1)
        (config.DOWNLOAD_DIR / f"{titulo} - {artista}.mp3").write_bytes(b"x" * 20000)


def _arquivos():
    return sorted(p.name for p in playlists.caminho_playlist_musicas("T").glob("*.mp3"))


def test_musica_nova_no_inicio_so_renderiza_a_nova(ambiente):
    renders = ambiente
    _musicas("A - s1", "B - s2", "C - s3")
    assert playlists.reconciliar_links("T")[0] == 3
    antes = {p.name.split(" - ", 1)[1]: p.read_bytes() for p in playlists.caminho_playlist_musicas("T").glob("*.mp3")}
    renders.clear()

    _musicas("N - s0", "A - s1", "B - s2", "C - s3")           # N entra na frente: todo prefixo desloca
    criados, removidos, _ = playlists.reconciliar_links("T")

    assert renders == ["s0 - N"]                               # só a nova foi renderizada
    assert criados == 1 and removidos == 0
    depois = {p.name.split(" - ", 1)[1]: p.read_bytes() for p in playlists.caminho_playlist_musicas("T").glob("*.mp3")}
    for nome, conteudo in antes.items():
        assert depois[nome] == conteudo                        # mesmo arquivo, só renomeado
    assert _arquivos() == ["01 - s0 - N.mp3", "02 - s1 - A.mp3", "03 - s2 - B.mp3", "04 - s3 - C.mp3"]


def test_render_state_acompanha_os_novos_nomes(ambiente):
    _musicas("A - s1", "B - s2")
    playlists.reconciliar_links("T")
    _musicas("N - s0", "A - s1", "B - s2")
    playlists.reconciliar_links("T")
    estado = playlists._ler_render_state("T")
    assert {k: v["file"] for k, v in estado.items()} == {
        "N - s0": "01 - s0 - N.mp3", "A - s1": "02 - s1 - A.mp3", "B - s2": "03 - s2 - B.mp3"}


def test_terceira_rodada_nao_faz_nada(ambiente):
    renders = ambiente
    _musicas("A - s1", "B - s2")
    playlists.reconciliar_links("T")
    _musicas("N - s0", "A - s1", "B - s2")
    playlists.reconciliar_links("T")
    renders.clear()
    assert playlists.reconciliar_links("T") == (0, 0, [])
    assert renders == []


def test_musica_removida_continua_sendo_apagada_e_o_resto_so_renomeia(ambiente):
    renders = ambiente
    _musicas("A - s1", "B - s2", "C - s3")
    playlists.reconciliar_links("T")
    renders.clear()
    _musicas("B - s2", "C - s3")                               # A sai: B e C sobem uma posição
    criados, removidos, _ = playlists.reconciliar_links("T")
    assert (criados, renders) == (0, [])
    assert _arquivos() == ["01 - s2 - B.mp3", "02 - s3 - C.mp3"]
    assert removidos == 1


def test_trocar_o_preset_continua_re_renderizando_tudo(ambiente):
    renders = ambiente
    _musicas("A - s1", "B - s2")
    playlists.reconciliar_links("T")
    renders.clear()
    playlists.definir_preset("T", "carro")                     # hash muda: AÍ sim precisa re-renderizar
    assert playlists.reconciliar_links("T")[0] == 2
    assert sorted(renders) == ["s1 - A", "s2 - B"]


def test_arquivo_travado_cai_no_re_render_em_vez_de_quebrar(ambiente, monkeypatch):
    renders = ambiente
    _musicas("A - s1", "B - s2")
    playlists.reconciliar_links("T")
    renders.clear()
    original = type(playlists.caminho_playlist_musicas("T")).rename

    def rename_travado(self, alvo):
        raise PermissionError("arquivo em uso pelo player")
    monkeypatch.setattr(type(playlists.caminho_playlist_musicas("T")), "rename", rename_travado)
    _musicas("N - s0", "A - s1", "B - s2")
    playlists.reconciliar_links("T")                           # não pode lançar exceção
    monkeypatch.setattr(type(playlists.caminho_playlist_musicas("T")), "rename", original)
    assert _arquivos() == ["01 - s0 - N.mp3", "02 - s1 - A.mp3", "03 - s2 - B.mp3"]  # ficou consistente
    assert "s0 - N" in renders


class TestInterrupcao:
    """Ctrl+C / janela fechada no meio de um render grande não pode jogar fora o progresso."""

    def _preparar(self, ambiente, n):
        _musicas(*[f"Art{i} - Faixa{i}" for i in range(n)])

    def test_progresso_fica_salvo_se_for_interrompido(self, ambiente, monkeypatch):
        renders = ambiente
        monkeypatch.setattr(config, "RENDER_WORKERS", 1)       # 1 por vez: ordem previsível
        self._preparar(ambiente, 8)

        def interrompe_na_terceira(feito, total):
            if feito == 3:
                raise KeyboardInterrupt
        with pytest.raises(KeyboardInterrupt):
            playlists.reconciliar_links("T", interrompe_na_terceira)

        salvos = playlists._ler_render_state("T")
        assert len(salvos) >= 3                                  # o que terminou foi gravado em disco
        renders.clear()
        criados, _, _ = playlists.reconciliar_links("T")         # retomar só faz o que faltava
        assert len(renders) == 8 - len(salvos) and criados == len(renders)
        assert len(playlists._ler_render_state("T")) == 8

    def test_estado_e_gravado_a_cada_musica_pronta(self, ambiente, monkeypatch):
        monkeypatch.setattr(config, "RENDER_WORKERS", 1)
        self._preparar(ambiente, 4)
        tamanhos = []
        playlists.reconciliar_links("T", lambda f, t: tamanhos.append(len(playlists._ler_render_state("T"))))
        assert tamanhos == [0, 1, 2, 3, 4]                       # cresce de 1 em 1, não só no final

    def test_falha_de_uma_musica_nao_impede_de_salvar_as_outras(self, ambiente, monkeypatch):
        self._preparar(ambiente, 3)
        original = audio.renderizar_audio

        def metade_falha(origem, destino, preset):
            if origem.stem == "Faixa1 - Art1":
                raise RuntimeError("ffmpeg quebrou")
            return original(origem, destino, preset)
        monkeypatch.setattr(audio, "renderizar_audio", metade_falha)
        criados, _, _ = playlists.reconciliar_links("T")
        assert criados == 2 and set(playlists._ler_render_state("T")) == {"Art0 - Faixa0", "Art2 - Faixa2"}
