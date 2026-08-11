import json
import os
import shutil
from pathlib import Path

from . import audio, config, eq_presets
from .console_log import log
from .playlist import carregar_playlist as _carregar_playlist_de, parsear, nome_arquivo


def playlists_dir() -> Path:
    d = config.BASE_DIR / "playlists"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validar_nome(nome: str) -> str:
    """
    Impede path traversal: 'nome' vem de entrada do usuário (menu
    interativo, --playlist na CLI, argumento do spotify_export) e é
    usado direto pra montar um caminho de arquivo. Sem essa checagem,
    um nome como '..\\..\\Windows' escaparia de playlists\\ e
    remover_playlist() apagaria uma pasta arbitrária do disco.
    """
    nome = nome.strip().lstrip("﻿")  # remove BOM (alguns terminais/pipes o incluem em input())
    if not nome or nome in (".", ".."):
        raise ValueError("Nome de playlist inválido.")
    if os.sep in nome or (os.altsep and os.altsep in nome) or "/" in nome or "\\" in nome:
        raise ValueError("Nome de playlist não pode conter barras (/ ou \\).")
    if Path(nome).name != nome:
        raise ValueError("Nome de playlist inválido.")
    return nome


def caminho_playlist_txt(nome: str) -> Path:
    return playlists_dir() / _validar_nome(nome) / "playlist.txt"


def caminho_playlist_musicas(nome: str) -> Path:
    return playlists_dir() / _validar_nome(nome) / "Musicas"


def listar_playlists() -> list[str]:
    """Nomes das playlists existentes — qualquer pasta em playlists\\ com
    um playlist.txt dentro."""
    d = playlists_dir()
    return sorted(
        p.name for p in d.iterdir()
        if p.is_dir() and (p / "playlist.txt").exists()
    )


def criar_playlist(nome: str) -> Path:
    """Cria (ou garante que existe) a pasta da playlist. Idempotente —
    chamar de novo numa playlist existente não apaga nada."""
    caminho = caminho_playlist_txt(nome)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho_playlist_musicas(nome).mkdir(parents=True, exist_ok=True)
    if not caminho.exists():
        caminho.write_text(
            "# Uma música por linha, no formato: Artista - Título\n",
            encoding="utf-8",
        )
    return caminho


def caminho_preset(nome: str) -> Path:
    return playlists_dir() / _validar_nome(nome) / "preset.json"


def ler_preset(nome: str) -> str:
    """Preset de EQ/loudness atual da playlist. Ausente ou corrompido cai
    silenciosamente pro Padrão — uma playlist sem preset.json (ex: criada
    antes desta funcionalidade existir) continua funcionando sem migração."""
    caminho = caminho_preset(nome)
    if not caminho.exists():
        return eq_presets.PRESET_PADRAO
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        preset_id = dados.get("preset", eq_presets.PRESET_PADRAO)
        return preset_id if eq_presets.preset_valido(preset_id) else eq_presets.PRESET_PADRAO
    except (json.JSONDecodeError, OSError):
        return eq_presets.PRESET_PADRAO


def definir_preset(nome: str, preset_id: str):
    if not eq_presets.preset_valido(preset_id):
        raise ValueError(f"Preset desconhecido: {preset_id}")
    caminho = caminho_preset(nome)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps({"preset": preset_id}), encoding="utf-8")


def _caminho_render_state(nome: str) -> Path:
    return playlists_dir() / _validar_nome(nome) / "render_state.json"


def _ler_render_state(nome: str) -> dict:
    """Cache de quais músicas da playlist já foram renderizadas, com qual
    preset/hash e sob qual nome de arquivo — ver reconciliar_links().
    Corrompido ou ausente vira dict vazio: força re-render geral dessa
    playlist na próxima reconciliação, mas não quebra nada (é
    regenerável, ao contrário de sync_state.json)."""
    caminho = _caminho_render_state(nome)
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _salvar_render_state(nome: str, state: dict):
    caminho = _caminho_render_state(nome)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def remover_playlist(nome: str):
    """Remove a pasta da playlist (playlist.txt + os hardlinks/cópias em
    Musicas\\). NÃO mexe no pool central (Main\\Musicas\\) — a limpeza
    do pool acontece no próximo Sync, via todas_as_musicas()."""
    d = playlists_dir() / _validar_nome(nome)
    if d.exists():
        shutil.rmtree(d)


def carregar_playlist(nome: str) -> list[str]:
    return _carregar_playlist_de(caminho_playlist_txt(nome))


def todas_as_musicas() -> set[str]:
    """
    União de todas as músicas de todas as playlists do perfil — usado
    pra decidir o que é seguro manter no pool central (Main\\Musicas\\):
    uma música só sai do pool quando NENHUMA playlist mais a referencia.
    """
    musicas: set[str] = set()
    for nome in listar_playlists():
        musicas.update(carregar_playlist(nome))
    return musicas


def migrar_playlist_legada(nome: str) -> bool:
    """
    Migra o formato antigo (playlist.txt na raiz do perfil, uma playlist
    só) para o novo formato (playlists\\<nome>\\playlist.txt). Retorna
    True se migrou algo, False se não havia playlist.txt legado ou se
    já existe pelo menos uma playlist no formato novo (não sobrescreve
    nada nesse caso — evita perder dados se rodar duas vezes).
    """
    legado = config.BASE_DIR / "playlist.txt"
    if not legado.exists():
        return False
    if listar_playlists():
        log.warning(f"playlist.txt legado encontrado em {legado}, mas já existem playlists migradas — ignorando.")
        return False

    destino = criar_playlist(nome)
    conteudo = legado.read_text(encoding="utf-8-sig")
    destino.write_text(conteudo, encoding="utf-8")
    legado.unlink()
    log.info(f"Playlist legada migrada para playlists/{nome}/playlist.txt")

    pasta_musicas = caminho_playlist_musicas(nome)
    criados = 0
    for f in config.DOWNLOAD_DIR.glob("*.mp3"):
        if f.stem.startswith("__dl_"):
            continue
        destino_link = pasta_musicas / f.name
        if destino_link.exists():
            continue
        try:
            os.link(f, destino_link)
        except OSError:
            shutil.copy2(f, destino_link)
        criados += 1
    log.info(f"Migração: {criados} link(s) criados em playlists/{nome}/Musicas/")
    return True


def ordem_round_robin(playlist: list[str]) -> list[str]:
    """
    Reordena a playlist intercalando os artistas (uma música de cada vez,
    em rodízio) pra nunca repetir o mesmo artista em sequência.

    Motivo: tocadores de pendrive/carro simples reproduzem os arquivos na
    ordem alfabética do NOME do arquivo, não respeitam nenhuma ordem de
    "playlist" — e "Título - Artista.mp3" acaba ficando ok pra isso, mas
    nada impede vários títulos do mesmo artista de ficarem agrupados
    alfabeticamente por acaso. O prefixo numérico (aplicado em
    reconciliar_links) usa esta ordem pra forçar o rodízio.

    Agrupa pelo artista PRINCIPAL (primeiro nome antes da vírgula) — sem
    isso, "Eminem", "Eminem,Dido" e "Eminem,D12" contavam como três
    "artistas" diferentes e todas as parcerias do Eminem ainda ficavam
    juntas em sequência, mesmo cada uma sendo tecnicamente um grupo à parte.
    """
    grupos: dict[str, list[str]] = {}
    ordem_artistas: list[str] = []
    for nome in playlist:
        artista_completo, _ = parsear(nome)
        artista = artista_completo.split(",")[0].strip()
        if artista not in grupos:
            grupos[artista] = []
            ordem_artistas.append(artista)
        grupos[artista].append(nome)

    resultado = []
    restantes = len(playlist)
    while restantes > 0:
        for artista in ordem_artistas:
            fila = grupos[artista]
            if fila:
                resultado.append(fila.pop(0))
                restantes -= 1
    return resultado


def reconciliar_links(nome: str) -> tuple[int, int, list[str]]:
    """
    Garante que playlists\\<nome>\\Musicas\\ tem exatamente um arquivo por
    música do playlist.txt dessa playlist, renderizado com o preset de EQ
    atual da playlist (ver ler_preset()).

    Os nomes dos arquivos nessa pasta levam um prefixo numérico que
    reflete a ordem de rodízio por artista (ordem_round_robin) — pensado
    pra tocadores de pendrive/carro que reproduzem em ordem alfabética de
    nome de arquivo. O pool central (DOWNLOAD_DIR) não é afetado — fica
    sempre cru, é a fonte usada pra renderizar cada playlist.

    Reaproveita renders existentes (via render_state.json) quando o
    preset e a receita de EQ não mudaram — só chama o FFmpeg pra música
    nova ou quando o preset foi trocado. Se só a ORDEM mudou (prefixo
    diferente pro mesmo conteúdo), renomeia o arquivo em vez de
    renderizar de novo.

    Se config.NORMALIZAR_VOLUME estiver desligado, cai pro comportamento
    antigo (hardlink puro do pool, sem processamento nenhum).

    Retorna (criados, removidos, faltando_no_pool) — faltando_no_pool
    lista músicas que deveriam ter arquivo mas ainda não foram baixadas
    pro pool central (não é erro, só reflete Sync incompleto/pendente).
    """
    playlist = carregar_playlist(nome)
    pasta = caminho_playlist_musicas(nome)
    pasta.mkdir(parents=True, exist_ok=True)

    ordenada = ordem_round_robin(playlist)
    largura = max(len(str(len(ordenada))), 2)
    esperado_por_chave = {
        n: f"{i:0{largura}d} - {nome_arquivo(*parsear(n))}.mp3"
        for i, n in enumerate(ordenada, 1)
    }

    if not config.NORMALIZAR_VOLUME:
        return _reconciliar_links_sem_processamento(esperado_por_chave, pasta)

    preset_id = ler_preset(nome)
    perfil = audio.perfil_atual(preset_id)
    render_state = _ler_render_state(nome)

    esperados_nomes = set(esperado_por_chave.values())
    existentes = {f.name for f in pasta.glob("*.mp3")}

    removidos = 0
    for nome_arq in existentes - esperados_nomes:
        (pasta / nome_arq).unlink(missing_ok=True)
        removidos += 1
    for chave in list(render_state.keys()):
        if chave not in esperado_por_chave:
            del render_state[chave]

    criados = 0
    faltando_no_pool = []

    for chave, nome_arq in esperado_por_chave.items():
        destino = pasta / nome_arq
        entrada = render_state.get(chave)

        if entrada and entrada.get("preset") == preset_id and entrada.get("hash") == perfil:
            antigo = pasta / entrada.get("file", "")
            if antigo.exists():
                if antigo != destino:
                    antigo.rename(destino)
                    entrada["file"] = nome_arq
                continue
            # arquivo sumiu do disco apesar do render_state achar que
            # existia — cai pro render abaixo como se fosse novo.

        origem = config.DOWNLOAD_DIR / f"{nome_arquivo(*parsear(chave))}.mp3"
        if not origem.exists():
            faltando_no_pool.append(f"{nome_arquivo(*parsear(chave))}.mp3")
            continue

        if audio.renderizar_audio(origem, destino, preset_id):
            render_state[chave] = {"preset": preset_id, "hash": perfil, "file": nome_arq}
            criados += 1

    _salvar_render_state(nome, render_state)
    return criados, removidos, faltando_no_pool


def _reconciliar_links_sem_processamento(esperado_por_chave: dict, pasta: Path) -> tuple[int, int, list[str]]:
    """Comportamento antigo (hardlink puro do pool) — usado quando
    config.NORMALIZAR_VOLUME está desligado."""
    mapa_esperados = {nome_arq: chave for chave, nome_arq in esperado_por_chave.items()}
    esperados = set(mapa_esperados.keys())
    existentes = {f.name for f in pasta.glob("*.mp3")}

    removidos = 0
    for nome_arq in existentes - esperados:
        (pasta / nome_arq).unlink(missing_ok=True)
        removidos += 1

    criados = 0
    faltando_no_pool = []
    for nome_arq in esperados - existentes:
        chave = mapa_esperados[nome_arq]
        base = f"{nome_arquivo(*parsear(chave))}.mp3"
        origem = config.DOWNLOAD_DIR / base
        if not origem.exists():
            faltando_no_pool.append(base)
            continue
        destino = pasta / nome_arq
        try:
            os.link(origem, destino)
        except OSError:
            shutil.copy2(origem, destino)
        criados += 1

    return criados, removidos, faltando_no_pool
