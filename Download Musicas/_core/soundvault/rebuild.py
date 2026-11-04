from datetime import datetime

from . import config, eq_presets
from .console_log import limpar_tela, nome_do_spinner, console, RICH_OK, cprint, log, Table, Panel, Progress, SpinnerColumn, BarColumn, MofNCompleteColumn, box
from .playlist import parsear, nome_arquivo, sanitizar, calcular_md5, detectar_colisoes, MUTAGEN_OK
from . import playlists
from .progresso import barra_de_render
from .storage import carregar_state, salvar_state
from .tags import gravar_tags



def rebuild():
    """
    Reconstrói o sync_state.json analisando os .mp3 já existentes no disco.
    """
    limpar_tela()
    if RICH_OK:
        console.print(Panel("[bold]Reconstruindo sync_state.json[/]", border_style="blue"))
    else:
        print("Reconstruindo sync_state.json a partir dos arquivos locais...\n")

    playlist = list(playlists.todas_as_musicas())
    state = carregar_state()
    n_antes = len(state)

    if not config.STATE_FILE.exists():
        salvar_state({})
        log.info("sync_state.json criado do zero.")

    por_nome: dict = {}
    for vid, info in list(state.items()):
        if not isinstance(info, dict):
            continue
        nome = info.get("name", "").strip()
        if nome:
            por_nome.setdefault(nome, []).append((vid, info))

    consolidados = 0
    for nome, entradas in por_nome.items():
        if len(entradas) <= 1:
            continue
        def score_entrada(e):
            vid, info = e
            return (1 if info.get("url") else 0, 1 if info.get("hash") else 0, -1 if vid.startswith("rebuild_") else 0)
        entradas_ord = sorted(entradas, key=score_entrada, reverse=True)
        for vid, _ in entradas_ord[1:]:
            del state[vid]
            consolidados += 1

    # Mitigação: avisa colisões antes de montar o mapa nome_arquivo → chave,
    # em vez de deixar a última música da playlist sobrescrever a anterior
    # silenciosamente no dict.
    colisoes = detectar_colisoes(playlist)
    if colisoes and RICH_OK:
        console.print(f"[yellow]⚠ {len(colisoes)} colisão(ões) de nome de arquivo na playlist — um .mp3 pode ser atribuído à música errada. Veja Auditoria (opção 5).[/]")

    mapa = {}
    for chave in playlist:
        a, t = parsear(chave)
        mapa[nome_arquivo(a, t)] = chave
        mapa[sanitizar(chave)] = chave

    adicionados = 0
    nao_mapeados = []
    nomes_no_state = {info.get("name", "") for info in state.values() if isinstance(info, dict)}

    for f in config.DOWNLOAD_DIR.glob("*.mp3"):
        if f.stem.startswith("__dl_"):
            continue
        chave = mapa.get(f.stem)
        if chave:
            if chave in nomes_no_state:
                continue
            key = f"rebuild_{sanitizar(chave)}"
            state[key] = {
                "name": chave, "url": "", "hash": calcular_md5(f),
                "downloaded_at": datetime.now().isoformat(),
            }
            nomes_no_state.add(chave)
            adicionados += 1
        else:
            nao_mapeados.append(f.stem)

    salvar_state(state)
    n_depois = len(state)

    if RICH_OK:
        t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
        t.add_column(style="dim", width=34)
        t.add_column(style="bold cyan", justify="right")
        t.add_row("Entradas no state antes", str(n_antes))
        t.add_row("Duplicatas consolidadas", f"[yellow]{consolidados}[/]" if consolidados else "[green]0[/]")
        t.add_row("Novos registros adicionados", f"[green]{adicionados}[/]" if adicionados else "0")
        t.add_row("Entradas no state agora", str(n_depois))
        console.print(Panel(t, title="[bold]REGISTRAR MP3s DO DISCO[/]", border_style="green" if not nao_mapeados else "yellow"))
    else:
        print(f"State antes  : {n_antes}")
        print(f"State agora  : {n_depois}")

    log.info(f"Rebuild — {consolidados} duplicatas consolidadas, {adicionados} adicionadas, state: {n_antes}→{n_depois}.")


def fix_tags():
    limpar_tela()
    if not MUTAGEN_OK:
        cprint("[red]mutagen não instalado:[/] pip install mutagen")
        return
    arquivos = [f for f in config.DOWNLOAD_DIR.glob("*.mp3") if not f.stem.startswith("__dl_")]
    ok = 0
    if RICH_OK:
        with Progress(SpinnerColumn(nome_do_spinner()), BarColumn(bar_width=36), MofNCompleteColumn(), console=console) as prog:
            task = prog.add_task("Tags...", total=len(arquivos))
            for f in arquivos:
                if " - " in f.stem:
                    titulo, artista = f.stem.split(" - ", 1)
                    gravar_tags(f, artista.strip(), titulo.strip())
                    ok += 1
                prog.advance(task)
        cprint(f"[green]✓ Metadados gravados em {ok} arquivos.[/]")
    else:
        for f in arquivos:
            if " - " in f.stem:
                titulo, artista = f.stem.split(" - ", 1)
                gravar_tags(f, artista.strip(), titulo.strip())
                ok += 1
        print(f"\nOK: {ok}")


def reaplicar_audio(nome_playlist: str | None = None, preset_id: str | None = None):
    """
    Re-renderiza as playlists do perfil com o preset de EQ/loudness — só a
    playlist `nome_playlist`, ou todas quando for None.

    `preset_id` escolhe QUAL EQ aplicar: um id de eq_presets.PRESETS é salvo
    como o preset de cada playlist alvo (igual à opção "Configurar EQ") e
    aplicado em seguida; None mantém o preset que cada playlist já tem.

    A marca de perfil gravada em cada MP3 renderizado já
    reflete o preset e a receita de EQ atuais (ver audio.perfil_atual),
    então isso naturalmente pula o que não mudou e só reprocessa o que
    precisa — preset trocado numa playlist, ou mudança na receita de EQ
    no código (eq_presets.py).
    """
    limpar_tela()
    import shutil
    if not shutil.which("ffmpeg"):
        cprint("[red]FFmpeg não encontrado no PATH.[/]")
        return
    if preset_id is not None and not eq_presets.preset_valido(preset_id):
        cprint(f"[red]Preset desconhecido: {preset_id}[/]" if RICH_OK else f"Preset desconhecido: {preset_id}")
        return
    existentes = playlists.listar_playlists()
    if nome_playlist is not None:
        if nome_playlist not in existentes:
            cprint(f"[red]Playlist '{nome_playlist}' não encontrada.[/]" if RICH_OK else f"Playlist '{nome_playlist}' nao encontrada.")
            return
        nomes = [nome_playlist]
    else:
        nomes = existentes
    if not nomes:
        cprint("[yellow]Nenhuma playlist encontrada.[/]")
        return

    if preset_id is not None:
        trocadas = [n for n in nomes if playlists.ler_preset(n) != preset_id]
        for n in trocadas:
            playlists.definir_preset(n, preset_id)
        rotulo = eq_presets.PRESETS[preset_id]["label"]
        log.info(f"Reaplicar áudio — preset '{preset_id}' definido em {len(trocadas)} playlist(s): {', '.join(trocadas) or '-'}")
        cprint(f"[cyan]EQ '{rotulo}': {len(trocadas)} playlist(s) mudaram de preset, {len(nomes) - len(trocadas)} já usavam.[/]"
               if RICH_OK else f"EQ {rotulo}: {len(trocadas)} playlist(s) mudaram de preset.")

    total_criados, total_removidos, total_faltando = 0, 0, 0

    def _processar(n, cb=None):
        nonlocal total_criados, total_removidos, total_faltando
        criados, removidos, faltando = playlists.reconciliar_links(n, cb)
        total_criados += criados
        total_removidos += removidos
        total_faltando += len(faltando)

    for i, n in enumerate(nomes, 1):
        with barra_de_render(f"Equalizando {n} ({i}/{len(nomes)})") as cb:
            _processar(n, cb)

    log.info(f"Reaplicar áudio — {total_criados} renderizadas, {total_removidos} removidas, {total_faltando} pendentes de download.")
    cor = "green" if total_faltando == 0 else "yellow"
    msg = f"✓ Concluído: {total_criados} renderizada(s), {total_removidos} removida(s)"
    if total_faltando:
        msg += f", {total_faltando} ainda não baixada(s) no pool"
    cprint(f"[{cor}]{msg}.[/]" if RICH_OK else f"{msg}.")
