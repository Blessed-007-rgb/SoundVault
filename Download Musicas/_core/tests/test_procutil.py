from soundvault import procutil


def _com_executaveis(monkeypatch, instalados):
    monkeypatch.setattr(procutil.shutil, "which", lambda nome: f"C:/bin/{nome}.exe" if nome in instalados else None)


def test_node_instalado_vira_flag_para_o_ytdlp(monkeypatch):
    _com_executaveis(monkeypatch, {"node"})
    assert procutil.runtimes_js() == ["node"]
    assert procutil.ytdlp_js_args() == ["--js-runtimes", "node"]
    assert procutil.ytdlp_js_params() == {"js_runtimes": {"deno": {}, "node": {}}}


def test_sem_runtime_extra_nao_passa_nada(monkeypatch):
    _com_executaveis(monkeypatch, set())
    assert procutil.runtimes_js() == []
    assert procutil.ytdlp_js_args() == []
    assert procutil.ytdlp_js_params() == {}


def test_deno_sozinho_nao_precisa_de_flag(monkeypatch):
    # o yt-dlp já habilita o deno por padrão
    _com_executaveis(monkeypatch, {"deno"})
    assert procutil.ytdlp_js_args() == []


def test_node_e_bun_juntos(monkeypatch):
    _com_executaveis(monkeypatch, {"node", "bun"})
    assert procutil.ytdlp_js_args() == ["--js-runtimes", "node", "--js-runtimes", "bun"]


def test_comando_de_download_inclui_a_flag(monkeypatch, perfil):
    """O comando real montado por baixar() precisa carregar o --js-runtimes."""
    from soundvault import download
    _com_executaveis(monkeypatch, {"node"})
    vistos = []

    class R:
        returncode, stderr, stdout = 1, "ERROR: This video is unavailable", ""

    def falso_run(cmd, **kw):
        vistos.append(cmd)
        return R()
    monkeypatch.setattr(download.subprocess, "run", falso_run)
    monkeypatch.setattr(download.search, "buscar_ytmusic", lambda chave: None)
    download.baixar("A - B", "https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk", {})
    assert vistos and all("--js-runtimes" in c and "node" in c for c in vistos)
