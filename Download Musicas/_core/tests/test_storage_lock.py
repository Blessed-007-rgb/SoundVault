import json
import os
import threading

import pytest

from soundvault import config, lock, storage


class TestCache:
    def test_entrada_valida(self):
        ok = {"url": "https://www.youtube.com/watch?v=xLQ1QkGB6bk", "id": "xLQ1QkGB6bk"}
        assert storage.entrada_cache_valida(ok)
        assert storage.entrada_cache_valida({**ok, "id": ""})

    @pytest.mark.parametrize("dados", [
        {},
        {"url": ""},
        {"url": "https://www.youtube.com/watch?v=_xLQ1QkGB6bk", "id": "_xLQ1QkGB6bk"},  # 12 chars
        {"url": "https://www.youtube.com/watch?v=xLQ1QkGB6bk", "id": "OUTROIDXXXX"},    # id diverge
        "texto", None,
    ])
    def test_entrada_invalida(self, dados):
        assert not storage.entrada_cache_valida(dados)

    def test_salvar_recusa_invalida_e_nao_grava(self, perfil):
        assert storage.salvar_cache_entrada("A - B", {"url": "https://www.youtube.com/watch?v=curto"}) is False
        assert "A - B" not in storage.carregar_cache()

    def test_salvar_corrige_id_divergente(self, perfil):
        storage.salvar_cache_entrada("A - B", {"url": "https://youtu.be/xLQ1QkGB6bk", "id": ""})
        assert storage.carregar_cache()["A - B"]["id"] == "xLQ1QkGB6bk"

    def test_escritas_concorrentes_nao_perdem_entradas(self, perfil):
        def gravar(i):
            vid = f"{i:011d}"
            storage.salvar_cache_entrada(f"A - {i}", {"url": f"https://youtu.be/{vid}"})
        ts = [threading.Thread(target=gravar, args=(i,)) for i in range(25)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert len(storage.carregar_cache()) == 25


class TestStateCorrompido:
    def test_state_corrompido_vira_backup_e_retorna_vazio(self, perfil):
        config.STATE_FILE.write_text("{ não é json", encoding="utf-8")
        assert storage.carregar_state() == {}
        assert config.STATE_FILE.with_suffix(".json.bak").exists()

    def test_state_valido_roundtrip(self, perfil):
        storage.salvar_state({"abc": {"name": "A - B"}})
        assert storage.carregar_state() == {"abc": {"name": "A - B"}}

    def test_escrita_atomica_nao_deixa_tmp(self, perfil):
        storage.salvar_state({"x": 1})
        assert not list(config.BASE_DIR.glob("*.tmp"))
        assert json.loads(config.STATE_FILE.read_text(encoding="utf-8")) == {"x": 1}


class TestLock:
    def test_adquirir_e_liberar(self, perfil):
        lock.adquirir_lock()
        assert config.LOCK_FILE.read_text().strip() == str(os.getpid())
        lock.liberar_lock()
        assert not config.LOCK_FILE.exists()

    def test_nao_remove_lock_de_outro_processo(self, perfil):
        """Regressão: o atexit apagava o lock da instância que ainda rodava."""
        config.LOCK_FILE.write_text("999999999")  # PID de "outro" processo
        lock.liberar_lock()
        lock._liberar_lock_atexit()
        assert config.LOCK_FILE.exists()

    def test_lock_de_processo_morto_e_recuperado(self, perfil):
        config.LOCK_FILE.write_text("999999999")  # PID inexistente
        lock.adquirir_lock()
        assert config.LOCK_FILE.read_text().strip() == str(os.getpid())
        lock.liberar_lock()
