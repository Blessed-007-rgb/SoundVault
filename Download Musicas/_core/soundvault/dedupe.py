import os
from datetime import datetime
from pathlib import Path

from . import config
from .console_log import console, RICH_OK, log, cprint
from .playlist import parsear, nome_arquivo, calcular_md5
from . import playlists

if RICH_OK:
    from rich.table import Table
    from rich.panel import Panel
    from rich import box


def clean():
    """Remove do sync_state entradas cujo .mp3 não existe mais no disco."""
    from .storage import carregar_state, salvar_state
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    state = carregar_state()
    nomes_playlist = playlists.todas_as_musicas()

    removidos_state, removidos_skip, removidos_orfaos = [], [], []

    for vid, info in list(state.items()):
        if not isinstance(info, dict):
            del state[vid]
            removidos_orfaos.append(vid)
            continue
        nome = info.get("name", "").strip()
        skipped = info.get("skipped", False)
        if not nome:
            del state[vid]
            removidos_orfaos.append(vid)
            continue
        if skipped:
            if nome not in nomes_playlist:
                del state[vid]
                removidos_skip.append(nome)
            continue
        artista, titulo = parsear(nome)
        arquivo = config.DOWNLOAD_DIR / f"{nome_arquivo(artista, titulo)}.mp3"
        if not arquivo.exists():
            del state[vid]
            removidos_state.append(nome)

    total_removidos = len(removidos_state) + len(removidos_skip) + len(removidos_orfaos)
    if total_removidos:
        salvar_state(state)

    if RICH_OK:
        t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
        t.add_column(style="dim", width=36)
        t.add_column(style="bold cyan", justify="right")
        n_antes = len(state) + total_removidos
        t.add_row("Entradas verificadas", str(n_antes))
        t.add_row("Entradas restantes no estado", str(len(state)))
        t.add_row("Sem .mp3 no disco (removidas)", f"[yellow]{len(removidos_state)}[/]" if removidos_state else "[green]0[/]")
        t.add_row("Skips fora da playlist (removidos)", f"[yellow]{len(removidos_skip)}[/]" if removidos_skip else "[green]0[/]")
        t.add_row("Entradas inválidas (removidas)", f"[yellow]{len(removidos_orfaos)}[/]" if removidos_orfaos else "[green]0[/]")
        bstyle = "yellow" if total_removidos else "green"
        console.print(Panel(t, title="[bold]LIMPAR REGISTROS[/]", border_style=bstyle))
    else:
        print(f"\nRemovidas (sem .mp3) : {len(removidos_state)}")
        print(f"Removidas (skip)     : {len(removidos_skip)}")

    log.info(f"Clean — {len(removidos_state)} sem .mp3, {len(removidos_skip)} skips, {len(removidos_orfaos)} inválidas removidas.")


def detectar_duplicatas() -> dict:
    """Encontra arquivos MP3 duplicados no disco por hash MD5."""
    hashes: dict = {}
    arquivos = [f for f in config.DOWNLOAD_DIR.glob("*.mp3") if not f.stem.startswith("__dl_")]
    for f in arquivos:
        h = calcular_md5(f)
        if not h:  # bug 14: leitura falhou (arquivo travado) — pula, não conta como duplicata
            continue
        hashes.setdefault(h, []).append(f)
    return {h: paths for h, paths in hashes.items() if len(paths) > 1}


def limpar_duplicatas_playlist(nome: str):
    """Remove entradas duplicadas do playlist.txt de UMA playlist, mantendo a primeira ocorrência."""
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    playlist_txt = playlists.caminho_playlist_txt(nome)
    if not playlist_txt.exists():
        cprint(f"[yellow]playlist.txt da playlist '{nome}' não encontrado.[/]")
        return

    linhas = playlist_txt.read_text(encoding="utf-8-sig").splitlines()
    vistos, unicas, removidas = set(), [], []
    for linha in linhas:
        stripped = linha.strip()
        if not stripped:
            continue
        if stripped in vistos:
            removidas.append(stripped)
        else:
            vistos.add(stripped)
            unicas.append(stripped)

    if not removidas:
        cprint("[green]✓ Nenhuma duplicata encontrada no playlist.txt[/]" if RICH_OK else "Nenhuma duplicata encontrada.")
        return

    tmp = playlist_txt.with_name(playlist_txt.name + ".tmp")
    tmp.write_text("\n".join(unicas) + "\n", encoding="utf-8")
    # Bug 6: nome do backup com timestamp — preserva histórico em vez de
    # sobrescrever o .bak a cada execução (duas execuções seguidas não
    # destroem mais os dados originais).
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = playlist_txt.with_name(f"{playlist_txt.stem}.{ts}.txt.bak")
    playlist_txt.replace(bak)
    os.replace(tmp, playlist_txt)
    log.info(f"limpar_duplicatas_playlist: {len(removidas)} duplicatas removidas, backup em {bak}")

    if RICH_OK:
        t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
        t.add_column(style="dim", width=34)
        t.add_column(style="bold cyan", justify="right", width=8)
        t.add_row("Entradas originais", str(len(linhas)))
        t.add_row("Duplicatas removidas", f"[yellow]{len(removidas)}[/]")
        t.add_row("Entradas restantes", str(len(unicas)))
        t.add_row("Backup salvo em", bak.name)
        console.print(Panel(t, title="[bold]DUPLICATAS REMOVIDAS DO PLAYLIST.TXT[/]", border_style="yellow"))
    else:
        print(f"Duplicatas removidas: {len(removidas)}")


def limpar_duplicatas():
    """
    Detecta e remove duplicatas de MP3 por MD5.
    Bug 17: o critério de qual arquivo manter agora valida contra o nome
    de arquivo esperado pela playlist ATUAL (playlist.txt), não apenas
    "tem ' - ' no nome" — evita manter uma cópia com nome desatualizado.
    """
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    if RICH_OK:
        console.print(Panel("[bold]Escaneando duplicatas por MD5...[/]", border_style="blue"))
    else:
        print("\nEscaneando duplicatas...\n")

    duplicatas = detectar_duplicatas()
    if not duplicatas:
        cprint("[green]✓ Nenhuma duplicata encontrada.[/]" if RICH_OK else "Nenhuma duplicata encontrada.")
        return

    nomes_validos = {nome_arquivo(*parsear(n)) for n in playlists.todas_as_musicas()}

    removidos, erros = [], []
    for md5, paths in duplicatas.items():
        def score(p: Path) -> int:
            if p.stem in nomes_validos:
                return 2
            if " - " in p.stem and not p.stem.startswith("__dl_"):
                return 1
            return 0
        paths_ord = sorted(paths, key=score, reverse=True)
        manter = paths_ord[0]
        apagar = paths_ord[1:]
        for p in apagar:
            try:
                p.unlink()
                removidos.append((p.name, manter.name))
                log.info(f"[DEDUP] Removido: {p.name} (duplicata de {manter.name})")
            except Exception as e:
                erros.append((p.name, str(e)))
                log.warning(f"[DEDUP] Falha ao remover {p.name}: {e}")

    if RICH_OK:
        t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
        t.add_column(style="dim", width=26)
        t.add_column(style="bold cyan", justify="right")
        t.add_row("Grupos duplicados", str(len(duplicatas)))
        t.add_row("Arquivos removidos", f"[green]{len(removidos)}[/]" if removidos else "0")
        console.print(Panel(t, title="[bold]DUPLICATAS[/]", border_style="green" if not erros else "yellow"))
    else:
        print(f"\nDuplicatas encontradas: {len(duplicatas)}")
        print(f"Arquivos removidos    : {len(removidos)}")

    log.info(f"Dedup — {len(duplicatas)} grupos, {len(removidos)} removidos, {len(erros)} erros.")
