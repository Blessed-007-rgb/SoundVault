import json
import os
import subprocess
import threading
import time
import webbrowser
from datetime import datetime, timedelta

from . import config
from .console_log import console, RICH_OK, log
from .playlist import classificar_erro

_cookie_renovado = threading.Event()
_prompt_exibido = threading.Event()
_cookie_lock_ui = threading.Lock()

_URL_TESTE_COOKIE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


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
    if not config.COOKIES_FILE.exists():
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
            ["yt-dlp", "--cookies", str(config.COOKIES_FILE), "--skip-download",
             "--simulate", "--quiet", _URL_TESTE_COOKIE],
            capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace",
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})
        )
    except Exception as e:
        log.debug(f"[HEALTH] Não foi possível testar cookies.txt agora: {e}")
        return None  # inconclusivo — nunca bloqueia o Sync por causa disso

    if result.returncode == 0:
        valido = True
    else:
        valido = classificar_erro(result.stderr.strip()) != "auth"

    try:
        arq.write_text(json.dumps({"checado_em": datetime.now().isoformat(), "valido": valido}), encoding="utf-8")
    except Exception:
        pass
    log.debug(f"[HEALTH] cookies.txt {'válido' if valido else 'INVÁLIDO'} (teste ativo)")
    return valido


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
            from rich.panel import Panel
            console.print(Panel(
                "[bold yellow]⚠  Cookie do YouTube expirado![/]\n\n"
                "  1. O YouTube foi aberto no seu browser\n"
                "  2. Faça login se necessário\n"
                "  3. Use a extensão [bold]'Get cookies.txt LOCALLY'[/] para exportar\n"
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
