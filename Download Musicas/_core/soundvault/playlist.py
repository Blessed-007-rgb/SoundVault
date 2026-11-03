import hashlib
import re
from pathlib import Path

from typing import Any

MP3: Any = None
try:
    from mutagen.mp3 import MP3
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False



def extrair_video_id(url: str) -> str:
    """
    Extrai o ID de 11 caracteres de uma URL do YouTube, ou "" se não achar.
    Achado nesta revisão: os pontos que salvam URL encontrada via busca
    automática (sync.py, download.py, cache_maint.py) gravavam sempre
    "id": "" no cache, mesmo com o ID disponível na própria URL — isso
    impedia baixar() de registrar a música no sync_state.json
    (`if video_id:` nunca era verdadeiro), fazendo a música nunca contar
    como concluída em nenhum Sync futuro.
    """
    # (?![\w-]) rejeita IDs com mais de 11 caracteres (URL corrompida):
    # sem isso, "v=_xLQ1QkGB6bk" (12 chars) virava o ID errado "_xLQ1QkGB6b"
    # em silêncio, e o download falhava com "video unavailable".
    m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})(?![\w-])", url)
    return m.group(1) if m else ""


def carregar_playlist(caminho: Path) -> list[str]:
    if not caminho.exists():
        return []
    with open(caminho, "r", encoding="utf-8-sig") as f:
        linhas_limpas = (l.strip() for l in f)
        return [l for l in linhas_limpas if l and not l.startswith("#")]


def sanitizar(nome: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", nome).strip()


def parsear(chave: str) -> tuple[str, str]:
    """'Artista - Título' → (artista, titulo)"""
    if " - " in chave:
        a, t = chave.split(" - ", 1)
        return a.strip(), t.strip()
    return chave.strip(), chave.strip()


# Limite do NOME (sem extensão) — o Windows rejeita componentes de caminho
# com mais de 255 caracteres, e ainda entram o prefixo numérico "NNN - ",
# ".render.mp3" e o prefixo/sufixo dos temporários "__dl_...". O maior nome
# real hoje tem ~206 chars, então nenhum arquivo existente é afetado.
MAX_NOME_ARQUIVO = 220


def nome_arquivo(artista: str, titulo: str) -> str:
    """Nome do .mp3 no disco: 'Título - Artista'. Nomes acima de
    MAX_NOME_ARQUIVO são truncados com um sufixo de hash (determinístico,
    evita colisão entre dois nomes longos com o mesmo começo)."""
    nome = sanitizar(f"{titulo} - {artista}")
    if len(nome) <= MAX_NOME_ARQUIVO:
        return nome
    h = hashlib.md5(nome.encode("utf-8")).hexdigest()[:8]
    return f"{nome[:MAX_NOME_ARQUIVO - 10].rstrip()}~{h}"


def detectar_colisoes(nomes: list[str]) -> dict[str, list[str]]:
    """
    Bug 16 (mitigação): sanitizar()/nome_arquivo() não são injetivas — dois
    nomes de playlist diferentes podem gerar o mesmo nome de arquivo no
    disco. Isso não muda o esquema de nomes (mudaria o formato de todo
    arquivo já baixado), mas dá visibilidade: retorna
    {nome_de_arquivo_colidido: [chave1, chave2, ...]} para os casos com
    2+ chaves de playlist mapeando pro mesmo arquivo.
    """
    por_arquivo: dict[str, list[str]] = {}
    for chave in nomes:
        a, t = parsear(chave)
        arq = nome_arquivo(a, t)
        por_arquivo.setdefault(arq, []).append(chave)
    return {arq: chaves for arq, chaves in por_arquivo.items() if len(chaves) > 1}


def checar_integridade(p: Path) -> bool:
    """Verifica se o MP3 existe, tem tamanho mínimo e é um arquivo de áudio válido."""
    if not p.exists() or p.stat().st_size < 10240:
        return False
    if not MUTAGEN_OK:
        return True
    try:
        audio = MP3(str(p))
        return audio.info.length > 5.0
    except Exception:
        return False


def calcular_md5(p: Path) -> str:
    """Bug 14: lê o arquivo protegido contra PermissionError (antivírus
    travando o arquivo logo após um download é comum no Windows). Retorna
    string vazia se não conseguiu ler — chamadores devem tratar '' como
    'hash indisponível agora', não como um hash real."""
    h = hashlib.md5()
    try:
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(8192), b""):
                h.update(b)
    except (PermissionError, OSError):
        return ""
    return h.hexdigest()


ERROS_429 = ["http error 429", "too many requests", "rate limit"]

ERROS_REDE = [
    "http error 503",
    "service unavailable",
    "http error 502",
    "http error 504",
    "bytes read",
    "connection reset",
    "connection refused",
    "timed out",
    "temporary failure",
]

ERROS_PERMANENTES = [
    "copyright claim",
    "video unavailable",
    "this video is unavailable",
    "this video is not available",
    "video is not available",
    "video is no longer available",
    "this video has been removed",
    "private video",
    "account associated with this video has been terminated",
]

ERROS_FORMATO = [
    "requested format is not available",
    "no video formats found",
    "downloaded file is empty",
    "the downloaded file is empty",
    "the page needs to be reloaded",
    "page needs to be reloaded",
]

ERROS_AUTH = [
    "sign in to confirm",
    "requires authentication",
    "please sign in",
    "music premium",
]


def classificar_erro(stderr: str) -> str:
    """
    Retorna:
      'auth'      → cookie expirado/inválido
      'permanent' → vídeo removido, copyright, privado
      'format'    → formato não disponível nessa URL (tenta alternativa)
      'rate'      → HTTP 429, muitas requisições
      'retry'     → erro de rede ou temporário, vale retentar
    """
    s = stderr.lower()
    if any(e in s for e in ERROS_AUTH):
        return "auth"
    if any(e in s for e in ERROS_PERMANENTES):
        return "permanent"
    if any(e in s for e in ERROS_FORMATO):
        return "format"
    if any(e in s for e in ERROS_429):
        return "rate"
    return "retry"
