import re

from . import config
from .console_log import console, RICH_OK, cprint, log, Table, Panel, box
from .storage import carregar_falhas, carregar_cache, _escrever_json_atomico
from .search import buscar_ytmusic_detalhado, entrada_de_busca, SCORE_REVISAO
from .playlist import extrair_video_id, classificar_erro, nome_arquivo, parsear



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
        # Mesma classificação usada no download: cobre formato/copyright e
        # também "This video is (not) available" (URL morta), que antes
        # ficava de fora e nunca era re-buscada.
        if classificar_erro(str(falhas[nome])) not in ("permanent", "format"):
            continue
        det = buscar_ytmusic_detalhado(nome)
        nova_url = det["url"] if det else None
        if det and nova_url != cache.get(nome, {}).get("url", ""):
            cache[nome] = entrada_de_busca(det, cache.get(nome))
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
        salvar_cache_entrada(nome, {"url": url, "id": vid, "origem": "manual", "revisado": True})
        # Remove o skip antigo (o vídeo velho está indisponível) pra o Sync retentar com a URL nova.
        for k in [k for k, v in state.items() if isinstance(v, dict) and v.get("skipped") and v.get("name") == nome]:
            del state[k]
        salvar_state(state)
        log.info(f"[URL MANUAL] {nome} → {url}")
        cprint(f"[green]✓ Salvo:[/] {nome} → {url}" if RICH_OK else f"Salvo: {nome} -> {url}")
        nomes.remove(nome)

    cprint("[green]Todas resolvidas — rode o Sync (1) para baixar.[/]" if RICH_OK else "Todas resolvidas.")


def pendentes_de_revisao(cache: dict, incluir_todas: bool = False) -> list[tuple[str, dict]]:
    """URLs achadas automaticamente (auto=True) que ainda não foram revisadas, da
    menos para a mais confiável. Por padrão só as com score abaixo de SCORE_REVISAO."""
    achadas = []
    for nome, d in cache.items():
        if not isinstance(d, dict) or not d.get("auto") or d.get("revisado") or not d.get("url"):
            continue
        if incluir_todas or float(d.get("score", 0)) < SCORE_REVISAO:
            achadas.append((nome, d))
    return sorted(achadas, key=lambda par: float(par[1].get("score", 0)))


def _descartar_download(nome: str) -> int:
    """Remove o MP3 do pool, o registro no sync_state e os renders de todas as
    playlists de uma música cuja URL foi rejeitada. Devolve quantos itens saíram."""
    from . import playlists
    from .storage import carregar_state, salvar_state

    removidos = 0
    arq = config.DOWNLOAD_DIR / f"{nome_arquivo(*parsear(nome))}.mp3"
    if arq.exists():
        arq.unlink()
        removidos += 1
    state = carregar_state()
    chaves = [k for k, v in state.items() if isinstance(v, dict) and v.get("name") == nome]
    for k in chaves:
        del state[k]
    if chaves:
        salvar_state(state)
        removidos += len(chaves)
    return removidos + playlists.invalidar_render(nome)


def _perguntar(texto: str) -> str | None:
    try:
        return input(texto).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def revisar_urls_automaticas(incluir_todas: bool = False):
    """
    Fila de revisão: mostra, uma a uma, as URLs que a busca automática achou com
    pouca confiança. Para cada uma: aceitar, rejeitar (descarta o download e busca
    outro vídeo no próximo Sync), colar outra URL, pular ou sair.
    """
    from .storage import salvar_cache_entrada

    fila = pendentes_de_revisao(carregar_cache(), incluir_todas)
    if not fila:
        cprint("[green]✓ Nenhuma URL pendente de revisão.[/]" if RICH_OK else "Nenhuma URL pendente de revisao.")
        return
    total = len(fila)
    cprint(f"[bold]{total} URL(s) pra revisar[/] [dim](da menos para a mais confiável)[/]" if RICH_OK else f"{total} URL(s) pra revisar")

    for i, (nome, d) in enumerate(fila, 1):
        print()
        if RICH_OK:
            cprint(f"[bold cyan][{i}/{total}][/] Pedido:  [white]{nome}[/]")
            cprint(f"         Achado:  [yellow]{d.get('video', '?')}[/]  [dim](confiança {d.get('score', '?')})[/]")
            cprint(f"         Link:    {d['url']}")
        else:
            print(f"[{i}/{total}] Pedido: {nome}")
            print(f"  Achado: {d.get('video', '?')} (confianca {d.get('score', '?')})")
            print(f"  Link: {d['url']}")
        resp = _perguntar("  [Enter] aceitar · [r] rejeitar · [u] colar outra URL · [p] pular · [q] sair > ")
        if resp is None or resp.lower() == "q":
            return
        resp = resp.lower()
        if resp == "p":
            continue
        if resp == "":
            salvar_cache_entrada(nome, {**d, "revisado": True})
            log.info(f"[REVISAO] aceita: {nome} -> {d['url']}")
            continue

        novo_id = ""
        if resp == "u":
            entrada = _perguntar("  Cole a URL (ou o ID do vídeo) > ")
            if entrada is None:
                return
            novo_id = _extrair_id_manual(entrada)
            if not novo_id:
                cprint("[red]  URL/ID não reconhecido — pulando.[/]" if RICH_OK else "  URL invalida - pulando.")
                continue
            if novo_id == d.get("id"):
                salvar_cache_entrada(nome, {**d, "revisado": True})
                continue
        elif resp != "r":
            cprint("[yellow]  Opção não reconhecida — pulando.[/]" if RICH_OK else "  Opcao nao reconhecida - pulando.")
            continue

        arq = config.DOWNLOAD_DIR / f"{nome_arquivo(*parsear(nome))}.mp3"
        if arq.exists():
            c = _perguntar("  Isso apaga o MP3 já baixado dessa música (e os renders). Confirmar? [s/N] > ")
            if c is None:
                return
            if c.lower() != "s":
                cprint("[yellow]  Mantido — nada foi alterado.[/]" if RICH_OK else "  Mantido.")
                continue
        _descartar_download(nome)
        rejeitados = list(dict.fromkeys([*(d.get("rejeitados") or []), d.get("id", "")]))
        rejeitados = [r for r in rejeitados if r]
        if resp == "u":
            salvar_cache_entrada(nome, {"url": f"https://www.youtube.com/watch?v={novo_id}", "id": novo_id,
                                        "origem": "manual", "revisado": True, "rejeitados": rejeitados})
            cprint("[green]  ✓ URL trocada — rode o Sync pra baixar.[/]" if RICH_OK else "  URL trocada - rode o Sync.")
        else:
            salvar_cache_entrada(nome, {"url": "", "id": "", "rejeitados": rejeitados})
            cprint("[green]  ✓ Rejeitada — o próximo Sync busca outro vídeo.[/]" if RICH_OK else "  Rejeitada - o proximo Sync busca outro video.")
        log.info(f"[REVISAO] {'URL manual' if resp == 'u' else 'rejeitada'}: {nome} (antes: {d['url']})")


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
        elif not url_pattern.match(url) or not extrair_video_id(url):
            # domínio errado OU ID de vídeo que não tem exatamente 11 caracteres
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
