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
