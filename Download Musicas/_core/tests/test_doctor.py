from soundvault import doctor, storage


def _por_nome(checks):
    return {c.nome: c for c in checks}


def test_sem_runtime_js_e_erro(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda n: None)
    c = doctor.checar_js()
    assert c[0].status == doctor.ERRO and "Node.js" in c[0].dica


def test_node_sem_deno_e_ok_e_sem_ejs_e_aviso(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda n: "C:/n.exe" if n == "node" else None)
    monkeypatch.setattr(doctor, "_tem_modulo", lambda m: False)
    c = _por_nome(doctor.checar_js())
    assert c["Runtime JavaScript"].status == doctor.OK
    assert c["yt-dlp-ejs"].status == doctor.AVISO and "yt-dlp[default]" in c["yt-dlp-ejs"].dica


def test_ffmpeg_ausente_e_erro(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda n: None)
    assert all(c.status == doctor.ERRO for c in doctor.checar_ffmpeg())


def test_pacote_ausente_e_aviso_com_dica(monkeypatch):
    monkeypatch.setattr(doctor, "_tem_modulo", lambda m: m != "psutil")
    c = _por_nome(doctor.checar_pacotes())
    assert c["Pacote psutil"].status == doctor.AVISO and c["Pacote psutil"].dica == "pip install psutil"
    assert c["Pacote rich"].status == doctor.OK


def test_disco_nos_tres_niveis(monkeypatch, perfil):
    class U:
        def __init__(self, livre): self.free = livre
    for livre_gb, esperado in ((0.5, doctor.ERRO), (3, doctor.AVISO), (50, doctor.OK)):
        monkeypatch.setattr(doctor.shutil, "disk_usage", lambda _p, g=livre_gb: U(int(g * doctor.GB)))
        assert doctor.checar_disco().status == esperado


def test_cookie_ausente_e_aviso_e_offline_nao_testa_rede(perfil, monkeypatch):
    assert doctor.checar_cookies(rede=False).status == doctor.AVISO
    from soundvault import config
    config.COOKIES_FILE.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tA\tb\n", encoding="utf-8")
    monkeypatch.setattr("soundvault.cookies.verificar_cookie_valido", lambda forcar=False: (_ for _ in ()).throw(AssertionError("não deveria testar")))
    assert doctor.checar_cookies(rede=False).status == doctor.INFO


def test_cookie_invalido_e_erro(perfil, monkeypatch):
    from soundvault import config
    config.COOKIES_FILE.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tA\tb\n", encoding="utf-8")
    monkeypatch.setattr("soundvault.cookies.verificar_cookie_valido", lambda forcar=False: False)
    c = doctor.checar_cookies(rede=True)
    assert c.status == doctor.ERRO and "janela anônima" in c.dica
    monkeypatch.setattr("soundvault.cookies.verificar_cookie_valido", lambda forcar=False: None)
    assert doctor.checar_cookies(rede=True).status == doctor.AVISO


def test_cache_com_problema_e_fila_de_revisao(perfil):
    storage.salvar_cache_entrada("A - B", {"url": "https://youtu.be/aaaaaaaaaaa", "auto": True, "score": 50, "video": "v"})
    from soundvault import config
    import json
    dados = storage.carregar_cache()
    dados["Quebrada"] = {"url": "https://www.youtube.com/watch?v=_curto"}
    config.CACHE_FILE.write_text(json.dumps(dados), encoding="utf-8")
    c = _por_nome(doctor.checar_cache())
    assert c["playlist_cache.json"].status == doctor.AVISO
    assert c["Revisão de URLs"].status == doctor.AVISO


def test_diagnosticar_devolve_1_so_quando_ha_erro(perfil, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "coletar", lambda rede=True: [doctor.Check("x", doctor.OK, "tudo certo")])
    assert doctor.diagnosticar() == 0
    monkeypatch.setattr(doctor, "coletar", lambda rede=True: [doctor.Check("y", doctor.ERRO, "quebrou", "conserte")])
    assert doctor.diagnosticar() == 1
    saida = capsys.readouterr().out
    assert "conserte" in saida and "1 erro(s)" in saida


def test_cli_doctor_propaga_o_codigo_de_saida(perfil, monkeypatch):
    import pytest
    from soundvault import __main__ as entrada
    monkeypatch.setattr(entrada.sys, "argv", ["soundvault", "--doctor", "--offline"])
    monkeypatch.setattr("soundvault.doctor.diagnosticar", lambda rede=True: 1 if rede else 7)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    with pytest.raises(SystemExit) as e:
        entrada.main()
    assert e.value.code == 7  # --offline chegou ao diagnosticar(rede=False)
