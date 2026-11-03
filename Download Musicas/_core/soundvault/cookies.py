import json
import subprocess
import threading
import time
import webbrowser
from datetime import datetime, timedelta

from . import config
from .console_log import console, RICH_OK, log, Panel, cprint
from .playlist import classificar_erro
from .procutil import sem_janela, ytdlp_js_args

_cookie_renovado = threading.Event()
_prompt_exibido = threading.Event()
_cookie_lock_ui = threading.Lock()

_URL_TESTE_COOKIE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Mensagens do yt-dlp quando não consegue ler o banco de cookies de um navegador.
_ERROS_LEITURA_NAVEGADOR = (
    "cookie database", "cookies database", "failed to decrypt", "could not find", "dpapi",
    "permission denied", "cookies from browser", "unsupported browser",
)


def _arquivo_health() -> "config.Path":
    return config.BASE_DIR / "cookie_health.json"


def verificar_cookie_valido(forcar: bool = False) -> bool | None:
    """
    Testa rapidamente (yt-dlp --simulate, sem baixar nada) se cookies.txt
    ainda autentica no YouTube, ANTES de começar um Sync grande — sem isso,
    um cookie expirado só era descoberto no meio dos downloads, depois de
    já ter gasto tempo/tentativas em várias músicas da fila.

    Retorna True (válido), False (expirado/inválido) ou None (não deu pra
    concluir — sem cookies.txt, checagem recente ainda dentro do intervalo
    de cache, yt-dlp indisponível, ou erro de rede/timeout no teste).
    """
    if not config.cookies_disponiveis():
        return None

    arq = _arquivo_health()
    if not forcar and arq.exists():
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
            checado_em = datetime.fromisoformat(dados["checado_em"])
            if datetime.now() - checado_em < timedelta(hours=config.COOKIE_HEALTH_CHECK_INTERVAL_H):
                return dados["valido"]
        except Exception:
            pass  # health file corrompido/ausente/formato antigo — checa de novo

    try:
        result = subprocess.run(
            ["yt-dlp", *config.cookies_args(), "--skip-download",
             "--simulate", "--quiet", *ytdlp_js_args(), _URL_TESTE_COOKIE],
            capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            **sem_janela()
        )
    except Exception as e:
        log.debug(f"[HEALTH] Não foi possível testar cookies.txt agora: {e}")
        return None  # inconclusivo — nunca bloqueia o Sync por causa disso

    if result.returncode == 0:
        valido = True
    else:
        erro = result.stderr.strip()
        if config.navegador_cookies() and any(m in erro.lower() for m in _ERROS_LEITURA_NAVEGADOR):
            # O yt-dlp nem conseguiu ler os cookies do navegador (navegador aberto
            # travando o banco, ou Chrome/Edge com criptografia que ele não abre).
            # Não dá pra dizer se o login vale — e NÃO pode contar como "válido".
            log.warning(f"[HEALTH] Não foi possível ler os cookies do navegador: {erro.splitlines()[-1][:160] if erro else ''}")
            return None
        valido = classificar_erro(erro) != "auth"

    try:
        arq.write_text(json.dumps({"checado_em": datetime.now().isoformat(), "valido": valido}), encoding="utf-8")
    except Exception:
        pass
    log.debug(f"[HEALTH] cookies.txt {'válido' if valido else 'INVÁLIDO'} (teste ativo)")
    return valido


def cookies_txt_corrompido() -> bool:
    """True se existe um cookies.txt (e nenhum navegador configurado) que NÃO está no
    formato de cookies — ex.: o texto de uma página colado no lugar do arquivo exportado."""
    return config.navegador_cookies() is None and config.COOKIES_FILE.exists() and not config.cookies_txt_valido()


def reset_sessao():
    """Chamada no início de cada Sync — permite um novo prompt de renovação
    por execução, mesmo que a anterior tenha dado timeout sem renovar."""
    _cookie_renovado.clear()
    _prompt_exibido.clear()


def cookie_renovado_nesta_sessao() -> bool:
    return _cookie_renovado.is_set()


def solicitar_renovacao_cookies():
    """
    Chamada quando o cookie expira durante o sync.
    Abre o YouTube no browser e pausa até o usuário renovar.

    Bugs 13/29: só exibe o prompt/abre o browser UMA VEZ por sessão de
    Sync (via _prompt_exibido), independente de quantas músicas na fila
    detectarem erro de auth em paralelo ou de o timeout ter batido sem
    renovação — antes, cada música na fila reabria o painel/browser
    independentemente.
    """
    if _cookie_renovado.is_set() or _prompt_exibido.is_set():
        return
    with _cookie_lock_ui:
        if _cookie_renovado.is_set() or _prompt_exibido.is_set():
            return
        _prompt_exibido.set()
        if RICH_OK:
            console.print(Panel(
                "[bold yellow]⚠  Cookie do YouTube expirado![/]\n\n"
                "  [dim]Dica: dá pra evitar o arquivo — rode  python -m soundvault --cookies-browser firefox[/]\n\n"
                "  1. Abra uma [bold]janela anônima/privada[/] e entre em youtube.com\n"
                "     [dim](o YouTube troca os cookies de abas normais em minutos —\n"
                "      por isso cookies exportados dali 'expiram' logo)[/]\n"
                "  2. Nessa mesma aba, vá para youtube.com/robots.txt [dim](é só uma página leve, para a aba\n"
                "     não recarregar — [bold]NÃO copie o texto dela[/])[/]\n"
                "  3. Clique na extensão [bold]'Get cookies.txt LOCALLY'[/] e use [bold]Export[/]; feche a janela anônima\n"
                "     [dim](sem o ícone? chrome://extensions → Detalhes → 'Permitir no modo de navegação anônima')[/]\n"
                "  4. Salve como [cyan]cookies.txt[/] na pasta do perfil:\n"
                f"     [dim]{config.COOKIES_FILE}[/]\n\n"
                "  [dim]Músicas que já falharam por causa disso nesta execução não são\n"
                "  retentadas automaticamente — depois de renovar, use a opção\n"
                "  2 (Retry de Falhas) no menu.[/]",
                title="[bold red]AÇÃO NECESSÁRIA[/]", border_style="red"
            ))
        else:
            print("\n!! COOKIE EXPIRADO !!")
            print(f"Renove o cookies.txt em: {config.COOKIES_FILE}")
        try:
            webbrowser.open("https://www.youtube.com")
        except Exception:
            pass

        ts_antes = config.COOKIES_FILE.stat().st_mtime if config.COOKIES_FILE.exists() else 0
        if RICH_OK:
            console.print("[dim]  Aguardando cookies.txt ser atualizado... (máx 10 min)[/]")
        timeout = 600
        decorrido = 0
        while decorrido < timeout:
            time.sleep(5)
            decorrido += 5
            if config.COOKIES_FILE.exists():
                ts_agora = config.COOKIES_FILE.stat().st_mtime
                if ts_agora > ts_antes:
                    _cookie_renovado.set()
                    if RICH_OK:
                        console.print("[green]  ✓ cookies.txt atualizado — retomando sync.[/]")
                    log.info("[AUTH] cookies.txt renovado — retomando sync.")
                    break
        else:
            if RICH_OK:
                console.print("[yellow]  ⚠ Timeout aguardando cookies — sync continuará mas pode falhar.[/]")
            log.warning("[AUTH] Timeout aguardando renovação de cookies.")


def configurar_cookies_navegador(nome: str) -> int:
    """Define (ou, com 'nenhum', remove) o navegador de onde ler os cookies deste
    perfil e testa se funciona. Devolve 0 se ficou usável, 1 caso contrário."""
    nome = nome.strip().lower()
    arq_saude = _arquivo_health()
    if nome in ("nenhum", "none", "arquivo", "off"):
        config.definir_navegador_cookies(None)
        arq_saude.unlink(missing_ok=True)
        cprint("[green]✓ Voltando a usar o arquivo cookies.txt.[/]" if RICH_OK else "Voltando a usar o cookies.txt.")
        return 0
    try:
        config.definir_navegador_cookies(nome)
    except ValueError as e:
        cprint(f"[red]{e}[/]" if RICH_OK else str(e))
        return 1
    arq_saude.unlink(missing_ok=True)  # o resultado em cache era do cookies.txt
    cprint(f"[cyan]Navegador '{nome}' configurado. Testando a leitura dos cookies...[/]" if RICH_OK else f"Testando cookies do {nome}...")
    ok = verificar_cookie_valido(forcar=True)
    if ok is True:
        cprint(f"[green]✓ Funcionando: o YouTube aceitou os cookies do {nome}. Não precisa mais exportar cookies.txt.[/]" if RICH_OK else "Funcionando.")
        return 0
    if ok is False:
        cprint(f"[yellow]⚠ O YouTube recusou os cookies do {nome}: entre na sua conta no YouTube nesse navegador e tente de novo.[/]" if RICH_OK else "Cookies recusados.")
    else:
        cprint(f"[yellow]⚠ Não consegui ler os cookies do {nome}. Feche o navegador e tente de novo; "
               "o Chrome/Edge recentes costumam bloquear isso no Windows — prefira o Firefox. "
               "Para voltar ao arquivo: --cookies-browser nenhum[/]" if RICH_OK else "Nao consegui ler os cookies.")
    return 1
