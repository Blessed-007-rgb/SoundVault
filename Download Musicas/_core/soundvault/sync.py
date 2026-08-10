import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from . import config, cookies, download
from .console_log import console, RICH_OK, log, cprint
from .lock import adquirir_lock, liberar_lock, LockError
from .playlist import parsear, nome_arquivo, sanitizar, extrair_video_id
from . import playlists
from .storage import carregar_cache, carregar_state, carregar_falhas, salvar_state, salvar_falhas, salvar_historico, salvar_cache_entrada
from .search import buscar_ytmusic
from .cache_maint import atualizar_urls_mortas, validar_cache

if RICH_OK:
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn, TextColumn
    from rich.prompt import Prompt
    from rich import box

# Acima desse número de remoções num único Sync, pede confirmação antes
# de apagar — evita que um erro no playlist.txt (ex: linha apagada por
# engano) derrube um monte de MP3 sem aviso.
LIMITE_CONFIRMACAO_REMOCAO = 3


def limpar_temporarios():
    """Remove arquivos __dl_* que ficaram de downloads interrompidos."""
    orphans = list(config.DOWNLOAD_DIR.glob("__dl_*"))
    for f in orphans:
        f.unlink(missing_ok=True)
    if orphans:
        log.info(f"Limpeza: {len(orphans)} arquivo(s) temporário(s) removido(s).")
    return len(orphans)


def verificar_atualizar_ytdlp():
    """Verifica/atualiza o yt-dlp em background (não bloqueia o sync)."""
    def _check():
        try:
            result = subprocess.run(
                ["yt-dlp", "--update-to", "stable"],
                capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})
            )
            saida = result.stdout + result.stderr
            if "Updated" in saida or "Updating" in saida:
                log.info(f"[yt-dlp] Atualizado automaticamente: {saida.strip().split(chr(10))[0]}")
                if RICH_OK:
                    console.print("[dim]  ✓ yt-dlp atualizado para a versão mais recente[/]")
            elif "up to date" in saida.lower() or "already" in saida.lower():
                log.debug("[yt-dlp] Já está na versão mais recente.")
        except subprocess.TimeoutExpired:
            log.debug("[yt-dlp] Timeout ao verificar atualização — continuando.")
        except FileNotFoundError:
            log.warning("[yt-dlp] Executável não encontrado no PATH.")
        except Exception as e:
            log.debug(f"[yt-dlp] Erro ao verificar atualização: {e}")

    t = threading.Thread(target=_check, daemon=True)
    t.start()
    return t


def resetar_skips_formato():
    """
    Remove do sync_state entradas skipped cujo motivo é erro de formato.
    Essas músicas serão retentadas no próximo Sync com o novo formato.
    """
    state = carregar_state()
    removidos = []
    for vid, info in list(state.items()):
        if not isinstance(info, dict) or not info.get("skipped"):
            continue
        reason = info.get("skip_reason", "").lower()
        if "requested format is not available" in reason or "no video formats found" in reason:
            del state[vid]
            removidos.append(info.get("name", vid))
    if removidos:
        salvar_state(state)
    return removidos


class _DynamicGate:
    """
    Bug 4: substitui o throttling cosmético. Limita quantas tarefas rodam
    de verdade ao mesmo tempo, respeitando download._workers_ativos (que
    é reduzido dinamicamente por baixar() em resposta a HTTP 429) em vez
    de um ThreadPoolExecutor de tamanho fixo que nunca diminuía de verdade.
    """
    def __init__(self):
        self._cond = threading.Condition()
        self._em_execucao = 0

    def acquire(self):
        with self._cond:
            while self._em_execucao >= download._workers_ativos:
                self._cond.wait(timeout=0.5)
            self._em_execucao += 1

    def release(self):
        with self._cond:
            self._em_execucao -= 1
            self._cond.notify_all()


def sincronizar(nome_playlist: str | None = None, apenas_falhas: bool = False):
    adquirir_lock()
    cookies.reset_sessao()
    try:
        os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
        log.debug("sincronizar() chamada")
        log.info(f"=== INICIANDO SYNC — perfil: {config.BASE_DIR.name} | DOWNLOAD_DIR: {config.DOWNLOAD_DIR} ===")
        if RICH_OK:
            console.print(f"[dim]  Perfil: [cyan]{config.BASE_DIR.name}[/] | Destino: [cyan]{config.DOWNLOAD_DIR}[/][/]")

        _cache_tmp = carregar_cache()
        if _cache_tmp:
            _r = validar_cache(_cache_tmp)
            if _r["problemas"] > 0 and RICH_OK:
                console.print(f"[yellow dim]  ⚠ playlist_cache.json tem {_r['problemas']} problema(s) — use Validar Cache para detalhes.[/]")

        # Health-check do cookie ANTES de baixar — sem isso, um cookie
        # expirado só era descoberto no meio da fila, depois de já ter
        # gasto tempo/tentativas em várias músicas. Throttled internamente
        # (COOKIE_HEALTH_CHECK_INTERVAL_H) pra não gastar segundos à toa
        # em todo Sync.
        cookie_ok = cookies.verificar_cookie_valido()
        if cookie_ok is False:
            log.warning("[HEALTH] cookies.txt reprovou no teste de autenticação antes do Sync")
            if RICH_OK:
                console.print(Panel(
                    "[bold yellow]⚠  cookies.txt parece expirado (falhou teste de autenticação)![/]\n"
                    "   As músicas podem falhar. Considere renovar antes de continuar\n"
                    "   (veja o aviso 'AÇÃO NECESSÁRIA' se/quando aparecer, ou renove\n"
                    f"   manualmente em: [cyan]{config.COOKIES_FILE}[/]",
                    border_style="yellow",
                ))
            else:
                print("\n!! cookies.txt parece expirado — considere renovar antes de continuar !!")

        t_update = verificar_atualizar_ytdlp()

        n_temp = limpar_temporarios()
        if n_temp and RICH_OK:
            cprint(f"[dim]  🧹 {n_temp} arquivo(s) temporário(s) removido(s)[/]")

        t_inicio = time.time()

        _skips_resetados = resetar_skips_formato()
        if _skips_resetados and RICH_OK:
            console.print(f"[dim]  ↺ {len(_skips_resetados)} skip(s) por erro de formato resetados para retry[/]")

        alvo_nomes = [nome_playlist] if nome_playlist else playlists.listar_playlists()
        if not alvo_nomes:
            cprint("[yellow]Nenhuma playlist encontrada. Use 'Gerenciar Playlists' pra criar uma.[/]")
            return

        playlist_alvo: set[str] = set()
        for n in alvo_nomes:
            playlist_alvo.update(playlists.carregar_playlist(n))

        if not playlist_alvo:
            cprint("[yellow]Playlist vazia — nada para sincronizar.[/]")
            return

        cache = carregar_cache()
        state = carregar_state()

        nomes_concluidos = {info.get("name", "") for info in state.values() if isinstance(info, dict)}

        # Limpeza do pool central usa a união de TODAS as playlists do
        # perfil, não só a(s) selecionada(s) agora — uma música só sai
        # do pool quando nenhuma playlist mais precisa dela.
        playlist_todas = playlists.todas_as_musicas()

        # Candidatos vindo do state (música completa que saiu de toda
        # playlist) e órfãos vindo do disco (arquivo sem registro que não
        # bate com o pool esperado) são as duas fontes de exclusão — ambos
        # entram na mesma confirmação, senão um "não" no primeiro prompt
        # não impedia o segundo bloco de apagar os mesmos arquivos.
        candidatos_remocao = []
        for nome in list(nomes_concluidos):
            if nome and nome not in playlist_todas:
                artista, titulo = parsear(nome)
                arquivo = config.DOWNLOAD_DIR / f"{nome_arquivo(artista, titulo)}.mp3"
                candidatos_remocao.append((nome, arquivo))

        nomes_esperados_pool = {nome_arquivo(*parsear(n)) for n in playlist_todas}
        caminhos_candidatos = {arquivo for _, arquivo in candidatos_remocao}
        candidatos_orfaos = []
        for mp3 in list(config.DOWNLOAD_DIR.glob("*.mp3")):
            if mp3.stem.startswith("__dl_") or mp3 in caminhos_candidatos:
                continue
            if mp3.stem not in nomes_esperados_pool:
                candidatos_orfaos.append(mp3)

        total_candidatos = len(candidatos_remocao) + len(candidatos_orfaos)
        prosseguir_remocao = True
        if total_candidatos > LIMITE_CONFIRMACAO_REMOCAO:
            nomes_exibicao = [nome for nome, _ in candidatos_remocao] + [f"{p.name} [dim](órfão sem registro)[/]" for p in candidatos_orfaos]
            if RICH_OK:
                t = Table(box=box.SIMPLE, show_header=True, header_style="bold yellow")
                t.add_column("Música que será removida do disco", style="yellow")
                for nome in nomes_exibicao:
                    t.add_row(nome)
                console.print(Panel(
                    t,
                    title=f"[bold yellow]⚠ {total_candidatos} MÚSICAS SERÃO REMOVIDAS DO DISCO[/]",
                    border_style="yellow",
                ))
                resposta = Prompt.ask(
                    "  Remover esses arquivos do disco?",
                    choices=["S", "s", "N", "n"], default="S",
                ).upper()
                prosseguir_remocao = resposta == "S"
            else:
                print(f"\n{total_candidatos} musicas serão removidas:")
                for nome in nomes_exibicao:
                    print(f"  - {nome}")
                resposta = input("Remover esses arquivos do disco? [S/n]: ").strip().upper()
                prosseguir_remocao = resposta != "N"

        removidos = []
        orfaos_removidos = []
        if prosseguir_remocao:
            for nome, arquivo in candidatos_remocao:
                if arquivo.exists():
                    arquivo.unlink()
                    removidos.append(nome)
                    log.info(f"Removido do pool (fora de todas as playlists): {nome}")
                for vid, info in list(state.items()):
                    if isinstance(info, dict) and info.get("name") == nome:
                        del state[vid]
                        break
            if removidos:
                salvar_state(state)
                nomes_concluidos = {info.get("name", "") for info in state.values() if isinstance(info, dict)}

            for mp3 in candidatos_orfaos:
                try:
                    mp3.unlink()
                    orfaos_removidos.append(mp3.name)
                    log.info(f"[SYNC] Órfão removido do pool: {mp3.name}")
                except Exception as _e:
                    log.warning(f"[SYNC] Falha ao remover órfão {mp3.name}: {_e}")
            if orfaos_removidos and RICH_OK:
                console.print(f"[dim]  🗑 {len(orfaos_removidos)} arquivo(s) órfão(s) removido(s) do pool central[/]")
        elif total_candidatos:
            log.info(f"Remoção de {total_candidatos} música(s) cancelada pelo usuário — arquivos mantidos.")
            cprint("[yellow]Remoção cancelada — os arquivos continuam no disco (nada foi alterado).[/]" if RICH_OK else "Remocao cancelada.")

        if apenas_falhas:
            falhas_ant = carregar_falhas()
            if not falhas_ant:
                cprint("[yellow]Nenhuma falha anterior registrada.[/]")
                return
            pendentes = {n: cache.get(n, {}) for n in falhas_ant if n in playlist_alvo and n not in nomes_concluidos}
            if RICH_OK:
                console.print(Panel(f"[bold]Retentando [cyan]{len(pendentes)}[/cyan] músicas que falharam[/]", border_style="yellow"))
        else:
            pendentes = {nome: cache.get(nome, {}) for nome in playlist_alvo if nome not in nomes_concluidos}
            sem_url = [n for n in pendentes if not cache.get(n, {}).get("url")]

            _urls_atualizadas = atualizar_urls_mortas(cache, list(playlist_alvo))
            if _urls_atualizadas and RICH_OK:
                console.print(f"[dim]  ↺ {_urls_atualizadas} URL(s) morta(s) atualizadas no cache[/]")
            if _urls_atualizadas:
                for nome in list(pendentes.keys()):
                    if not pendentes[nome].get("url") and cache.get(nome, {}).get("url"):
                        pendentes[nome] = cache[nome]

            if RICH_OK:
                t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
                t.add_column(style="dim", width=24)
                t.add_column(style="bold cyan", justify="right", width=8)
                t.add_row("Total na playlist", str(len(playlist_alvo)))
                t.add_row("Já concluídas", str(len(nomes_concluidos)))
                t.add_row("Para baixar", str(len(pendentes)))
                if removidos:
                    t.add_row("Removidas do disco", f"[yellow]{len(removidos)}[/]")
                if sem_url:
                    t.add_row("Sem URL no cache", f"[yellow]{len(sem_url)}[/]")
                console.print(Panel(t, title="[bold]SYNC[/]", border_style="blue"))
            else:
                print(f"\nTotal na playlist : {len(playlist_alvo)}")
                print(f"Já concluídas     : {len(nomes_concluidos)}")
                print(f"Para baixar       : {len(pendentes)}")

            if sem_url:
                if RICH_OK:
                    console.print(f"[yellow]  ⚠ {len(sem_url)} música(s) sem URL — buscando no YouTube Music...[/]")
                for nome in sem_url:
                    alt = buscar_ytmusic(nome)
                    if alt:
                        alt_id = extrair_video_id(alt)
                        pendentes[nome] = {"url": alt, "id": alt_id}
                        cache[nome] = {"url": alt, "id": alt_id}
                        salvar_cache_entrada(nome, {"url": alt, "id": alt_id})
                        if RICH_OK:
                            console.print(f"  [green]✓[/] URL encontrada e salva no cache: [dim]{nome}[/]")
                        log.info(f"[AUTO-URL] {nome} → {alt} (salvo no cache)")
                    else:
                        if RICH_OK:
                            console.print(f"  [red]✗[/] Não encontrada: [dim]{nome}[/]")
                        log.warning(f"[AUTO-URL] Não encontrada: {nome}")
                pendentes = {n: d for n, d in pendentes.items() if d.get("url")}

        if not pendentes:
            cprint("[green]✓ Tudo já está sincronizado![/]")
            for n in alvo_nomes:
                playlists.reconciliar_links(n)
            return

        # Bug 20: espera o self-update do yt-dlp terminar (até 35s) antes de
        # começar downloads reais — evita o update reescrevendo arquivos
        # que os workers de download estão prestes a invocar.
        t_update.join(timeout=35)

        total = len(pendentes)
        sucessos = 0
        falhas = {}
        skips = {}
        auth_falhou = False
        # Contagem por tipo de falha final (já passou por todos os retries
        # internos de download.baixar()) — usada pra dar um aviso específico
        # em vez de só "N falhas", que não diz se é cookie, rate limit, etc.
        contagem_tipo = {"rate": 0, "format": 0, "retry": 0}
        contador = 0
        c_lock = threading.Lock()
        _tempos_dl = []
        gate = _DynamicGate()  # bug 4

        def _fmt_eta(seg):
            seg = int(seg)
            h, m = divmod(seg, 3600)
            m, s = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

        def tarefa(nome, dados):
            nonlocal contador, auth_falhou, contagem_tipo
            gate.acquire()
            try:
                _t0 = time.time()
                ok, tipo, motivo = download.baixar(nome, dados.get("url", ""), dados.get("id", ""), state)
                _dur = time.time() - _t0
            finally:
                gate.release()
            with c_lock:
                contador += 1
                _tempos_dl.append(_dur)
                restantes = total - contador
                if RICH_OK and _tempos_dl and restantes > 0:
                    media = sum(_tempos_dl) / len(_tempos_dl)
                    eta_seg = (media * restantes) / max(config.WORKERS, 1)
                    prog.update(task, description=f"Baixando... ETA {_fmt_eta(eta_seg)}")
                elif RICH_OK and restantes == 0:
                    prog.update(task, description="Baixando...")
                if ok:
                    icon = "[green]✓[/]"
                elif tipo == "permanent":
                    icon = "[yellow]⊘[/]"
                else:
                    icon = "[red]✗[/]"
                if RICH_OK:
                    # O download já terminou (ok/tipo/motivo definidos acima) —
                    # uma falha aqui é só de exibição (console legado sem
                    # UTF-8) e não pode virar exceção propagada pro chamador,
                    # que interpretaria como falha no download em si.
                    try:
                        prog.console.print(f"  {icon} {nome}")
                    except UnicodeEncodeError:
                        status = "OK" if ok else ("SKIP" if tipo == "permanent" else "FALHA")
                        print(f"  {status} [{contador}/{total}] {nome}".encode("ascii", "replace").decode("ascii"))
                else:
                    status = "OK" if ok else ("SKIP" if tipo == "permanent" else "FALHA")
                    print(f"  {status} [{contador}/{total}] {nome}")
            if tipo == "auth":
                auth_falhou = True
            elif not ok and tipo != "permanent":
                contagem_tipo[tipo] = contagem_tipo.get(tipo, 0) + 1
            return nome, ok, tipo, motivo

        def _rodar_executor():
            nonlocal sucessos
            ex = ThreadPoolExecutor(max_workers=config.WORKERS)
            try:
                futures = {ex.submit(tarefa, n, d): n for n, d in pendentes.items()}
                for future in as_completed(futures, timeout=(config.TIMEOUT_DL + 60) * len(pendentes)):
                    try:
                        nome, ok, tipo, motivo = future.result(timeout=config.TIMEOUT_DL + 30)
                    except Exception as _fe:
                        nome = futures.get(future, "desconhecida")
                        log.warning(f"Worker timeout/erro: {nome} — {_fe}")
                        falhas[nome] = str(_fe)
                        if RICH_OK:
                            prog.advance(task)
                        continue
                    if ok:
                        sucessos += 1
                        salvar_state(state)
                    elif tipo == "permanent":
                        skips[nome] = motivo
                        state[f"skip_{sanitizar(nome)}"] = {
                            "name": nome, "url": pendentes[nome].get("url", ""),
                            "skipped": True, "skip_reason": motivo,
                            "downloaded_at": datetime.now().isoformat(),
                        }
                        salvar_state(state)
                    else:
                        falhas[nome] = motivo
                    if RICH_OK:
                        prog.advance(task)
            except Exception as _exec_e:
                log.warning(f"Executor interrompido: {_exec_e}")
            finally:
                # Bug 5: wait=True — espera as threads em andamento
                # terminarem antes do finally liberar o lock, evitando
                # duas "gerações" de Sync rodando ao mesmo tempo.
                log.debug("executor.shutdown(wait=True)")
                ex.shutdown(wait=True, cancel_futures=True)

        if RICH_OK:
            with Progress(
                SpinnerColumn(), TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=34), MofNCompleteColumn(), TimeElapsedColumn(),
                console=console,
            ) as prog:
                task = prog.add_task("Baixando...", total=total)
                log.debug(f"Executor iniciado: {len(pendentes)} músicas, {config.WORKERS} workers")
                _rodar_executor()
        else:
            _rodar_executor()

        salvar_falhas(falhas)

        # Garante que cada playlist sincronizada tem link pra tudo que
        # está no playlist.txt dela e nada além disso.
        _links_criados, _links_removidos = 0, 0
        for n in alvo_nomes:
            c, r, _faltando = playlists.reconciliar_links(n)
            _links_criados += c
            _links_removidos += r
        if RICH_OK and (_links_criados or _links_removidos):
            console.print(f"[dim]  🔗 {_links_criados} link(s) criados, {_links_removidos} removidos nas playlists sincronizadas[/]")

        if RICH_OK:
            t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
            t.add_column(style="dim", width=26)
            t.add_column(justify="right", width=8)
            t.add_row("Baixadas com sucesso", f"[green]{sucessos}[/]")
            if removidos:
                t.add_row("Removidas do disco", f"[yellow]{len(removidos)}[/]")
            t.add_row("Puladas (indisponíveis)", f"[yellow]{len(skips)}[/]" if skips else "0")
            t.add_row("Falhas (podem retentar)", f"[red]{len(falhas)}[/]" if falhas else "[green]0[/]")
            if contagem_tipo["rate"]:
                t.add_row("  ↳ rate limit (429)", f"[yellow]{contagem_tipo['rate']}[/]")
            if contagem_tipo["format"]:
                t.add_row("  ↳ formato indisponível", f"[yellow]{contagem_tipo['format']}[/]")
            if contagem_tipo["retry"]:
                t.add_row("  ↳ erro de rede/outro", f"[yellow]{contagem_tipo['retry']}[/]")
            bstyle = "red" if falhas else ("yellow" if skips else "green")
            console.print(Panel(t, title="[bold]RESULTADO[/]", border_style=bstyle))
            if auth_falhou:
                console.print(Panel(
                    "[bold yellow]⚠  Cookie expirado ou inválido!\n"
                    "   Exporte um novo cookies.txt do YouTube e rode Sync novamente.[/]",
                    border_style="yellow"
                ))
            if contagem_tipo["rate"] > 0 and download._rate_limit_hits > 0:
                console.print(Panel(
                    f"[bold yellow]⚠  YouTube limitou os downloads (rate limit / HTTP 429)!\n"
                    f"   {download._rate_limit_hits} bloqueio(s) detectado(s) — workers reduzidos pra {download._workers_ativos}.\n"
                    f"   Isso é temporário: espere alguns minutos e rode 'Retentar Falhas'.[/]",
                    border_style="yellow"
                ))
            if skips:
                st = Table(box=box.SIMPLE, show_header=True, header_style="bold yellow")
                st.add_column("Música pulada", style="dim")
                st.add_column("Motivo", style="yellow")
                for n, m in list(skips.items())[:10]:
                    st.add_row(n, (m[:55] + "...") if len(m) > 55 else m)
                console.print(Panel(st, title="[bold yellow]PULADAS[/]", border_style="yellow"))
            if falhas:
                ft = Table(box=box.SIMPLE, show_header=True, header_style="bold red")
                ft.add_column("Música", style="dim")
                ft.add_column("Motivo", style="red")
                for n, m in list(falhas.items())[:15]:
                    ft.add_row(n, (m[:55] + "...") if len(m) > 55 else m)
                if len(falhas) > 15:
                    ft.add_row(f"... e mais {len(falhas)-15}", "ver falhas.json")
                console.print(Panel(ft, title="[bold red]FALHAS[/]", border_style="red"))
                cprint("[dim]  Dica: use 'Retentar Falhas' no menu para tentar novamente.[/]")
        else:
            print(f"\nSucesso: {sucessos} | Removidas: {len(removidos)} | Puladas: {len(skips)} | Falhas: {len(falhas)}")
            if auth_falhou:
                print("\n!! Cookie expirado — renove o cookies.txt !!")
            if contagem_tipo["rate"] > 0:
                print(f"\n!! YouTube limitou downloads (rate limit) {download._rate_limit_hits}x — tente novamente mais tarde !!")

        t_total = time.time() - t_inicio
        mp3s = list(config.DOWNLOAD_DIR.glob("*.mp3"))
        tam_total = sum(f.stat().st_size for f in mp3s)
        tam_str = (f"{tam_total/1024/1024/1024:.1f} GB" if tam_total > 1024**3 else f"{tam_total/1024/1024:.0f} MB")
        mins, secs = divmod(int(t_total), 60)
        dur_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        if RICH_OK:
            td = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
            td.add_column(style="dim", width=26)
            td.add_column(style="cyan", justify="right", width=10)
            td.add_row("Duração do sync", dur_str)
            td.add_row("Arquivos no disco", str(len(mp3s)))
            td.add_row("Tamanho total", tam_str)
            td.add_row("Velocidade média", f"{sucessos/(t_total/60):.1f} músicas/min" if t_total > 0 else "—")
            if download._rate_limit_hits > 0:
                td.add_row("Rate limits (429)", f"[yellow]{download._rate_limit_hits}[/]")
                td.add_row("Workers finais", str(download._workers_ativos))
            console.print(Panel(td, title="[bold]ESTATÍSTICAS[/]", border_style="dim"))

        from .console_log import notificar_windows
        # Prioriza o aviso mais acionável no título da notificação — cookie
        # expirado e rate limit exigem uma ação do usuário (renovar cookie /
        # esperar), diferente de uma falha genérica que já é sempre visível
        # no resultado do próprio Sync.
        rate_limitado = contagem_tipo["rate"] > 0 and download._rate_limit_hits > 0
        if auth_falhou:
            titulo_notify = "⚠ SoundVault — Cookie do YouTube expirou"
            msg_notify = f"{len(falhas)} música(s) não baixaram por cookie inválido. Exporte um novo cookies.txt."
        elif rate_limitado:
            titulo_notify = "⚠ SoundVault — YouTube limitou os downloads"
            msg_notify = f"Rate limit (429) detectado {download._rate_limit_hits}x. {len(falhas)} falha(s) — tente novamente mais tarde."
        else:
            titulo_notify = "SoundVault — Sync Concluído"
            msg_notify = (f"{sucessos} baixadas com sucesso" + (f", {len(falhas)} falharam" if falhas else "") + f" — {dur_str}")
        if sucessos > 0 or falhas:
            notificar_windows(titulo_notify, msg_notify)

        if auth_falhou:
            log.warning(f"Sync com cookie expirado/inválido — {len(falhas)} falha(s) possivelmente por isso")
        if rate_limitado:
            log.warning(f"Sync limitado por rate limit (429): {download._rate_limit_hits} bloqueio(s), workers reduzidos pra {download._workers_ativos}")
        log.info(
            f"Sync — sucesso: {sucessos}, removidas: {len(removidos)}, puladas: {len(skips)}, "
            f"falhas: {len(falhas)} (rate: {contagem_tipo['rate']}, formato: {contagem_tipo['format']}, "
            f"outro: {contagem_tipo['retry']}), auth_falhou: {auth_falhou}, duração: {dur_str}"
        )
        salvar_historico({
            "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "sucesso": sucessos, "removidas": len(removidos), "puladas": len(skips),
            "falhas": len(falhas), "duracao": dur_str, "perfil": config.BASE_DIR.name,
            "auth_falhou": auth_falhou, "rate_limit_hits": download._rate_limit_hits,
        })
    finally:
        log.debug("finally sincronizar — liberando lock")
        liberar_lock()
