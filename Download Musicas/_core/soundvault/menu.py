import os

from . import config, playlists
from .console_log import console, RICH_OK, cprint, log
from .storage import carregar_state, salvar_state, carregar_historico
from .lock import LockError
from .sync import sincronizar
from .dedupe import limpar_duplicatas_playlist, limpar_duplicatas, clean
from .audit import auditoria
from .cache_maint import exibir_validacao_cache
from .rebuild import rebuild, fix_tags, reaplicar_audio

if RICH_OK:
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.console import Group
    from rich.text import Text
    from rich import box


def resetar_skips_copyright():
    """
    Lista músicas puladas por copyright/indisponível e permite resetá-las
    para que sejam retentadas no próximo Sync.
    """
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    state = carregar_state()
    puladas = [(vid, info) for vid, info in state.items() if isinstance(info, dict) and info.get("skipped")]

    if not puladas:
        cprint("[green]✓ Nenhuma música pulada no momento.[/]" if RICH_OK else "Nenhuma musica pulada.")
        return

    if RICH_OK:
        t = Table(box=box.ROUNDED, show_header=True, header_style="bold dim", padding=(0, 2))
        t.add_column("#", style="dim", width=4)
        t.add_column("Música", style="white", width=52)
        t.add_column("Motivo", style="yellow dim", width=36)
        for i, (vid, info) in enumerate(puladas, 1):
            motivo = info.get("skip_reason", "desconhecido")
            t.add_row(str(i), info.get("name", vid), (motivo[:55] + "...") if len(motivo) > 55 else motivo)
        console.print(Panel(t, title=f"[bold yellow]MÚSICAS PULADAS ({len(puladas)})[/]", border_style="yellow"))
        console.print("[dim]  Números por vírgula (ex: 1,3,5) · [bold]T[/] para todas · [bold]0[/] para cancelar[/]")
    else:
        print(f"MUSICAS PULADAS ({len(puladas)}):")

    try:
        escolha = input("  > ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        return

    if escolha in ("0", ""):
        return
    if escolha == "T":
        selecionados = list(range(len(puladas)))
    else:
        try:
            selecionados = [int(x.strip()) - 1 for x in escolha.split(",") if x.strip().isdigit()]
            selecionados = [i for i in selecionados if 0 <= i < len(puladas)]
        except ValueError:
            cprint("[red]Entrada inválida.[/]")
            return

    if not selecionados:
        cprint("[yellow]Nenhuma música selecionada.[/]")
        return

    resetadas = []
    for i in selecionados:
        vid, info = puladas[i]
        nome = info.get("name", vid)
        del state[vid]
        resetadas.append(nome)
        log.info(f"[RESET] Skip removido: {nome}")

    salvar_state(state)
    cprint(f"[green]✓ {len(resetadas)} música(s) liberada(s) para retry[/]" if RICH_OK else f"{len(resetadas)} resetada(s).")


def escolher_playlist(permitir_todas: bool = True) -> str | None:
    """
    Mostra as playlists do perfil e retorna o nome escolhido.
    Retorna None se o usuário escolheu 'Todas'.
    Retorna a sentinela "__cancelar__" se não há playlists, ou se a
    escolha foi inválida/cancelada — o chamador deve checar por ela
    antes de prosseguir.
    """
    nomes = playlists.listar_playlists()
    if not nomes:
        cprint("[yellow]Nenhuma playlist encontrada. Use 'Gerenciar Playlists' (G) pra criar uma.[/]")
        return "__cancelar__"
    if len(nomes) == 1 and not permitir_todas:
        return nomes[0]

    opcoes = (["Todas"] if permitir_todas else []) + nomes
    if RICH_OK:
        t = Table(box=box.SIMPLE, show_header=False)
        t.add_column(style="bold cyan", width=4)
        t.add_column()
        for i, o in enumerate(opcoes, 1):
            t.add_row(str(i), o)
        console.print(t)
        escolha = Prompt.ask("  Escolha a playlist", choices=[str(i) for i in range(1, len(opcoes) + 1)], default="1")
    else:
        for i, o in enumerate(opcoes, 1):
            print(f"  {i} - {o}")
        escolha = input("Escolha a playlist: ").strip()

    try:
        idx = int(escolha) - 1
    except ValueError:
        return "__cancelar__"
    if not (0 <= idx < len(opcoes)):
        return "__cancelar__"
    escolhida = opcoes[idx]
    return None if escolhida == "Todas" else escolhida


def gerenciar_playlists():
    while True:
        os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
        nomes = playlists.listar_playlists()
        if RICH_OK:
            t = Table(box=box.ROUNDED, show_header=True, header_style="bold dim", padding=(0, 2))
            t.add_column("Playlist", style="white")
            t.add_column("Músicas", style="cyan", justify="right")
            for n in nomes:
                t.add_row(n, str(len(playlists.carregar_playlist(n))))
            console.print(Panel(
                t if nomes else "[dim]Nenhuma playlist ainda.[/]",
                title="[bold]PLAYLISTS DO PERFIL[/]", border_style="blue"
            ))
            escolha = Prompt.ask("\n  [C]riar · [R]emover · [V]oltar", choices=["C", "c", "R", "r", "V", "v"], default="V").upper()
        else:
            print("Playlists:", nomes)
            escolha = input("C=criar, R=remover, V=voltar: ").strip().upper()

        if escolha == "C":
            nome = input("  Nome da nova playlist: ").strip()
            if nome in nomes:
                cprint(f"[yellow]Já existe uma playlist chamada '{nome}'.[/]")
            else:
                try:
                    playlists.criar_playlist(nome)
                    cprint(f"[green]✓ Playlist '{nome}' criada.[/]")
                except ValueError as e:
                    cprint(f"[red]{e}[/]")
            input("\n  Pressione Enter para continuar...")
        elif escolha == "R":
            if not nomes:
                cprint("[yellow]Nenhuma playlist para remover.[/]")
                input("\n  Pressione Enter para continuar...")
                continue
            nome = input(f"  Nome da playlist a remover ({', '.join(nomes)}): ").strip()
            if nome not in nomes:
                cprint("[red]Playlist não encontrada.[/]")
            else:
                confirmacao = input(f"  Tem certeza? Isso apaga playlists/{nome}/ (digite o nome de novo pra confirmar): ").strip()
                if confirmacao == nome:
                    playlists.remover_playlist(nome)
                    cprint(f"[green]✓ Playlist '{nome}' removida.[/]")
                else:
                    cprint("[yellow]Cancelado.[/]")
            input("\n  Pressione Enter para continuar...")
        else:
            return


def mostrar_help():
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    if RICH_OK:
        console.print(Panel(
            "[bold]SoundVault[/]\n"
            "[dim]Baixa músicas do YouTube automaticamente a partir do playlist.txt,\n"
            "salva como MP3 com metadados e mantém tudo sincronizado.[/]",
            title="[bold blue]  SOUNDVAULT — AJUDA  [/]", border_style="blue"
        ))
        t2 = Table(box=box.ROUNDED, show_header=True, header_style="bold dim", padding=(0, 2))
        t2.add_column("Opção", style="bold cyan", width=22)
        t2.add_column("Quando usar", width=58)
        t2.add_row("1 · Sincronizar", "Use sempre que atualizar o playlist.txt.\nBaixa o que é novo e remove do disco o que saiu da lista.")
        t2.add_row("2 · Retry de Falhas", "Use quando o Sync teve erros de rede ou timeout.\nTenta de novo apenas as músicas que falharam.")
        t2.add_row("3 · Limpar Playlist.txt", "Use se a Auditoria mostrar 'Duplicatas no playlist.txt'.\nRemove músicas repetidas, salva backup antes de alterar.")
        t2.add_row("4 · Remover Duplicatas MP3", "Use se tiver dois arquivos com o mesmo conteúdo no disco.\nCompara por conteúdo real (MD5), não só pelo nome.")
        t2.add_row("5 · Verificar Biblioteca", "Use para checar se tudo está em ordem.\nCompara playlist.txt × registros × arquivos no disco.")
        t2.add_row("6 · Limpar Registros", "Use quando deletar músicas manualmente do disco.\nRemove os registros delas — o próximo Sync vai rebaixar.")
        t2.add_row("7 · Verificar Cache", "Use se o Sync mostrar músicas sem URL.\nValida o playlist_cache.json e aponta entradas problemáticas.")
        t2.add_row("8 · Reaplicar Áudio", "Use após mudar configurações de volume ou EQ no código.\nReprocessa todos os .mp3 existentes com as novas configurações.")
        t2.add_row("9 · Corrigir Metadados", "Use se músicas aparecerem sem nome/artista no player.\nRegrava título, artista e capa em todos os .mp3.")
        t2.add_row("P · Resetar Puladas", "Use quando quiser retentar músicas puladas por copyright.\nLista as puladas, escolha quais liberar — depois rode Sync.")
        t2.add_row("R · Registrar MP3s do Disco", "Use ao migrar de máquina ou copiar músicas manualmente.\nImporta os .mp3 existentes para o sistema não baixar de novo.")
        t2.add_row("H · Help", "Esta tela.")
        t2.add_row("0 · Sair", "Fecha o programa.")
        console.print(Panel(t2, title="[bold]O QUE CADA OPÇÃO FAZ[/]", border_style="dim"))

        t3 = Table(box=box.ROUNDED, show_header=True, header_style="bold dim", padding=(0, 2))
        t3.add_column("Comando", style="cyan", width=40)
        t3.add_column("Equivale a", style="dim", width=26)
        t3.add_row("python -m soundvault", "Abre o menu")
        t3.add_row("python -m soundvault --sync", "Opção 1 — Sincronizar")
        t3.add_row("python -m soundvault --retry", "Opção 2 — Retry")
        t3.add_row("python -m soundvault --audit", "Opção 5 — Verificar Biblioteca")
        t3.add_row("python -m soundvault --clean", "Opção 6 — Limpar Registros")
        t3.add_row("python -m soundvault --rebuild", "Opção R — Registrar MP3s")
        t3.add_row("python -m soundvault --profile Tiago", "Usa o perfil do Tiago")
        console.print(Panel(t3, title="[bold]COMANDOS (uso avançado)[/]", border_style="dim"))
    else:
        print("\n=== HELP — SOUNDVAULT ===\n")
        print("  1 - Sincronizar")
        print("  H - Help")
        print("PERFIS:    --profile NomeDaPasta")


MENU = [
    ("1", "Sincronizar",            "Baixa músicas pendentes do playlist.txt"),
    ("2", "Retry de Falhas",        "Tenta de novo as que falharam no último sync"),
    ("3", "Limpar Playlist.txt",    "Remove duplicatas do playlist.txt"),
    ("4", "Remover Duplicatas MP3", "Detecta e remove MP3s duplicados por MD5"),
    ("5", "Verificar Biblioteca",   "Compara playlist vs registros vs disco"),
    ("6", "Limpar Registros",       "Remove registros de músicas que não existem mais no disco"),
    ("7", "Verificar Cache",        "Verifica integridade do playlist_cache.json"),
    ("8", "Reaplicar Áudio",        "Reprocessa EQ e volume em todos os .mp3 existentes"),
    ("9", "Corrigir Metadados",     "Grava título, artista e capa nos .mp3 existentes"),
    ("P", "Resetar Puladas",        "Lista músicas puladas por copyright e libera para retry"),
    ("R", "Registrar MP3s do Disco","Importa .mp3 existentes que o sistema não conhece"),
    ("G", "Gerenciar Playlists",    "Criar, listar e remover playlists do perfil"),
    ("H", "Help",                   "Documentação detalhada de todas as opções"),
    ("0", "Sair",                   ""),
]

# Agrupamento puramente visual do MENU acima — cada item aparece em uma
# única seção, na mesma ordem em que está definido em MENU.
GRUPOS_MENU = [
    ("SINCRONIZAÇÃO", ["1", "2"]),
    ("MANUTENÇÃO", ["3", "4", "5", "6", "7", "8", "9", "P", "R"]),
    ("SISTEMA", ["G", "H", "0"]),
]


def exibir_menu():
    os.system("cls")  # comando literal fixo, sem entrada do usuário — não é injeção
    if RICH_OK:
        hist = carregar_historico()
        if hist:
            ultimo = hist[-1]
            cor_status = "green" if ultimo["falhas"] == 0 else "red"
            status_icon = "✓" if ultimo["falhas"] == 0 else "✗"
            sub = (
                f"[dim]Último sync: {ultimo['data']} · {ultimo['sucesso']} baixadas · "
                f"[{cor_status}]{status_icon} {ultimo['falhas']} falhas[/{cor_status}] · {ultimo['duracao']}[/]"
            )
        else:
            ultimo = None
            sub = "[dim]Nenhum sync realizado ainda[/]"

        # Aviso persiste até o próximo Sync bem-sucedido — sem isso, um
        # cookie expirado ou rate limit só aparecia no resultado do Sync
        # que já rolou e passava despercebido se a pessoa não estava
        # olhando a tela naquele momento.
        if ultimo and ultimo.get("auth_falhou"):
            console.print(Panel(
                "[bold red]⚠ O último Sync falhou por cookie do YouTube expirado ou inválido![/]\n"
                "[dim]Exporte um novo cookies.txt e rode Sync de novo.[/]",
                border_style="red",
            ))
        elif ultimo and ultimo.get("rate_limit_hits", 0) > 0 and ultimo.get("falhas", 0) > 0:
            console.print(Panel(
                f"[bold yellow]⚠ O último Sync foi limitado pelo YouTube (rate limit / HTTP 429, {ultimo['rate_limit_hits']}x).[/]\n"
                "[dim]Normal em syncs grandes — espere um pouco e use 'Retentar Falhas'.[/]",
                border_style="yellow",
            ))

        por_num = {num: (nome, desc) for num, nome, desc in MENU}
        secoes = []
        for i, (titulo, nums) in enumerate(GRUPOS_MENU):
            if i > 0:
                secoes.append(Text(""))
            secoes.append(Text(f"  {titulo}", style="bold dim"))
            t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2), expand=False, border_style="dim")
            t.add_column(style="bold cyan", width=3)
            t.add_column(style="bold white", width=26)
            t.add_column(style="dim", width=44)
            for num in nums:
                nome, desc = por_num[num]
                t.add_row(num, nome, desc)
            secoes.append(t)
        console.print(Panel(
            Group(*secoes),
            title=f"[bold blue]  SOUNDVAULT  [/]  [dim]perfil: {config.BASE_DIR.name}[/]",
            subtitle=f"[dim]{config.DOWNLOAD_DIR}[/]  ·  {sub.strip()}",
            padding=(1, 2),
        ))
        # Bug 23: aceita escolha em qualquer caixa — choices inclui
        # maiúsculas e minúsculas, e a resposta é normalizada para
        # maiúsculo antes de retornar.
        todas_choices = [o[0] for o in MENU] + [o[0].lower() for o in MENU]
        resposta = Prompt.ask("\n  [bold cyan]Escolha[/]", choices=todas_choices, default="1")
        return resposta.upper()
    else:
        print("\n" + "=" * 44)
        print("   SOUNDVAULT")
        print("=" * 44)
        for num, nome, desc in MENU:
            print(f"  {num} - {nome}")
        return input("\nEscolha: ").strip().upper()


def menu():
    ok, faltando = config.verificar_dependencias()
    if faltando and RICH_OK:
        linhas = "".join(f"  [red]✗[/] [bold]{n}[/] não encontrado\n     → {i}\n" for n, c, i in faltando)
        console.print(Panel(linhas.rstrip(), title="[bold red]DEPENDÊNCIAS FALTANDO[/]", border_style="red"))

    while True:
        try:
            opcao = exibir_menu()
        except KeyboardInterrupt:
            # Ctrl+C enquanto o menu espera a escolha (Prompt.ask) não é
            # capturado pelo try abaixo, que só envolve a execução da opção
            # — sem isso, o programa encerrava com traceback cru em vez de
            # sair como o "0 · Sair" normal.
            cprint("\n[yellow]⚠ Encerrado pelo usuário (Ctrl+C).[/]" if RICH_OK else "\nEncerrado.")
            break
        try:
            if opcao == "1":
                alvo = escolher_playlist()
                if alvo != "__cancelar__":
                    sincronizar(alvo)
            elif opcao == "2":
                alvo = escolher_playlist()
                if alvo != "__cancelar__":
                    sincronizar(alvo, apenas_falhas=True)
            elif opcao == "3":
                alvo = escolher_playlist(permitir_todas=False)
                if alvo != "__cancelar__":
                    limpar_duplicatas_playlist(alvo)
            elif opcao == "4": limpar_duplicatas()
            elif opcao == "5":
                alvo = escolher_playlist()
                if alvo != "__cancelar__":
                    auditoria(alvo)
            elif opcao == "6": clean()
            elif opcao == "7": exibir_validacao_cache()
            elif opcao == "8": reaplicar_audio()
            elif opcao == "9": fix_tags()
            elif opcao == "P": resetar_skips_copyright()
            elif opcao == "R": rebuild()
            elif opcao == "G": gerenciar_playlists()
            elif opcao == "H": mostrar_help()
            elif opcao == "0": break
        except LockError:
            pass  # mensagem já exibida em adquirir_lock
        except KeyboardInterrupt:
            # KeyboardInterrupt (Ctrl+C) é BaseException, não Exception — sem
            # este except, cancelar uma operação longa (Sync, Rebuild, etc.)
            # derrubava o programa inteiro em vez de voltar ao menu.
            cprint("\n[yellow]⚠ Operação interrompida pelo usuário.[/]" if RICH_OK else "\nOperacao interrompida.")
            log.warning(f"Operação '{opcao}' interrompida via Ctrl+C")
        except Exception as e:
            cprint(f"[bold red]Erro inesperado: {e}[/]" if RICH_OK else f"Erro: {e}")
            log.exception("Erro inesperado no menu")

        # Bug 24: removido o `if opcao == "0": break` duplicado que existia
        # aqui — é código morto: se opcao == "0", o `elif opcao == "0":
        # break` dentro do try acima já encerrou o loop antes de chegar
        # neste ponto.
        log.debug(f"Menu aguardando Enter após opção {opcao}")
        input("\n  Pressione Enter para voltar ao menu...")

    cprint("[bold green]✓ Sessão encerrada com sucesso.[/]" if RICH_OK else "\n  Sessão encerrada.")
