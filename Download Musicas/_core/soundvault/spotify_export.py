"""
spotify_export.py - Exporta playlist do Spotify para playlist.txt

Como usar:
  python -m soundvault.spotify_export "<link da playlist>" ["NomeDaPlaylist"]
  (ou o spotify_export.bat, que pergunta o link e o nome)

Usa o SpotAPI (API interna do Spotify, a mesma do open.spotify.com): sem abrir
navegador e sem login. Funciona com qualquer playlist cujo link abre sem estar
logado; playlists de compartilhamento restrito de verdade nao sao suportadas.

Saida:
  playlist.txt             - uma musica por linha: Artista - Titulo
  spotify_export_debug.log - log detalhado com traceback completo

Requisitos:
  pip install spotapi
"""

import json
import os
import sys
import logging
import traceback
from datetime import datetime
from pathlib import Path

from . import config as _config
from . import playlists as _playlists_mod

from typing import Any

PublicPlaylist: Any = None
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
OUTPUT_FILE  = _PASTA_EXPORT / "_staging_playlist.txt"

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


def extrair_via_spotapi(url: str):
    """
    Tenta extrair a playlist via SpotAPI (API interna do Spotify, mesmos
    endpoints que open.spotify.com usa) - sem abrir browser e sem login,
    usando um token anonimo gerado localmente.

    So funciona pra playlists acessiveis por link sem estar logado (a
    grande maioria - o toggle "publica" do perfil nao é o que decide
    isso, é o link em si). Playlists de verdade privadas (compartilhamento
    restrito) fazem a API retornar vazio/erro, e o chamador
    deve avisar o usuario.

    Retorna (lista_de_musicas, total_esperado) em caso de sucesso, ou
    None se o SpotAPI nao estiver disponivel ou a extração falhar por
    qualquer motivo (nunca levanta exceção - só sinaliza a falha).
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
        log.error(f"[SPOTAPI] Falhou:\n{traceback.format_exc()}")
        return None


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

    if not SPOTAPI_OK:
        print("ERRO: o pacote 'spotapi' nao esta instalado.")
        print("Execute: pip install spotapi")
        log.error("spotapi nao instalado")
        sys.exit(1)

    print("Extraindo via SpotAPI (sem abrir browser)...")
    resultado = extrair_via_spotapi(url)
    if resultado is None:
        print()
        print("ERRO: o SpotAPI nao conseguiu ler a playlist.")
        print("  - Confira se o link e de uma PLAYLIST e se abre sem estar logado")
        print("    (playlists de compartilhamento restrito nao sao suportadas).")
        print(f"  - Se o link esta certo, o Spotify pode ter mudado a API: veja {DEBUG_FILE.name}")
        sys.exit(1)
    musicas, rowcount = resultado

    if not musicas:
        print("\nERRO: nenhuma musica extraida.")
        print(f"Verifique: {DEBUG_FILE.name}")
        sys.exit(1)

    # Bugs 1/2: aborta se a extracao ficou visivelmente incompleta em vez
    # de sobrescrever um playlist.txt bom com uma lista truncada.
    if rowcount > 0 and len(musicas) < rowcount * 0.9:
        print(f"\nAVISO: extracao incompleta — {len(musicas)} de {rowcount} músicas capturadas (<90%).")
        print("playlist.txt NÃO foi sobrescrito para proteger os dados existentes.")
        log.warning(f"Extracao incompleta: {len(musicas)}/{rowcount} — abortando escrita.")
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
