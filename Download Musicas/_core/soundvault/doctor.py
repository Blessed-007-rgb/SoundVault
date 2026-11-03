"""Diagnóstico do ambiente: `python -m soundvault --doctor` (ou opção D do menu).

Confere tudo que costuma dar problema em silêncio — ferramentas externas,
pacotes opcionais, espaço em disco, cookies e integridade do cache — e diz como
resolver cada item. Só lê; não altera nada (exceto o cookie_health.json, que o
teste de cookie atualiza como em qualquer Sync).
"""
import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass

from . import config
from .console_log import console, RICH_OK, Table, Panel, box
from .procutil import sem_janela

OK, AVISO, ERRO, INFO = "ok", "aviso", "erro", "info"
_ICONE = {OK: "✓", AVISO: "⚠", ERRO: "✗", INFO: "·"}
_COR = {OK: "green", AVISO: "yellow", ERRO: "red", INFO: "dim"}

GB = 1024 ** 3
DISCO_MIN_ERRO_GB = 1.0
DISCO_MIN_AVISO_GB = 5.0


@dataclass
class Check:
    nome: str
    status: str
    detalhe: str
    dica: str = ""


def _primeira_linha(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=15, **sem_janela())
        linhas = (r.stdout or r.stderr).strip().splitlines()
        return linhas[0].strip() if linhas else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _tem_modulo(nome: str) -> bool:
    try:
        return importlib.util.find_spec(nome) is not None
    except (ImportError, ValueError):
        return False


def checar_python() -> Check:
    v = sys.version_info
    texto = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 10):
        return Check("Python", ERRO, f"{texto} — é preciso 3.10 ou mais novo", "Atualize em python.org/downloads")
    return Check("Python", OK, texto)


def checar_ffmpeg() -> list[Check]:
    saida = []
    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            saida.append(Check(exe, ERRO, "não encontrado no PATH",
                               "Instale o FFmpeg 'essentials' (gyan.dev/ffmpeg/builds) e adicione a pasta bin ao PATH (README §1.4)"))
        else:
            versao = _primeira_linha([exe, "-version"]).replace("version ", "")
            saida.append(Check(exe, OK, versao[:60] or "ok"))
    return saida


def checar_ytdlp() -> Check:
    if not shutil.which("yt-dlp"):
        return Check("yt-dlp", ERRO, "executável não encontrado no PATH", "pip install -U \"yt-dlp[default]\"")
    versao = _primeira_linha(["yt-dlp", "--version"]) or "?"
    if not _tem_modulo("yt_dlp"):
        return Check("yt-dlp", AVISO, f"{versao} (módulo Python ausente: a busca automática de URLs não funciona)",
                     "pip install -U \"yt-dlp[default]\"")
    return Check("yt-dlp", OK, versao)


def checar_js() -> list[Check]:
    achados = [r for r in ("deno", "node", "bun") if shutil.which(r)]
    saida = []
    if not achados:
        saida.append(Check("Runtime JavaScript", ERRO, "nenhum encontrado (deno, node ou bun)",
                           "Instale o Node.js (nodejs.org): sem ele o yt-dlp perde formatos e falha com 'format not available'"))
    elif "deno" in achados:
        saida.append(Check("Runtime JavaScript", OK, "deno (habilitado por padrão no yt-dlp)"))
    else:
        saida.append(Check("Runtime JavaScript", OK, f"{', '.join(achados)} — habilitado automaticamente pelo SoundVault (--js-runtimes)"))
    if achados and not _tem_modulo("yt_dlp_ejs"):
        saida.append(Check("yt-dlp-ejs", AVISO, "pacote ausente (scripts que resolvem os desafios de JS do YouTube)",
                           "pip install -U \"yt-dlp[default]\""))
    elif achados:
        saida.append(Check("yt-dlp-ejs", OK, "instalado"))
    return saida


def checar_pacotes() -> list[Check]:
    itens = [
        ("rich", "interface visual do menu", "sem ele o menu cai para o modo texto simples"),
        ("mutagen", "tags ID3 e capas dos MP3", "sem ele as músicas ficam sem título, artista e capa"),
        ("psutil", "trava contra duas execuções ao mesmo tempo", "sem ele o lock não confere se o outro processo ainda existe"),
    ]
    saida = []
    for modulo, para_que, sem_ele in itens:
        if _tem_modulo(modulo):
            saida.append(Check(f"Pacote {modulo}", OK, para_que))
        else:
            saida.append(Check(f"Pacote {modulo}", AVISO, f"ausente — {sem_ele}", f"pip install {modulo}"))
    return saida


def _tamanho_pool() -> int:
    total = 0
    for f in config.DOWNLOAD_DIR.glob("*.mp3"):
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total


def checar_disco() -> Check:
    try:
        livre = shutil.disk_usage(config.DOWNLOAD_DIR).free
    except OSError as e:
        return Check("Espaço em disco", AVISO, f"não foi possível medir ({e})")
    pool = _tamanho_pool()
    detalhe = f"{livre / GB:.1f} GB livres · pool atual: {pool / GB:.1f} GB (cada playlist guarda uma cópia renderizada a mais)"
    if livre < DISCO_MIN_ERRO_GB * GB:
        return Check("Espaço em disco", ERRO, detalhe, "Libere espaço: o download e o render vão falhar")
    if livre < DISCO_MIN_AVISO_GB * GB:
        return Check("Espaço em disco", AVISO, detalhe, "Pouco espaço: um Sync grande pode encher o disco")
    return Check("Espaço em disco", OK, detalhe)


def checar_escrita() -> Check:
    teste = config.BASE_DIR / ".doctor_escrita.tmp"
    try:
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
        return Check("Pasta do perfil", OK, f"{config.BASE_DIR.name} — escrita ok")
    except OSError as e:
        return Check("Pasta do perfil", ERRO, f"sem permissão de escrita em {config.BASE_DIR}: {e}",
                     "Verifique permissões/antivírus/OneDrive nessa pasta")


def checar_cookies(rede: bool) -> Check:
    import time
    from . import cookies
    nav = config.navegador_cookies()
    if nav is None and config.COOKIES_FILE.exists() and not config.cookies_txt_valido():
        return Check("Cookies do YouTube", ERRO,
                     "cookies.txt NÃO é um arquivo de cookies (sem o cabeçalho '# Netscape HTTP Cookie File' e sem linhas de cookie) — "
                     "provavelmente foi colado o texto de uma página. Os downloads rodam sem cookies até corrigir",
                     "Exporte com a extensão 'Get cookies.txt LOCALLY' (botão Export/Exportar) e salve como cookies.txt — "
                     "não copie o texto da página")
    if nav is None and not config.COOKIES_FILE.exists():
        return Check("Cookies do YouTube", AVISO, "sem cookies — vídeos que exigem login vão falhar",
                     "Exporte cookies.txt de uma janela anônima (README §5) ou deixe o yt-dlp ler direto do navegador: "
                     "python -m soundvault --cookies-browser firefox")
    if nav:
        idade = f"cookies lidos direto do {nav}"
    else:
        dias = (time.time() - config.COOKIES_FILE.stat().st_mtime) / 86400
        idade = f"cookies.txt de {dias:.0f} dia(s) atrás"
    if not rede:
        return Check("Cookies do YouTube", INFO, f"{idade} (validade não testada: modo offline)")
    valido = cookies.verificar_cookie_valido(forcar=True)
    if valido is True:
        return Check("Cookies do YouTube", OK, f"{idade} — autenticação ok")
    if valido is False:
        return Check("Cookies do YouTube", ERRO, f"{idade} — o YouTube recusou",
                     f"Entre no YouTube no {nav} e tente de novo" if nav else
                     "Exporte um novo cookies.txt de uma janela anônima e feche a janela em seguida")
    return Check("Cookies do YouTube", AVISO, f"{idade} — teste inconclusivo (rede ou yt-dlp indisponível)")


def checar_cache() -> list[Check]:
    from . import playlists
    from .cache_maint import pendentes_de_revisao, validar_cache
    from .storage import carregar_cache
    cache = carregar_cache()
    saida = []
    r = validar_cache(cache)
    if r["problemas"]:
        saida.append(Check("playlist_cache.json", AVISO,
                           f"{r['problemas']} problema(s) em {r['total']} entradas (sem URL: {len(r['sem_url'])}, URL inválida: {len(r['url_invalida'])})",
                           "Rode o Sync (re-busca sozinho) ou use a opção 7 para ver os detalhes"))
    else:
        saida.append(Check("playlist_cache.json", OK, f"{r['total']} entradas, sem problemas"))
    fila = pendentes_de_revisao(cache)
    if fila:
        saida.append(Check("Revisão de URLs", AVISO, f"{len(fila)} URL(s) achada(s) automaticamente com baixa confiança",
                           "Use a opção V do menu para confirmar ou trocar"))
    nomes = playlists.listar_playlists()
    saida.append(Check("Playlists", INFO, f"{len(nomes)} no perfil: {', '.join(nomes) or '—'}"))
    return saida


def checar_lock() -> Check | None:
    if not config.LOCK_FILE.exists():
        return None
    try:
        pid = int(config.LOCK_FILE.read_text().strip().split(":")[0])
    except (OSError, ValueError, IndexError):
        pid = None
    return Check("Trava de execução (.lock)", AVISO, f"arquivo presente (PID {pid or '?'})",
                 "Se nenhum SoundVault está aberto, o programa limpa sozinho no próximo Sync; ou apague o .lock")


def coletar(rede: bool = True) -> list[Check]:
    checks: list[Check] = [checar_python(), *checar_ffmpeg(), checar_ytdlp(), *checar_js(), *checar_pacotes(),
                           checar_disco(), checar_escrita(), checar_cookies(rede), *checar_cache()]
    lock = checar_lock()
    if lock:
        checks.append(lock)
    return checks


def diagnosticar(rede: bool = True) -> int:
    """Imprime o relatório e devolve 1 se algum item for erro, 0 caso contrário."""
    checks = coletar(rede)
    if RICH_OK:
        t = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
        t.add_column(width=2)
        t.add_column(style="bold", width=26)
        t.add_column()
        for c in checks:
            t.add_row(f"[{_COR[c.status]}]{_ICONE[c.status]}[/]", c.nome, c.detalhe)
        console.print(Panel(t, title=f"[bold]DIAGNÓSTICO — perfil {config.BASE_DIR.name}[/]", border_style="blue"))
    else:
        for c in checks:
            print(f" {_ICONE[c.status]} {c.nome}: {c.detalhe}")

    problemas = [c for c in checks if c.status in (ERRO, AVISO) and c.dica]
    if problemas:
        print()
        print("Como resolver:")
        for c in problemas:
            print(f"  {_ICONE[c.status]} {c.nome}: {c.dica}")
    erros = sum(c.status == ERRO for c in checks)
    avisos = sum(c.status == AVISO for c in checks)
    print()
    print(f"Resultado: {erros} erro(s), {avisos} aviso(s).")
    return 1 if erros else 0
