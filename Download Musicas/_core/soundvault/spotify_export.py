"""
spotify_export.py - Exporta playlist do Spotify para playlist.txt

Como usar:
  1. Passe a URL da playlist como argumento, ou configure PLAYLIST_URL abaixo
  2. Execute: python -m soundvault.spotify_export [URL]
  3. Primeira vez: faca login no browser (inclui 2FA/codigo por email)
  4. Proximas vezes: sessao salva, entra automatico

Caminho rapido (SpotAPI): se o pacote 'spotapi' estiver instalado, a
extracao tenta primeiro via API interna do Spotify (sem abrir browser,
sem login) - so cai para o scraping via Playwright abaixo se o SpotAPI
nao estiver instalado, falhar, ou a playlist nao for acessivel sem login
(playlist privada de verdade, nao so "nao publica no perfil").

Saida:
  playlist.txt             - uma musica por linha: Artista - Titulo
  spotify_export_debug.log - log detalhado com traceback completo
  spotify_export_page.html - snapshot do DOM para analise

Requisitos:
  pip install spotapi        (opcional, caminho rapido sem browser)
  pip install playwright     (fallback, sempre funciona p/ playlists privadas)
  python -m playwright install chromium
"""

import json
import os
import sys
import time
import logging
import traceback
from datetime import datetime
from pathlib import Path

from . import config as _config
from . import playlists as _playlists_mod

try:
    from spotapi import PublicPlaylist
    SPOTAPI_OK = True
except ImportError:
    SPOTAPI_OK = False

# ── Configuracao ──────────────────────────────────────────────────────────────
# Bug (achado ao planejar multiplas playlists): antes esses caminhos
# eram relativos a __file__, o que fazia sentido quando este arquivo
# vivia dentro da pasta do perfil (Main\Spotify export\). Depois da
# migracao pro nucleo compartilhado (_core\), isso passou a apontar pra
# dentro de _core\ — compartilhado entre TODOS os perfis, vazando
# sessao/log/staging entre Main e Tiago. Agora usa config.BASE_DIR (o
# perfil ativo, resolvido via SOUNDVAULT_ROOT_DIR/--profile igual ao resto
# do programa), mantendo a pasta "Spotify export\" dentro do perfil.
PLAYLIST_URL = "SEU_LINK_AQUI"
_PASTA_EXPORT = _config.BASE_DIR / "Spotify export"
_PASTA_EXPORT.mkdir(parents=True, exist_ok=True)
SESSION_DIR  = _PASTA_EXPORT / ".spotify_session"
OUTPUT_FILE  = _PASTA_EXPORT / "_staging_playlist.txt"
SCROLL_WAIT  = 1.5
MAX_ITERACOES_SCROLL = 500  # bug 10: teto absoluto — mesmo se sem_avanco nunca disparar

# ── Log de debug ──────────────────────────────────────────────────────────────
DEBUG_FILE = _PASTA_EXPORT / "spotify_export_debug.log"
logging.basicConfig(
    filename=str(DEBUG_FILE),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
    filemode="w",
)
log = logging.getLogger("spotify_export")


def verificar_dependencias():
    try:
        import playwright  # noqa
    except ImportError:
        print("ERRO: playwright nao instalado.")
        print("Execute: pip install playwright")
        print("Depois:  python -m playwright install chromium")
        sys.exit(1)
    # Bug 21: no Windows o Playwright instala em %LOCALAPPDATA%\ms-playwright,
    # não em ~/.cache/ms-playwright (caminho de Linux/macOS) — a checagem
    # antiga sempre reportava "não instalado" no Windows e reinstalava o
    # Chromium a cada execução.
    if os.name == "nt":
        chromium_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ms-playwright"
    else:
        chromium_path = Path.home() / ".cache" / "ms-playwright"
    if not chromium_path.exists():
        print("Instalando Chromium (apenas na primeira vez)...")
        import subprocess
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])


def esta_logado(page):
    """
    Retorna True (logado), False (deslogado) ou None (estado ambíguo/incerto).

    Bug 22: o fallback antigo retornava True quando nenhum seletor batia —
    tratando "não sei" como "está logado" e pulando a espera de login. Isso
    podia derrubar o fluxo mais adiante com um erro genérico de "playlist
    não encontrada" em vez do diagnóstico real (sessão não carregou a
    tempo). Agora retorna None nesse caso, e o chamador trata None igual a
    "não logado" — aguarda o login em vez de seguir em frente às cegas.
    """
    try:
        if page.locator("button[data-testid='login-button']").count() > 0:
            return False
        if page.locator("[data-testid='user-widget-link']").count() > 0:
            return True
        if "login" in page.url or "accounts.spotify" in page.url:
            return False
        return None
    except Exception:
        log.warning(f"esta_logado excecao:\n{traceback.format_exc()}")
        return None


def aguardar_login(page):
    print("  Aguardando login completo (inclui 2FA/codigo por email)...")
    inicio = time.time()
    while time.time() - inicio < 600:
        try:
            if page.locator("[data-testid='user-widget-link']").count() > 0:
                time.sleep(2)
                return True
            elapsed = int(time.time() - inicio)
            if elapsed > 0 and elapsed % 10 == 0:
                print(f"  Aguardando... {elapsed}s", end="\r")
        except Exception:
            log.warning(f"aguardar_login excecao:\n{traceback.format_exc()}")
        time.sleep(2)
    return False


def salvar_html_debug(page, sufixo=""):
    try:
        html = page.evaluate("document.documentElement.outerHTML")
        nome = f"spotify_export_page{sufixo}.html"
        path = Path(__file__).parent / nome
        path.write_text(html, encoding="utf-8")
        log.debug(f"HTML do DOM salvo: {len(html)} chars -> {nome}")
    except Exception:
        log.error(f"salvar_html_debug ERRO:\n{traceback.format_exc()}")


def get_focused(page):
    try:
        return page.evaluate(
            "() => { const e = document.activeElement; if (!e) return 'none';"
            " return e.tagName"
            " + '[testid=' + (e.getAttribute('data-testid')||'') + ']'"
            " + '[role=' + (e.getAttribute('role')||'') + ']'"
            " + '[tabindex=' + (e.getAttribute('tabindex')||'') + ']'"
            " + '[cls=' + e.className.toString().slice(0,40) + ']'; }"
        )
    except Exception:
        return "<get_focused erro: " + traceback.format_exc().splitlines()[-1] + ">"


def detectar_container_scroll(page):
    try:
        resultado = page.evaluate(
            "() => {"
            " const todos = Array.from(document.querySelectorAll('*'));"
            " const lista = [];"
            " for (const el of todos) {"
            "  const rect = el.getBoundingClientRect();"
            "  if (el.scrollHeight > el.clientHeight + 10 && rect.height > 50) {"
            "   const s = window.getComputedStyle(el);"
            "   lista.push({"
            "    tag: el.tagName,"
            "    testid: el.getAttribute('data-testid') || '',"
            "    role: el.getAttribute('role') || '',"
            "    cls: el.className.toString().slice(0, 80),"
            "    osv: el.getAttribute('data-overlayscrollbars-viewport') || '',"
            "    scrollH: el.scrollHeight,"
            "    clientH: el.clientHeight,"
            "    scrollTop: el.scrollTop,"
            "    overflowY: s.overflowY,"
            "    overflowX: s.overflowX,"
            "    rectTop: Math.round(rect.top),"
            "    rectLeft: Math.round(rect.left),"
            "    rectW: Math.round(rect.width),"
            "    rectH: Math.round(rect.height),"
            "   });"
            "  }"
            " }"
            " lista.sort((a, b) => b.scrollH - a.scrollH);"
            " return lista.slice(0, 20);"
            "}"
        )
        log.info(f"=== Elementos scrollaveis: {len(resultado)} ===")
        for r in resultado:
            log.info(
                f"  {r['tag']}"
                f" testid='{r['testid']}' role='{r['role']}'"
                f" scrollH={r['scrollH']} clientH={r['clientH']} scrollTop={r['scrollTop']}"
                f" overflowY={r['overflowY']} overflowX={r['overflowX']}"
                f" rect=({r['rectLeft']},{r['rectTop']} {r['rectW']}x{r['rectH']})"
                f" osv='{r['osv']}' cls='{r['cls']}'"
            )
        log.info(f"Elemento focado atual: {get_focused(page)}")
        return resultado
    except Exception:
        log.error(f"detectar_container_scroll ERRO:\n{traceback.format_exc()}")
        return []


def scroll_e_extrair(page):
    """
    Extrai musicas de playlist com virtualização por translateY.

    O Spotify usa um pool fixo de ~51 containers DOM reutilizados.
    Ao scrollar, muda transform:translateY e aria-rowindex no elemento
    pai [role='row'], mas não cria novos elementos tracklist-row.

    Estrategia:
    - Ler aria-rowindex do elemento pai [role='row'] de cada tracklist-row
    - Continuar scrollando ate cobrir todos os indices 1..rowcount
    - Parar quando nao aparecerem indices novos por N passagens

    Retorna (lista_de_musicas, rowcount) — rowcount é usado pelo chamador
    para decidir se a extração ficou completa o suficiente (bug 1/2).
    """
    musicas  = {}   # rowindex -> "Artista - Titulo"
    log.info("=== SCROLL+EXTRACAO INICIADA ===")

    salvar_html_debug(page)
    detectar_container_scroll(page)

    rowcount = page.evaluate("""
        () => {
            const g = document.querySelector('[data-testid="playlist-tracklist"]');
            return g ? parseInt(g.getAttribute('aria-rowcount') || '0') : 0;
        }
    """)
    log.info(f"aria-rowcount total: {rowcount}")

    osv_info = page.evaluate(
        "() => {"
        " const osvs = Array.from(document.querySelectorAll('[data-overlayscrollbars-viewport]'));"
        " return osvs.map(el => {"
        "  const rect = el.getBoundingClientRect();"
        "  return {scrollH: el.scrollHeight, clientH: el.clientHeight, scrollTop: el.scrollTop,"
        "          rectLeft: Math.round(rect.left), rectTop: Math.round(rect.top),"
        "          rectW: Math.round(rect.width), rectH: Math.round(rect.height)};"
        " });"
        "}"
    )
    osv_principal = None
    for osv in osv_info:
        if osv.get("rectLeft", 0) > 300 and osv.get("scrollH", 0) > 1000:
            if osv_principal is None or osv["scrollH"] > osv_principal["scrollH"]:
                osv_principal = osv
    log.info(f"OSV principal: {osv_principal}")

    if osv_principal:
        safe_x = osv_principal["rectLeft"] + osv_principal["rectW"] // 2
        safe_y = osv_principal["rectTop"]  + osv_principal["rectH"] // 2
    else:
        safe_x, safe_y = 660, 300
    log.info(f"Coordenada segura: ({safe_x}, {safe_y})")

    try:
        page.mouse.move(safe_x, safe_y)
    except Exception:
        log.error(f"mouse.move inicial ERRO:\n{traceback.format_exc()}")
    time.sleep(0.3)

    sem_avanco = 0
    indices_vistos = set()
    _iteracoes = 0

    while sem_avanco < 8:
        # Bug 10: teto absoluto de iterações — se o rowindex nunca for
        # encontrado (mudança no DOM do Spotify), a chave de fallback
        # `ni_{len(musicas)}` muda a cada passagem e `novos` nunca é 0,
        # então sem_avanco jamais dispara e o loop rodaria para sempre.
        _iteracoes += 1
        if _iteracoes > MAX_ITERACOES_SCROLL:
            log.warning(f"scroll_e_extrair: atingiu o teto de {MAX_ITERACOES_SCROLL} iterações — abortando para evitar loop infinito.")
            print(f"\n  AVISO: parado após {MAX_ITERACOES_SCROLL} iterações (possível problema de extração).")
            break

        extraidos = page.evaluate("""
            () => {
                const resultado = [];
                const rows = document.querySelectorAll('[data-testid="tracklist-row"]');
                for (const row of rows) {
                    let el = row;
                    let rowindex = null;
                    for (let i = 0; i < 5; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        const idx = el.getAttribute('aria-rowindex');
                        if (idx) { rowindex = parseInt(idx); break; }
                    }

                    let titulo = '';
                    const tlink = row.querySelector('[data-testid="internal-track-link"] div')
                               || row.querySelector('[data-testid="internal-track-link"]');
                    if (tlink) titulo = tlink.innerText.trim();

                    let artista = '';
                    const alink = row.querySelector('a[href*="/artist/"]');
                    if (alink) artista = alink.innerText.trim();

                    if (titulo && artista) {
                        resultado.push({rowindex: rowindex, musica: artista + ' - ' + titulo});
                    }
                }
                return resultado;
            }
        """)

        novos = 0
        for item in extraidos:
            ri = item.get("rowindex") or f"ni_{len(musicas)}"
            key = str(ri)
            if key not in musicas:
                musicas[key] = item["musica"]
                indices_vistos.add(ri)
                novos += 1
                log.debug(f"[rowindex={ri}] OK: {item['musica']}")

        total = len(musicas)
        print(f"  {total}/{rowcount or '?'} musicas extraidas...", end="\r", flush=True)

        if rowcount > 0 and len(indices_vistos) >= rowcount:
            log.info(f"Todos os {rowcount} indices cobertos!")
            break

        idx_max = max(indices_vistos) if indices_vistos else 0
        log.debug(f"passagem: novos={novos} total={total} idx_max={idx_max}/{rowcount} sem_avanco={sem_avanco}")

        if novos == 0:
            sem_avanco += 1
        else:
            sem_avanco = 0

        try:
            resultado = page.evaluate(
                "() => {"
                " const osvs = Array.from(document.querySelectorAll('[data-overlayscrollbars-viewport]'));"
                " let t = null;"
                " for (const el of osvs) {"
                "  const r = el.getBoundingClientRect();"
                "  if (r.left > 300 && el.scrollHeight > 1000) { t = el; break; }"
                " }"
                " if (!t) t = document.querySelector('main');"
                " if (!t) return {ok: false};"
                " const antes = t.scrollTop;"
                " t.scrollTop += 600;"
                " t.dispatchEvent(new Event('scroll', {bubbles: true}));"
                " document.dispatchEvent(new Event('scroll', {bubbles: false}));"
                " window.dispatchEvent(new Event('scroll', {bubbles: false}));"
                " return {ok: true, antes: antes, depois: t.scrollTop};"
                "}"
            )
            if resultado.get("depois", 0) == resultado.get("antes", 0):
                log.warning(f"scrollTop nao mudou: {resultado}")
            else:
                log.debug(f"scroll: {resultado['antes']} -> {resultado['depois']}")
        except Exception:
            log.error(f"Scroll ERRO:\n{traceback.format_exc()}")

        time.sleep(SCROLL_WAIT)

    print(f"  {len(musicas)} musicas extraidas.          ")
    log.info(f"=== EXTRACAO FINALIZADA: {len(musicas)} musicas (rowcount={rowcount}) ===")
    return list(musicas.values()), rowcount


def extrair_via_spotapi(url: str):
    """
    Tenta extrair a playlist via SpotAPI (API interna do Spotify, mesmos
    endpoints que open.spotify.com usa) - sem abrir browser e sem login,
    usando um token anonimo gerado localmente.

    So funciona pra playlists acessiveis por link sem estar logado (a
    grande maioria - o toggle "publica" do perfil nao é o que decide
    isso, é o link em si). Playlists de verdade privadas (compartilhamento
    restrito) fazem a API retornar vazio/erro, e o chamador deve cair
    pro scraping via Playwright.

    Retorna (lista_de_musicas, total_esperado) em caso de sucesso, ou
    None se o SpotAPI nao estiver disponivel ou a extração falhar por
    qualquer motivo (nunca levanta exceção - só sinaliza fallback).
    """
    if not SPOTAPI_OK:
        return None

    try:
        pl = PublicPlaylist(url)
        musicas = []
        total_esperado = None

        for chunk in pl.paginate_playlist():
            if total_esperado is None:
                total_esperado = chunk.get("totalCount")
            for item in chunk.get("items", []):
                dados = (item.get("itemV2") or {}).get("data") or {}
                titulo = dados.get("name", "").strip()
                artistas_items = ((dados.get("artists") or {}).get("items")) or []
                artistas = ",".join(
                    a["profile"]["name"].strip()
                    for a in artistas_items
                    if a.get("profile", {}).get("name")
                )
                if titulo and artistas:
                    musicas.append(f"{artistas} - {titulo}")
                    print(f"  {len(musicas)}/{total_esperado or '?'} musicas extraidas...", end="\r", flush=True)

        print(f"  {len(musicas)} musicas extraidas (via SpotAPI).          ")
        log.info(f"[SPOTAPI] Extração via API concluída: {len(musicas)} músicas (total esperado: {total_esperado})")
        return musicas, (total_esperado or len(musicas))
    except Exception:
        log.warning(f"[SPOTAPI] Falhou, caindo pro scraping via Playwright:\n{traceback.format_exc()}")
        return None


def extrair_playlist(url):
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    url_limpa = url.split("?")[0].strip()
    log.info(f"URL limpa: {url_limpa}")

    with sync_playwright() as p:
        print("Abrindo browser...")
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        print("Verificando sessao...")
        try:
            page.goto("https://open.spotify.com", wait_until="domcontentloaded", timeout=30000)
        except Exception:
            log.error(f"Erro ao carregar home:\n{traceback.format_exc()}")
            browser.close()
            sys.exit(1)

        time.sleep(3)
        log.debug(f"URL apos home: {page.url}")

        # Bug 22: trata None (estado ambíguo) igual a "não logado" — aguarda
        # o login em vez de seguir em frente às cegas.
        if esta_logado(page) is not True:
            print()
            print("=" * 60)
            print("  LOGIN NECESSARIO")
            print("  Faca login no Spotify no browser que abriu.")
            print("  O script continua apos o login completo.")
            print("=" * 60)
            log.info("Login necessario — aguardando usuario")
            if not aguardar_login(page):
                print("ERRO: timeout aguardando login (10 min).")
                log.error("Timeout aguardando login")
                browser.close()
                sys.exit(1)

        print("\n  Login OK! Acessando playlist...")
        log.info("Login confirmado")

        try:
            page.goto(url_limpa, wait_until="domcontentloaded", timeout=30000)
        except PWTimeout:
            log.error(f"Timeout ao carregar playlist:\n{traceback.format_exc()}")
            print("ERRO: timeout carregando a playlist.")
            browser.close()
            sys.exit(1)
        except Exception:
            log.error(f"Erro ao navegar:\n{traceback.format_exc()}")
            browser.close()
            sys.exit(1)

        time.sleep(4)
        log.debug(f"URL apos navegacao: {page.url}")

        carregou = False
        for sel in [
            "[data-testid='tracklist-row']",
            "[data-testid='playlist-tracklist']",
            "div[role='row']",
        ]:
            try:
                page.wait_for_selector(sel, timeout=10000)
                carregou = True
                log.debug(f"Seletor OK: {sel}")
                break
            except PWTimeout:
                log.debug(f"Seletor timeout: {sel}")
            except Exception:
                log.error(f"Erro seletor '{sel}':\n{traceback.format_exc()}")

        if not carregou:
            print("ERRO: playlist nao encontrada. Verifique o link.")
            log.error(f"Nenhum seletor encontrado. URL: {page.url}")
            salvar_html_debug(page)
            browser.close()
            sys.exit(1)

        time.sleep(2)

        nome = "playlist"
        try:
            el = page.locator("h1").first
            if el.count() > 0:
                nome = el.inner_text().strip()
        except Exception:
            log.warning(f"Nome da playlist:\n{traceback.format_exc()}")

        print(f"Playlist: {nome}")
        log.info(f"Nome: '{nome}' | URL real: {page.url}")

        musicas, rowcount = scroll_e_extrair(page)
        browser.close()
        return musicas, rowcount


def extrair_playlist_id(url: str) -> str:
    """ID da playlist (sem query string), usado como chave de identidade
    pra saber se duas URLs apontam pra mesma playlist do Spotify."""
    return url.split("?")[0].strip().rstrip("/").split("playlist/")[-1]


def _arquivo_source(nome_playlist: str) -> Path:
    return _playlists_mod.playlists_dir() / nome_playlist / "spotify_source.json"


def carregar_source(nome_playlist: str) -> dict | None:
    """Lê de qual playlist_id/URL do Spotify essa playlist local veio (se
    já foi importada por este script antes). None se nunca foi."""
    arq = _arquivo_source(nome_playlist)
    if not arq.exists():
        return None
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        return None


def salvar_source(nome_playlist: str, playlist_id: str, url: str):
    dados = {
        "playlist_id": playlist_id,
        "url": url,
        "last_export": datetime.now().isoformat(),
    }
    _arquivo_source(nome_playlist).write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")


def buscar_playlist_por_source(playlist_id: str) -> str | None:
    """Procura, entre as playlists locais já existentes, qual (se alguma)
    já foi importada a partir desse mesmo playlist_id do Spotify."""
    for nome in _playlists_mod.listar_playlists():
        dados = carregar_source(nome)
        if dados and dados.get("playlist_id") == playlist_id:
            return nome
    return None


def salvar(musicas, arquivo):
    vistas, unicas = set(), []
    for m in musicas:
        k = m.lower().strip()
        if k not in vistas:
            vistas.add(k)
            unicas.append(m)
    arquivo.write_text("\n".join(unicas), encoding="utf-8")
    return len(unicas)


def copiar_para_playlist(origem: Path, destino: Path):
    """
    Copia o playlist.txt exportado pra pasta da playlist de destino.
    Escreve atomicamente (arquivo .tmp + os.replace) e guarda a versão
    anterior com backup com timestamp, pra nunca perder a lista antiga
    se algo der errado no meio da cópia — ou se duas exportações ruins
    acontecerem em sequência (um nome fixo de backup seria sobrescrito
    na segunda).
    """
    conteudo = origem.read_text(encoding="utf-8")
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(conteudo, encoding="utf-8")
    if destino.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = destino.with_name(f"{destino.stem}.{ts}.txt.bak")
        destino.replace(bak)
    os.replace(tmp, destino)


def main():
    print()
    print("=" * 60)
    print("  SPOTIFY EXPORT - playlist.txt")
    print("=" * 60)
    print()

    # Bug 26: URL da playlist pode vir por argumento de linha de comando,
    # com fallback para o valor configurado no topo do arquivo — antes só
    # dava pra trocar de playlist editando o código-fonte.
    url = sys.argv[1] if len(sys.argv) > 1 else PLAYLIST_URL
    nome_playlist = sys.argv[2] if len(sys.argv) > 2 else None

    if "SEU_LINK_AQUI" in url or "open.spotify.com/playlist/" not in url:
        print("ERRO: configure o PLAYLIST_URL no topo do script, ou passe a URL como argumento.")
        print()
        print('  python -m soundvault.spotify_export "https://open.spotify.com/playlist/..." "NomeDaPlaylist"')
        sys.exit(1)

    # Bug pedido pelo usuário: reimportar o MESMO link do Spotify sob um
    # nome de destino diferente (esquecido/digitado errado) criava uma
    # playlist local DUPLICADA em vez de atualizar a existente. Cada
    # playlist local grava de qual playlist_id do Spotify ela veio
    # (spotify_source.json) — usamos isso pra detectar e decidir.
    playlist_id = extrair_playlist_id(url)
    match_existente = buscar_playlist_por_source(playlist_id)
    existentes = _playlists_mod.listar_playlists()

    if nome_playlist is None:
        if match_existente:
            nome_playlist = match_existente
            print(f"Essa playlist do Spotify já foi importada antes como '{nome_playlist}' — atualizando ela automaticamente.")
        elif len(existentes) == 1:
            nome_playlist = existentes[0]
        else:
            print("ERRO: especifique o nome da playlist de destino (segundo argumento).")
            print('  python -m soundvault.spotify_export "<url>" "<NomeDaPlaylist>"')
            if existentes:
                print(f"Playlists existentes: {', '.join(existentes)}")
            else:
                print("Nenhuma playlist existe ainda — crie uma pelo menu (opção G) antes de exportar.")
            sys.exit(1)
    elif match_existente and match_existente != nome_playlist:
        # Mesma origem do Spotify, nome de destino diferente do que foi
        # usado da última vez — provavelmente esquecido/digitado errado.
        # Continuar criaria uma duplicata da mesma playlist do Spotify.
        print(f"AVISO: essa playlist do Spotify já foi importada como '{match_existente}' (não '{nome_playlist}').")
        print(f"Continuar vai criar '{nome_playlist}' como uma SEGUNDA cópia da mesma playlist — duplicata.")
        resposta = input(f"Tem certeza que quer criar '{nome_playlist}' mesmo assim? [s/N]: ").strip().upper()
        if resposta != "S":
            print(f"Cancelado. Rode de novo sem informar o nome — ele detecta e atualiza '{match_existente}' automaticamente.")
            sys.exit(1)
    elif nome_playlist in existentes:
        origem_atual = carregar_source(nome_playlist)
        if origem_atual and origem_atual.get("playlist_id") and origem_atual["playlist_id"] != playlist_id:
            # A playlist de destino já existe e veio de OUTRO link do
            # Spotify — sobrescrever aqui é "alteração indevida" de
            # conteúdo não relacionado, exige confirmação explícita.
            print(f"AVISO: a playlist '{nome_playlist}' já existe e veio de OUTRO link do Spotify.")
            print("Continuar vai SUBSTITUIR o conteúdo dela pelo desta playlist diferente.")
            confirmacao = input(f"Digite '{nome_playlist}' de novo pra confirmar a substituição: ").strip()
            if confirmacao != nome_playlist:
                print("Cancelado — nada foi alterado.")
                sys.exit(1)

    log.info(f"=== EXPORT INICIADO | {url} -> playlist '{nome_playlist}' ===")

    resultado = None
    if SPOTAPI_OK:
        print("Tentando via SpotAPI (rápido, sem abrir browser)...")
        resultado = extrair_via_spotapi(url)
        if resultado is not None:
            _musicas_sa, _total_sa = resultado
            # Mesmo critério de completude usado mais abaixo (bugs 1/2) —
            # um resultado parcial do SpotAPI (ex: paginação incompleta)
            # deve cair pro fallback, não ser aceito pela metade.
            if _total_sa > 0 and len(_musicas_sa) < _total_sa * 0.9:
                log.warning(f"[SPOTAPI] Resultado incompleto ({len(_musicas_sa)}/{_total_sa}) — caindo pro Playwright.")
                resultado = None
        if resultado is None:
            print("  SpotAPI não conseguiu (playlist privada ou instável) — caindo pro método com browser.")
    else:
        print("Dica: 'pip install spotapi' habilita um caminho mais rápido, sem abrir browser.")

    if resultado is not None:
        musicas, rowcount = resultado
    else:
        verificar_dependencias()
        try:
            musicas, rowcount = extrair_playlist(url)
        except Exception:
            log.error(f"ERRO FATAL:\n{traceback.format_exc()}")
            print(f"\nERRO FATAL. Verifique: {DEBUG_FILE.name}")
            sys.exit(1)

    if not musicas:
        print("\nERRO: nenhuma musica extraida.")
        print(f"Verifique: {DEBUG_FILE.name}")
        sys.exit(1)

    # Bugs 1/2: aborta se a raspagem ficou visivelmente incompleta em vez
    # de sobrescrever um playlist.txt bom com uma lista truncada.
    if rowcount > 0 and len(musicas) < rowcount * 0.9:
        print(f"\nAVISO: raspagem incompleta — {len(musicas)} de {rowcount} músicas capturadas (<90%).")
        print("playlist.txt NÃO foi sobrescrito para proteger os dados existentes.")
        log.warning(f"Raspagem incompleta: {len(musicas)}/{rowcount} — abortando escrita.")
        sys.exit(1)

    total = salvar(musicas, OUTPUT_FILE)
    log.info(f"Salvas: {total} musicas em {OUTPUT_FILE}")

    # Explica a diferença de contagem em vez de deixar o usuário achando
    # que músicas sumiram — playlist.txt guarda uma linha por música
    # ÚNICA (o Sync já trata por nome, então repetir a linha não baixaria
    # de novo), mas se a playlist do Spotify tem a mesma música 2x/3x, o
    # total aqui fica menor que o total lá, e isso precisa ficar claro.
    repetidas = len(musicas) - total
    if repetidas > 0:
        print(f"({repetidas} repetida(s) na playlist do Spotify — mantida 1 cópia de cada; não afeta o download)")
        log.info(f"{repetidas} entrada(s) duplicada(s) na playlist do Spotify, colapsadas em playlist.txt")

    try:
        destino = _playlists_mod.criar_playlist(nome_playlist)
    except ValueError as e:
        print(f"ERRO: nome de playlist inválido ({e})")
        sys.exit(1)
    try:
        copiar_para_playlist(OUTPUT_FILE, destino)
        salvar_source(nome_playlist, playlist_id, url)
        log.info(f"Copiado automaticamente para {destino}")
        copiado = True
    except Exception:
        log.error(f"Falha ao copiar para a playlist:\n{traceback.format_exc()}")
        copiado = False

    print()
    print("=" * 60)
    print(f"  OK: {total} musicas salvas em: {OUTPUT_FILE.name}")
    print("=" * 60)
    print()
    if copiado:
        print(f"playlist.txt copiado automaticamente para: playlists/{nome_playlist}/playlist.txt")
        print("(a versao anterior foi salva com backup com timestamp)")
        print("Proximo passo: rode o play.bat -> opcao 1 (Sincronizar)")
    else:
        print(f"ERRO ao copiar automaticamente. Copie manualmente {OUTPUT_FILE.name}")
        print(f"para playlists/{nome_playlist}/playlist.txt. Verifique: {DEBUG_FILE.name}")
    print()


if __name__ == "__main__":
    main()
