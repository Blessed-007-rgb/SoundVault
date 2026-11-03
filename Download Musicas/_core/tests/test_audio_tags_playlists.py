import shutil
import subprocess
import time

import pytest

from soundvault import audio, config, eq_presets, playlists, tags

FFMPEG = shutil.which("ffmpeg")
precisa_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg não encontrado no PATH")


def _gerar_mp3(destino, segundos=8, freq=440, vol_db=-20):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={segundos}",
         "-af", f"volume={vol_db}dB", "-codec:a", "libmp3lame", "-q:a", "2", str(destino)],
        check=True,
    )


def _loudness(arquivo):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(arquivo), "-af", "ebur128=peak=true:framelog=quiet",
         "-vn", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    medido = audio._medir_loudness(r.stderr)
    assert medido is not None, "ebur128 não devolveu resumo de loudness"
    return medido


class TestEqPresets:
    def test_todos_os_presets_sao_coerentes(self):
        for pid, p in eq_presets.PRESETS.items():
            assert set(p["loudnorm"]) == {"I", "TP", "LRA"}, pid
            assert -30 < p["loudnorm"]["I"] < -5 and p["loudnorm"]["TP"] <= 0, pid
            for freq, ganho in p["eq_bands"]:
                assert 20 <= freq <= 20000 and abs(ganho) <= 12, (pid, freq, ganho)

    def test_cadeia_de_eq(self):
        assert eq_presets.montar_eq_chain("padrao") == ""
        cadeia = eq_presets.montar_eq_chain("fone")
        assert cadeia.endswith(",") and cadeia.count("equalizer=") == len(eq_presets.PRESETS["fone"]["eq_bands"])

    def test_perfil_muda_com_o_preset_e_e_estavel(self):
        assert audio.perfil_atual("fone") == audio.perfil_atual("fone")
        assert len({audio.perfil_atual(p) for p in eq_presets.PRESETS}) == len(eq_presets.PRESETS)


class TestMedirLoudness:
    RESUMO = "  Summary:\n\n  Integrated loudness:\n    I:         -7.0 LUFS\n    Threshold: -17.0 LUFS\n\n  True peak:\n    Peak:        2.1 dBFS\n"

    def test_parse(self):
        assert audio._medir_loudness(self.RESUMO) == (-7.0, 2.1)

    def test_silencio_digital_e_sem_resumo(self):
        assert audio._medir_loudness(self.RESUMO.replace("-7.0", "-inf")) is None
        assert audio._medir_loudness("nada aqui") is None


@precisa_ffmpeg
class TestRenderizar:
    @pytest.mark.parametrize("preset,alvo", [("padrao", -14.0), ("fone", -14.0), ("carro", -11.0)])
    def test_atinge_o_loudness_alvo(self, tmp_path, preset, alvo, perfil):
        origem, destino = tmp_path / "in.mp3", tmp_path / "out.mp3"
        _gerar_mp3(origem, vol_db=-5)  # ~-26 LUFS: precisa de ~+12 dB, dentro do teto de ganho
        assert audio.renderizar_audio(origem, destino, preset)
        lufs, tp = _loudness(destino)
        assert abs(lufs - alvo) < 0.6, f"{preset}: {lufs} LUFS (alvo {alvo})"
        assert tp < 0.0
        assert not (tmp_path / "out.render.mp3").exists()  # sem lixo temporário

    def test_audio_muito_baixo_e_limitado_pelo_teto_de_ganho(self, tmp_path, perfil):
        """Faixa quase inaudível (~-46 LUFS) não é amplificada além de
        _GANHO_MAX_DB: amplificaria o ruído de fundo junto."""
        origem, destino = tmp_path / "quieto.mp3", tmp_path / "out.mp3"
        _gerar_mp3(origem, vol_db=-25)
        entrada, _ = _loudness(origem)
        assert audio.renderizar_audio(origem, destino, "padrao")
        saida, _ = _loudness(destino)
        assert saida - entrada <= audio._GANHO_MAX_DB + 1.0

    def test_pico_alto_respeita_o_teto_de_true_peak(self, tmp_path, perfil):
        origem, destino = tmp_path / "alto.mp3", tmp_path / "out.mp3"
        _gerar_mp3(origem, vol_db=0)  # já alto; carro pede -11 LUFS / TP -1.0
        assert audio.renderizar_audio(origem, destino, "carro")
        _, tp = _loudness(destino)
        assert tp <= eq_presets.loudnorm_alvo("carro")["TP"] + 0.6  # margem do re-encode MP3

    def test_audio_silencioso_nao_quebra(self, tmp_path, perfil):
        origem, destino = tmp_path / "sil.mp3", tmp_path / "out.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                        "-t", "6", "-codec:a", "libmp3lame", str(origem)], check=True)
        # silêncio digital: não pode lançar exceção (False é aceitável)
        assert audio.renderizar_audio(origem, destino, "fone") in (True, False)

    def test_arquivo_inexistente_retorna_false(self, tmp_path, perfil):
        assert audio.renderizar_audio(tmp_path / "nao_existe.mp3", tmp_path / "o.mp3", "fone") is False


class TestTags:
    def test_capa_nao_duplica_em_regravacoes(self, tmp_path, monkeypatch):
        """Regressão: `"APIC:" not in tags` era sempre True e empilhava capas."""
        pytest.importorskip("mutagen")
        from mutagen.id3 import ID3
        mp3 = tmp_path / "t.mp3"
        if FFMPEG:
            _gerar_mp3(mp3)
        else:
            pytest.skip("precisa de ffmpeg pra gerar o MP3")
        monkeypatch.setattr(tags, "_baixar_thumbnail", lambda url: b"\xff\xd8" + b"x" * 5000)
        for _ in range(3):
            tags.gravar_tags(mp3, "Artista", "Título", url_video="https://youtu.be/xLQ1QkGB6bk")
        t = ID3(str(mp3))
        assert len(t.getall("APIC")) == 1
        assert str(t["TIT2"]) == "Título" and str(t["TPE1"]) == "Artista"


class TestPlaylists:
    @pytest.mark.parametrize("nome", ["..", ".", "", "a/b", "a\\b", "..\\..\\Windows", "../x"])
    def test_nome_de_playlist_com_path_traversal_e_rejeitado(self, nome):
        with pytest.raises(ValueError):
            playlists._validar_nome(nome)

    def test_round_robin_intercala_artistas(self):
        ordem = playlists.ordem_round_robin(["A - 1", "A,X - 2", "B - 3", "A - 4", "B - 5"])
        artistas = [m.split(" - ")[0].split(",")[0] for m in ordem]
        assert all(a != b for a, b in zip(artistas, artistas[1:]) if artistas.count(a) <= 2)
        assert sorted(ordem) == sorted(["A - 1", "A,X - 2", "B - 3", "A - 4", "B - 5"])

    def test_reconciliar_renderiza_em_paralelo_e_e_idempotente(self, perfil, monkeypatch):
        playlists.criar_playlist("T")
        nomes = [f"Art{i} - Musica{i}" for i in range(6)]
        playlists.caminho_playlist_txt("T").write_text("\n".join(nomes), encoding="utf-8")
        for n in nomes:
            (config.DOWNLOAD_DIR / f"{n.split(' - ')[1]} - {n.split(' - ')[0]}.mp3").write_bytes(b"x" * 20000)

        chamadas, ativas, pico = [], [0], [0]

        def render_falso(origem, destino, preset):
            ativas[0] += 1
            pico[0] = max(pico[0], ativas[0])
            time.sleep(0.15)
            destino.write_bytes(b"render")
            chamadas.append(origem.name)
            ativas[0] -= 1
            return True

        monkeypatch.setattr(audio, "renderizar_audio", render_falso)
        monkeypatch.setattr(config, "RENDER_WORKERS", 3)
        criados, removidos, faltando = playlists.reconciliar_links("T")
        assert (criados, removidos, faltando) == (6, 0, [])
        assert pico[0] > 1, "os renders deveriam rodar em paralelo"
        assert len(list(config.BASE_DIR.glob("playlists/T/Musicas/*.mp3"))) == 6

        chamadas.clear()
        assert playlists.reconciliar_links("T")[0] == 0 and not chamadas  # reaproveita render_state

    def test_render_que_falha_nao_e_marcado_como_feito(self, perfil, monkeypatch):
        playlists.criar_playlist("T")
        playlists.caminho_playlist_txt("T").write_text("A - B\n", encoding="utf-8")
        (config.DOWNLOAD_DIR / "B - A.mp3").write_bytes(b"x" * 20000)
        monkeypatch.setattr(audio, "renderizar_audio", lambda *a: False)
        assert playlists.reconciliar_links("T")[0] == 0
        assert playlists._ler_render_state("T") == {}

    def test_escrita_de_preset_e_render_state_sem_tmp_sobrando(self, perfil):
        playlists.criar_playlist("T")
        playlists.definir_preset("T", "fone")
        playlists._salvar_render_state("T", {"a": 1})
        assert playlists.ler_preset("T") == "fone"
        assert not list((config.BASE_DIR / "playlists" / "T").glob("*.tmp"))


class TestReaplicarAudio:
    @pytest.fixture
    def chamadas(self, perfil, monkeypatch):
        from soundvault import rebuild
        for nome in ("Treino", "Sertanejo", "Sex"):
            playlists.criar_playlist(nome)
        vistas = []
        monkeypatch.setattr(playlists, "reconciliar_links", lambda n: (vistas.append(n) or (1, 0, [])))
        monkeypatch.setattr(rebuild.os, "system", lambda *a: 0)
        monkeypatch.setattr("shutil.which", lambda *_: "ffmpeg")
        return rebuild, vistas

    def test_so_a_playlist_escolhida(self, chamadas):
        rebuild, vistas = chamadas
        rebuild.reaplicar_audio("Sertanejo")
        assert vistas == ["Sertanejo"]

    def test_sem_argumento_roda_todas(self, chamadas):
        rebuild, vistas = chamadas
        rebuild.reaplicar_audio()
        assert sorted(vistas) == ["Sertanejo", "Sex", "Treino"]

    def test_playlist_inexistente_nao_roda_nada(self, chamadas):
        rebuild, vistas = chamadas
        rebuild.reaplicar_audio("NaoExiste")
        assert vistas == []

    def test_preset_escolhido_e_salvo_so_na_playlist_alvo(self, chamadas):
        rebuild, vistas = chamadas
        rebuild.reaplicar_audio("Sertanejo", "carro")
        assert vistas == ["Sertanejo"]
        assert playlists.ler_preset("Sertanejo") == "carro"
        assert playlists.ler_preset("Treino") == eq_presets.PRESET_PADRAO  # intacta

    def test_preset_em_todas_as_playlists(self, chamadas):
        rebuild, vistas = chamadas
        rebuild.reaplicar_audio(None, "fone")
        assert {playlists.ler_preset(n) for n in ("Treino", "Sertanejo", "Sex")} == {"fone"}
        assert sorted(vistas) == ["Sertanejo", "Sex", "Treino"]

    def test_sem_preset_mantem_o_de_cada_playlist(self, chamadas):
        rebuild, vistas = chamadas
        playlists.definir_preset("Treino", "fone")
        playlists.definir_preset("Sex", "caixa")
        rebuild.reaplicar_audio()
        assert playlists.ler_preset("Treino") == "fone" and playlists.ler_preset("Sex") == "caixa"

    def test_preset_invalido_nao_altera_nada(self, chamadas):
        rebuild, vistas = chamadas
        rebuild.reaplicar_audio("Treino", "nao_existe")
        assert vistas == [] and playlists.ler_preset("Treino") == eq_presets.PRESET_PADRAO


class TestMenuReaplicar:
    @staticmethod
    def _resposta(monkeypatch, menu, valor):
        import types
        monkeypatch.setattr(menu, "Prompt", types.SimpleNamespace(ask=lambda *a, **k: valor))

    def test_escolher_preset_mapeia_as_opcoes(self, monkeypatch):
        from soundvault import menu
        ids = list(eq_presets.PRESETS)
        self._resposta(monkeypatch, menu, "1")
        assert menu.escolher_preset() is None                       # manter o atual
        self._resposta(monkeypatch, menu, "2")
        assert menu.escolher_preset() == ids[0]                     # 1º preset real
        self._resposta(monkeypatch, menu, str(len(ids) + 1))
        assert menu.escolher_preset() == ids[-1]                    # último
        self._resposta(monkeypatch, menu, "0")
        assert menu.escolher_preset() == "__cancelar__"

    def _fluxo(self, monkeypatch, alvo, preset, confirma):
        from soundvault import menu
        chamadas = []
        monkeypatch.setattr(menu, "escolher_playlist", lambda *a, **k: alvo)
        monkeypatch.setattr(menu, "escolher_preset", lambda *a, **k: preset)
        monkeypatch.setattr(menu, "_confirmar", lambda *_: confirma)
        monkeypatch.setattr(menu, "reaplicar_audio", lambda a, p: chamadas.append((a, p)))
        menu.reaplicar_audio_interativo()
        return chamadas

    def test_uma_playlist_com_preset_nao_pede_confirmacao(self, monkeypatch, perfil):
        assert self._fluxo(monkeypatch, "Treino", "carro", confirma=False) == [("Treino", "carro")]

    def test_todas_com_preset_exige_confirmacao(self, monkeypatch, perfil):
        assert self._fluxo(monkeypatch, None, "carro", confirma=False) == []
        assert self._fluxo(monkeypatch, None, "carro", confirma=True) == [(None, "carro")]

    def test_todas_mantendo_o_atual_nao_precisa_confirmar(self, monkeypatch, perfil):
        assert self._fluxo(monkeypatch, None, None, confirma=False) == [(None, None)]

    def test_cancelar_em_qualquer_etapa(self, monkeypatch, perfil):
        assert self._fluxo(monkeypatch, "__cancelar__", None, confirma=True) == []
        assert self._fluxo(monkeypatch, "Treino", "__cancelar__", confirma=True) == []
