import os

from . import config
from .console_log import console, RICH_OK, log
from .playlist import parsear, nome_arquivo, checar_integridade, detectar_colisoes
from . import playlists
from .storage import carregar_cache, carregar_state, carregar_falhas

if RICH_OK:
    from rich.table import Table
    from rich.panel import Panel
    from rich import box


def auditoria(nome_playlist: str | None = None):
    """
    Compara três fontes de verdade:
      playlist.txt da(s) playlist(s)  → o que você QUER ter
      sync_state.json                 → o que o sistema ACHA que foi baixado
      pasta Musicas/ (pool central)   → o que realmente EXISTE no disco

    nome_playlist=None audita a união de todas as playlists do perfil.
    Órfãos no disco são sempre calculados contra a união de TODAS as
    playlists, mesmo quando auditando uma só — um arquivo só é órfão de
    verdade se nenhuma playlist do perfil precisa dele.
    """
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    todas = playlists.todas_as_musicas()
    playlist = list(todas) if nome_playlist is None else playlists.carregar_playlist(nome_playlist)
    cache = carregar_cache()
    state = carregar_state()
    falhas = carregar_falhas()
    arquivos_mp3 = [f for f in config.DOWNLOAD_DIR.glob("*.mp3") if not f.stem.startswith("__dl_")]
    disco = {f.stem for f in arquivos_mp3}
    corrompidos = [f for f in arquivos_mp3 if not checar_integridade(f)]

    vistos_pl, duplicatas_playlist = set(), []
    for nome in playlist:
        if nome in vistos_pl and nome not in duplicatas_playlist:
            duplicatas_playlist.append(nome)
        vistos_pl.add(nome)

    playlist_set = set(playlist)

    # Bug 18: separa entradas baixadas (têm/tiveram arquivo real) de
    # entradas skipped (nunca tiveram arquivo) ao calcular "removidas".
    nomes_baixados = {info.get("name", "") for info in state.values() if isinstance(info, dict) and not info.get("skipped")}
    puladas = {info.get("name", "") for info in state.values() if isinstance(info, dict) and info.get("skipped")}
    faltando = [n for n in playlist_set if n not in nomes_baixados and n not in puladas]
    removidas = [n for n in nomes_baixados if n and n not in playlist_set]
    puladas_removidas = [n for n in puladas if n and n not in playlist_set]

    sem_url = [n for n in playlist_set if n not in cache or not cache[n].get("url")]
    nomes_esperados = {nome_arquivo(*parsear(n)) for n in playlist_set}
    nomes_esperados_pool = {nome_arquivo(*parsear(n)) for n in todas}
    orfaos = disco - nomes_esperados_pool

    # Mitigação bug 16: colisões de nome de arquivo entre entradas distintas da playlist
    colisoes = detectar_colisoes(playlist)

    if RICH_OK:
        t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
        t.add_column(style="dim", width=32)
        t.add_column(style="bold cyan", justify="right", width=8)
        t.add_row("Músicas na playlist", str(len(playlist)))
        t.add_row("Registradas no estado", str(len(nomes_baixados)))
        t.add_row("Arquivos no disco", str(len(disco)))
        t.add_row("Faltando baixar", f"[red]{len(faltando)}[/]" if faltando else "[green]0[/]")
        t.add_row("Removidas da playlist (com arquivo)", f"[yellow]{len(removidas)}[/]" if removidas else "0")
        t.add_row("Puladas removidas da playlist (sem arquivo)", f"[dim]{len(puladas_removidas)}[/]" if puladas_removidas else "0")
        t.add_row("Sem URL no cache", f"[yellow]{len(sem_url)}[/]" if sem_url else "0")
        t.add_row("Órfãos no disco", f"[dim]{len(orfaos)}[/]" if orfaos else "0")
        t.add_row("Puladas (indisponíveis)", f"[yellow]{len(puladas)}[/]" if puladas else "0")
        t.add_row("Corrompidos no disco", f"[red]{len(corrompidos)}[/]" if corrompidos else "[green]0[/]")
        if colisoes:
            t.add_row("Colisões de nome de arquivo", f"[red]{len(colisoes)}[/]")
        if falhas:
            t.add_row("Falhas do último sync", f"[red]{len(falhas)}[/]")
        titulo_alvo = "TODAS AS PLAYLISTS" if nome_playlist is None else nome_playlist
        console.print(Panel(t, title=f"[bold]AUDITORIA — {titulo_alvo}[/]", border_style="blue"))

        legenda = (
            "[bold white]Faltando baixar[/]         → na playlist mas ainda não baixadas\n"
            "[bold white]Removidas da playlist[/]   → baixadas mas você removeu do playlist.txt\n"
            "                            (o próximo Sync deleta os arquivos)\n"
            "[bold white]Puladas removidas[/]       → estavam puladas (copyright) e saíram da playlist\n"
            "                            (não há arquivo — nada a deletar)\n"
            "[bold white]Sem URL no cache[/]        → sem URL no playlist_cache.json, não podem ser baixadas\n"
            "[bold white]Órfãos no disco[/]         → .mp3 que não correspondem a nenhuma música da playlist\n"
            "[bold white]Corrompidos[/]             → .mp3 com tamanho ok mas áudio inválido (use Sync para rebaixar)"
        )
        console.print(Panel(f"[dim]{legenda}[/]", title="[dim]LEGENDA[/]", border_style="dim"))

        if duplicatas_playlist:
            console.print(Panel(f"[yellow]⚠ {len(duplicatas_playlist)} música(s) duplicada(s) no playlist.txt — use opção 3 para remover[/]", border_style="yellow"))

        if colisoes:
            ct = Table(box=box.SIMPLE, show_header=True, header_style="bold red")
            ct.add_column("Nome de arquivo", style="dim")
            ct.add_column("Músicas em conflito", style="red")
            for arq, chaves in list(colisoes.items())[:10]:
                ct.add_row(arq, " / ".join(chaves))
            console.print(Panel(ct, title="[bold red]COLISÕES DE NOME DE ARQUIVO[/]", border_style="red"))

        if faltando:
            ft = Table(box=box.SIMPLE, show_header=False)
            ft.add_column(style="dim")
            for m in faltando[:25]:
                ft.add_row(m)
            console.print(Panel(ft, title=f"[bold red]Faltando baixar ({len(faltando)})[/]", border_style="red"))
    else:
        print("\n=== AUDITORIA ===\n")
        print(f"Músicas na playlist       : {len(playlist)}")
        print(f"Faltando baixar           : {len(faltando)}")
        print(f"Removidas da playlist     : {len(removidas)}")
        print(f"Puladas removidas         : {len(puladas_removidas)}")
        if colisoes:
            print(f"Colisões de nome          : {len(colisoes)}")
