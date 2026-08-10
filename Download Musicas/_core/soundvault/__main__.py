import sys
import traceback as _tb_mod
from datetime import datetime

from . import config
from .console_log import console, RICH_OK, init_logging, log, cprint


def main():
    _CRASH_LOG = config.LOGS_DIR / "crash.log"

    try:
        if not RICH_OK:
            print("[AVISO] 'rich' não instalado — interface simplificada.")
            print("        Instale com: pip install rich\n")

        args = sys.argv[1:]

        if "--profile" in args:
            idx = args.index("--profile")
            # Bug 11: valida que existe um próximo argumento E que ele não
            # é outra flag (começa com "--"). Sem isso, "--profile --sync"
            # criava uma pasta de perfil chamada "--sync" e caía no menu
            # interativo silenciosamente em vez de rodar o Sync.
            valor_valido = (
                idx + 1 < len(args)
                and not args[idx + 1].startswith("--")
            )
            if not valor_valido:
                print("Uso: --profile NomeDoPerfil")
                print("(O nome do perfil não pode começar com '--' nem estar ausente.)")
                sys.exit(1)
            perfil = args[idx + 1]
            config.ativar_perfil(perfil)
            _CRASH_LOG = config.LOGS_DIR / "crash.log"
            args = [a for i, a in enumerate(args) if i != idx and i != idx + 1]
            if RICH_OK:
                console.print(f"[dim]  Perfil: [cyan]{perfil}[/] ({config.BASE_DIR})[/]")

        init_logging()
        log.info(f"=== SESSÃO INICIADA — perfil: {config.BASE_DIR.name} ===")

        from . import playlists
        if not playlists.listar_playlists() and (config.BASE_DIR / "playlist.txt").exists():
            if RICH_OK:
                from rich.panel import Panel
                console.print(Panel(
                    "[bold]Migrando pro novo formato de múltiplas playlists...[/]\n"
                    "[dim]Sua playlist.txt atual vai virar a primeira playlist.[/]",
                    border_style="blue"
                ))
            else:
                print("Migrando pro novo formato de multiplas playlists...")
            nome_legado = input("  Nome para essa playlist (Enter usa 'Main'): ").strip() or "Main"
            try:
                if playlists.migrar_playlist_legada(nome_legado):
                    cprint(f"[green]✓ Migrado para playlists/{nome_legado}/[/]" if RICH_OK else f"Migrado para playlists/{nome_legado}/")
                    log.info(f"Migração automática concluída: playlists/{nome_legado}/")
            except ValueError as e:
                cprint(f"[red]Nome inválido ({e}) — migração adiada, tente de novo na próxima execução.[/]" if RICH_OK else f"Nome invalido: {e}")

        nome_playlist_cli = None
        if "--playlist" in args:
            idx2 = args.index("--playlist")
            valor_valido2 = idx2 + 1 < len(args) and not args[idx2 + 1].startswith("--")
            if not valor_valido2:
                print("Uso: --playlist NomeDaPlaylist")
                sys.exit(1)
            nome_playlist_cli = args[idx2 + 1]
            args = [a for i, a in enumerate(args) if i != idx2 and i != idx2 + 1]

        if not args:
            from .menu import menu
            menu()
        else:
            from .sync import sincronizar
            from .audit import auditoria
            from .rebuild import rebuild, fix_tags
            from .dedupe import clean, limpar_duplicatas, limpar_duplicatas_playlist
            from .menu import resetar_skips_copyright, mostrar_help
            from .cache_maint import exibir_validacao_cache

            try:
                if   "--sync"          in args: sincronizar(nome_playlist_cli)
                elif "--retry"         in args: sincronizar(nome_playlist_cli, apenas_falhas=True)
                elif "--audit"         in args: auditoria(nome_playlist_cli)
                elif "--rebuild"       in args: rebuild()
                elif "--fix-tags"      in args: fix_tags()
                elif "--clean"         in args: clean()
                elif "--duplicatas"    in args: limpar_duplicatas()
                elif "--duplicatas-pl" in args: limpar_duplicatas_playlist()
                elif "--reset-puladas" in args: resetar_skips_copyright()
                elif "--validate"      in args: exibir_validacao_cache()
                elif "--help"          in args: mostrar_help()
                else:
                    print(f"Opção desconhecida: {args}")
                    print("Use sem argumentos para o menu interativo, ou --help.")
                    sys.exit(1)
            except KeyboardInterrupt:
                # Ver nota equivalente em menu.py: Ctrl+C é BaseException, não
                # Exception — sem este except, cancelar uma operação em modo
                # CLI derrubava com traceback cru e o .bat mostrava "ERRO FATAL".
                print("\n  Operação interrompida pelo usuário.")
                log.warning(f"Operação CLI {args} interrompida via Ctrl+C")
            input("\n  Pressione Enter para fechar...")

    except Exception:
        _tb = _tb_mod.format_exc()
        try:
            _CRASH_LOG.write_text(f"=== CRASH {datetime.now()} ===\n{_tb}", encoding="utf-8")
        except Exception as _ce:
            print(f"[AVISO] Não foi possível gravar crash.log: {_ce}")
        print("\n" + "=" * 60)
        print("ERRO FATAL — detalhes em crash.log:")
        print(_tb)
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
