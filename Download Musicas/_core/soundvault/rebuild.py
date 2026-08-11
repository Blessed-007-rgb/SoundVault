import os
from datetime import datetime

from . import config
from .console_log import console, RICH_OK, cprint, log
from .playlist import parsear, nome_arquivo, sanitizar, calcular_md5, detectar_colisoes, MUTAGEN_OK
from . import playlists
from .storage import carregar_state, salvar_state
from .tags import gravar_tags

if RICH_OK:
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn, TextColumn
    from rich import box


def rebuild():
    """
    Reconstrói o sync_state.json analisando os .mp3 já existentes no disco.
    """
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
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
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    if not MUTAGEN_OK:
        cprint("[red]mutagen não instalado:[/] pip install mutagen")
        return
    arquivos = [f for f in config.DOWNLOAD_DIR.glob("*.mp3") if not f.stem.startswith("__dl_")]
    ok = 0
    if RICH_OK:
        with Progress(SpinnerColumn(), BarColumn(bar_width=36), MofNCompleteColumn(), console=console) as prog:
            task = prog.add_task("Tags...", total=len(arquivos))
            for f in arquivos:
                if " - " in f.stem:
                    titulo, artista = f.stem.split(" - ", 1)
                    gravar_tags(f, artista.strip(), titulo.strip())
                    ok += 1
                prog.advance(task)
        cprint(f"[green]✓ Metadados e capas gravados em {ok} arquivos.[/]")
    else:
        for f in arquivos:
            if " - " in f.stem:
                titulo, artista = f.stem.split(" - ", 1)
                gravar_tags(f, artista.strip(), titulo.strip())
                ok += 1
        print(f"\nOK: {ok}")


def reaplicar_audio():
    """
    Re-renderiza todas as playlists do perfil com o preset de EQ/loudness
    de cada uma. A marca de perfil gravada em cada MP3 renderizado já
    reflete o preset e a receita de EQ atuais (ver audio.perfil_atual),
    então isso naturalmente pula o que não mudou e só reprocessa o que
    precisa — preset trocado numa playlist, ou mudança na receita de EQ
    no código (eq_presets.py).
    """
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    import shutil
    if not shutil.which("ffmpeg"):
        cprint("[red]FFmpeg não encontrado no PATH.[/]")
        return
    nomes = playlists.listar_playlists()
    if not nomes:
        cprint("[yellow]Nenhuma playlist encontrada.[/]")
        return

    total_criados, total_removidos, total_faltando = 0, 0, 0

    def _processar(n):
        nonlocal total_criados, total_removidos, total_faltando
        criados, removidos, faltando = playlists.reconciliar_links(n)
        total_criados += criados
        total_removidos += removidos
        total_faltando += len(faltando)

    if RICH_OK:
        with Progress(
            SpinnerColumn(), TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=36), MofNCompleteColumn(), TimeElapsedColumn(), console=console,
        ) as prog:
            task = prog.add_task("Playlists...", total=len(nomes))
            for n in nomes:
                _processar(n)
                prog.advance(task)
    else:
        for n in nomes:
            _processar(n)

    log.info(f"Reaplicar áudio — {total_criados} renderizadas, {total_removidos} removidas, {total_faltando} pendentes de download.")
    cor = "green" if total_faltando == 0 else "yellow"
    msg = f"✓ Concluído: {total_criados} renderizada(s), {total_removidos} removida(s)"
    if total_faltando:
        msg += f", {total_faltando} ainda não baixada(s) no pool"
    cprint(f"[{cor}]{msg}.[/]" if RICH_OK else f"{msg}.")
