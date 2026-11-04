"""Checagem de espaço em disco ANTES de um Sync (downloads + renders)."""
import pytest

from soundvault import audio, config, disco, playlists

GB = 1024 ** 3
MB = 1024 ** 2


class TestEstimativa:
    def test_soma_downloads_e_renders_com_margem(self):
        assert disco.estimar(2, 3, media=10) == int(5 * 10 * disco.MARGEM)

    def test_media_usa_o_tamanho_real_do_pool(self, perfil):
        for i, tamanho in enumerate((2 * MB, 4 * MB, 6 * MB)):
            (config.DOWNLOAD_DIR / f"m{i}.mp3").write_bytes(b"x" * tamanho)
        assert disco.media_mp3() == 4 * MB

    def test_pool_vazio_usa_o_padrao(self, perfil):
        assert disco.media_mp3() == disco.MEDIA_PADRAO

    def test_ignora_temporarios_de_download(self, perfil):
        (config.DOWNLOAD_DIR / "bom.mp3").write_bytes(b"x" * 3 * MB)
        (config.DOWNLOAD_DIR / "__dl_lixo.mp3").write_bytes(b"x" * 50 * MB)
        assert disco.media_mp3() == 3 * MB


class TestAvaliar:
    MEDIA = 10 * MB

    def _necessario(self, d, r):
        return disco.estimar(d, r, media=self.MEDIA)

    def test_sem_nada_a_fazer_nunca_bloqueia(self):
        assert disco.avaliar(0, 0, livre=0, media=self.MEDIA).status == disco.OK

    def test_cabe_com_folga(self):
        assert disco.avaliar(10, 10, livre=100 * GB, media=self.MEDIA).status == disco.OK

    def test_sobra_pouco_apos_o_sync_avisa(self):
        livre = self._necessario(10, 10) + 2 * GB          # sobra 2 GB: < FOLGA_AVISO, > RESERVA
        e = disco.avaliar(10, 10, livre=livre, media=self.MEDIA)
        assert e.status == disco.AVISO and e.livre == livre

    def test_nao_cabe_e_erro(self):
        e = disco.avaliar(10, 10, livre=self._necessario(10, 10) - 1, media=self.MEDIA)
        assert e.status == disco.ERRO

    def test_cabe_mas_sem_reserva_minima_tambem_e_erro(self):
        livre = self._necessario(10, 10) + disco.RESERVA_MINIMA // 2
        assert disco.avaliar(10, 10, livre=livre, media=self.MEDIA).status == disco.ERRO

    def test_guarda_os_numeros_para_a_mensagem(self):
        e = disco.avaliar(3, 5, livre=50 * GB, media=self.MEDIA)
        assert (e.n_downloads, e.n_renders, e.necessario) == (3, 5, self._necessario(3, 5))

    def test_mede_o_disco_real_quando_livre_nao_e_informado(self, perfil, monkeypatch):
        class Uso:
            free = 7 * GB
        monkeypatch.setattr(disco.shutil, "disk_usage", lambda _p: Uso())
        assert disco.avaliar(1, 1, media=self.MEDIA).livre == 7 * GB

    def test_descricao_cita_livre_necessario_e_contagens(self):
        texto = disco.descrever(disco.avaliar(152, 152, livre=2 * GB, media=7 * MB))
        assert "152" in texto and "GB" in texto and "livre" in texto.lower()


class TestRendersPendentes:
    @pytest.fixture
    def ambiente(self, perfil, monkeypatch):
        def render_falso(origem, destino, preset):
            destino.write_bytes(b"r")
            return True
        monkeypatch.setattr(audio, "renderizar_audio", render_falso)
        monkeypatch.setattr(config, "RENDER_WORKERS", 1)
        playlists.criar_playlist("T")
        nomes = ["A - s1", "B - s2", "C - s3"]
        playlists.caminho_playlist_txt("T").write_text("\n".join(nomes), encoding="utf-8")
        for n in nomes:
            a, t = n.split(" - ")
            (config.DOWNLOAD_DIR / f"{t} - {a}.mp3").write_bytes(b"x" * 20000)
        return nomes

    def test_nada_renderizado_ainda_tudo_pendente(self, ambiente):
        assert playlists.renders_pendentes("T") == 3

    def test_tudo_renderizado_nada_pendente(self, ambiente):
        playlists.reconciliar_links("T")
        assert playlists.renders_pendentes("T") == 0

    def test_musica_nova_na_playlist_conta(self, ambiente):
        playlists.reconciliar_links("T")
        playlists.caminho_playlist_txt("T").write_text("\n".join([*ambiente, "D - s4"]), encoding="utf-8")
        assert playlists.renders_pendentes("T") == 1

    def test_arquivo_apagado_conta_como_pendente(self, ambiente):
        playlists.reconciliar_links("T")
        next(playlists.caminho_playlist_musicas("T").glob("*.mp3")).unlink()
        assert playlists.renders_pendentes("T") == 1

    def test_trocar_o_preset_deixa_tudo_pendente(self, ambiente):
        playlists.reconciliar_links("T")
        playlists.definir_preset("T", "carro")
        assert playlists.renders_pendentes("T") == 3

    def test_so_mudar_de_posicao_nao_conta(self, ambiente):
        """Renomear é de graça: não pode inflar a estimativa de espaço."""
        playlists.reconciliar_links("T")
        playlists.caminho_playlist_txt("T").write_text("\n".join(["N - s0", *ambiente]), encoding="utf-8")
        (config.DOWNLOAD_DIR / "s0 - N.mp3").write_bytes(b"x" * 20000)
        assert playlists.renders_pendentes("T") == 1            # só a nova

    def test_linha_repetida_na_playlist_conta_uma_vez(self, ambiente):
        playlists.caminho_playlist_txt("T").write_text("\n".join([*ambiente, "A - s1"]), encoding="utf-8")
        assert playlists.renders_pendentes("T") == 3

    def test_sem_normalizacao_nao_ha_render(self, ambiente, monkeypatch):
        monkeypatch.setattr(config, "NORMALIZAR_VOLUME", False)
        assert playlists.renders_pendentes("T") == 0
