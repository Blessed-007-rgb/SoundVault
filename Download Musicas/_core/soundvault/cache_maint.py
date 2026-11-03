import re

from . import config
from .console_log import console, RICH_OK, cprint, log
from .storage import carregar_falhas, carregar_cache, _escrever_json_atomico
from .search import buscar_ytmusic
from .playlist import extrair_video_id

if RICH_OK:
    from rich.table import Table
    from rich.panel import Panel
    from rich import box


def atualizar_urls_mortas(cache: dict, playlist: list) -> int:
    """
    Para músicas que falharam por formato/copyright, busca nova URL no YouTube Music
    e atualiza o cache automaticamente. Retorna número de URLs atualizadas.
    """
    falhas = carregar_falhas()
    if not falhas:
        return 0
    atualizados = 0
    for nome in playlist:
        if nome not in falhas:
            continue
        motivo = falhas[nome].lower()
        if "requested format is not available" not in motivo and "copyright" not in motivo:
            continue
        nova_url = buscar_ytmusic(nome)
        if nova_url and nova_url != cache.get(nome, {}).get("url", ""):
            cache[nome] = {"url": nova_url, "id": extrair_video_id(nova_url)}
            atualizados += 1
            log.info(f"[CACHE] URL morta substituída: {nome} → {nova_url}")
    if atualizados:
        _escrever_json_atomico(config.CACHE_FILE, cache)
    return atualizados


def _extrair_id_manual(texto: str) -> str:
    """Aceita URL do YouTube/YT Music (watch?v=, youtu.be/) ou o ID puro de 11 caracteres."""
    texto = texto.strip()
    if re.fullmatch(r"[\w-]{11}", texto):
        return texto
    return extrair_video_id(texto)


def definir_url_manual():
    """
    Permite colar manualmente a URL de músicas que a busca automática não
    achou (sem URL no cache), que falharam ou que foram puladas por copyright.
    Salva no playlist_cache.json e libera o skip — depois é só rodar o Sync.
    """
    from .storage import carregar_state, salvar_state, salvar_cache_entrada

    cache = carregar_cache()
    falhas = carregar_falhas()
    state = carregar_state()

    pendentes = {}  # nome -> motivo
    for nome, dados in cache.items():
        if not isinstance(dados, dict) or not dados.get("url"):
            pendentes[nome] = "sem URL no cache"
    for nome, motivo in falhas.items():
        pendentes.setdefault(nome, str(motivo)[:70])
    for info in state.values():
        if isinstance(info, dict) and info.get("skipped") and info.get("name"):
            pendentes.setdefault(info["name"], "pulada: " + str(info.get("skip_reason", ""))[:60])

    if not pendentes:
        cprint("[green]✓ Nenhuma música sem URL, com falha ou pulada.[/]" if RICH_OK else "Nada pendente.")
        return

    nomes = sorted(pendentes)
    while nomes:
        if RICH_OK:
            t = Table(box=box.ROUNDED, show_header=True, header_style="bold dim", padding=(0, 1))
            t.add_column("#", style="dim", width=4)
            t.add_column("Música", style="white", overflow="ellipsis", max_width=58)
            t.add_column("Motivo", style="yellow dim", overflow="ellipsis", max_width=40)
            for i, n in enumerate(nomes, 1):
                t.add_row(str(i), n, pendentes[n])
            console.print(Panel(t, title=f"[bold yellow]URL MANUAL — {len(nomes)} música(s)[/]", border_style="yellow"))
            console.print("[dim]  Digite o [bold]número[/] da música, depois cole a URL do YouTube · [bold]0[/] ou Enter para sair[/]")
        else:
            for i, n in enumerate(nomes, 1):
                print(f"{i:>3}. {n}  [{pendentes[n]}]")

        try:
            escolha = input("  Música # > ").strip()
            if escolha in ("", "0"):
                return
            if not escolha.isdigit() or not (1 <= int(escolha) <= len(nomes)):
                cprint("[red]Número inválido.[/]" if RICH_OK else "Numero invalido.")
                continue
            nome = nomes[int(escolha) - 1]
            entrada = input(f"  URL para '{nome}' > ").strip()
        except (EOFError, KeyboardInterrupt):
            return

        vid = _extrair_id_manual(entrada)
        if not vid:
            cprint("[red]URL/ID não reconhecido — cole um link tipo https://www.youtube.com/watch?v=XXXXXXXXXXX[/]" if RICH_OK
                   else "URL invalida.")
            continue

        url = f"https://www.youtube.com/watch?v={vid}"
        salvar_cache_entrada(nome, {"url": url, "id": vid})
        # Remove o skip antigo (o vídeo velho está indisponível) pra o Sync retentar com a URL nova.
        for k in [k for k, v in state.items() if isinstance(v, dict) and v.get("skipped") and v.get("name") == nome]:
            del state[k]
        salvar_state(state)
        log.info(f"[URL MANUAL] {nome} → {url}")
        cprint(f"[green]✓ Salvo:[/] {nome} → {url}" if RICH_OK else f"Salvo: {nome} -> {url}")
        nomes.remove(nome)

    cprint("[green]Todas resolvidas — rode o Sync (1) para baixar.[/]" if RICH_OK else "Todas resolvidas.")


def validar_cache(cache: dict) -> dict:
    """
    Valida o playlist_cache.json e retorna um relatório de problemas.
    """
    sem_url, url_invalida, id_invalido, nome_suspeito = [], [], [], []
    url_pattern = re.compile(r"https?://(www\.)?(youtube\.com|youtu\.be)/")
    id_pattern = re.compile(r"^[\w-]{11}$")

    for nome, dados in cache.items():
        if not isinstance(dados, dict):
            nome_suspeito.append(nome)
            continue
        if nome != nome.strip() or nome.startswith("﻿"):
            nome_suspeito.append(nome)
        url = dados.get("url", "")
        vid = dados.get("id", "")
        if not url:
            sem_url.append(nome)
        elif not url_pattern.match(url):
            url_invalida.append((nome, url))
        if vid and not id_pattern.match(vid):
            id_invalido.append((nome, vid))

    return {
        "sem_url": sem_url, "url_invalida": url_invalida,
        "id_invalido": id_invalido, "nome_suspeito": nome_suspeito,
        "total": len(cache),
        "problemas": len(sem_url) + len(url_invalida) + len(id_invalido) + len(nome_suspeito),
    }


def exibir_validacao_cache():
    """Valida e exibe relatório do playlist_cache.json."""
    cache = carregar_cache()
    if not cache:
        cprint("[yellow]playlist_cache.json não encontrado ou vazio.[/]" if RICH_OK else "playlist_cache.json não encontrado.")
        return

    r = validar_cache(cache)
    if r["problemas"] == 0:
        cprint(f"[green]✓ Cache validado — {r['total']} entradas, nenhum problema encontrado.[/]" if RICH_OK
               else f"Cache OK — {r['total']} entradas sem problemas.")
        return

    if RICH_OK:
        t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
        t.add_column(style="dim", width=28)
        t.add_column(style="bold cyan", justify="right")
        t.add_row("Total de entradas", str(r["total"]))
        t.add_row("Sem URL", f"[red]{len(r['sem_url'])}[/]" if r["sem_url"] else "0")
        t.add_row("URL inválida", f"[red]{len(r['url_invalida'])}[/]" if r["url_invalida"] else "0")
        t.add_row("ID inválido", f"[yellow]{len(r['id_invalido'])}[/]" if r["id_invalido"] else "0")
        t.add_row("Nome suspeito", f"[yellow]{len(r['nome_suspeito'])}[/]" if r["nome_suspeito"] else "0")
        console.print(Panel(t, title="[bold yellow]VALIDAÇÃO DO CACHE[/]", border_style="yellow"))
    else:
        print(f"\nTotal      : {r['total']}")
        print(f"Sem URL    : {len(r['sem_url'])}")
