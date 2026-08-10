import re
import unicodedata
from difflib import SequenceMatcher

from . import config
from .playlist import parsear
from .console_log import log

# Termos que só são aceitos no resultado se já estiverem no título original —
# senão o vídeo é quase certamente uma versão diferente da música pedida.
PALAVRAS_PROIBIDAS = [
    "remix", "cover", "live", "ao vivo", "karaoke", "instrumental",
    "8d audio", "reaction", "sped up", "slowed", "nightcore", "mashup",
]

# Limiares mínimos pra aceitar um candidato (inspirado no matching do
# projeto spotDL, adaptado pra este projeto: não há duração de referência
# do Spotify aqui, só o texto "Artista - Título" do playlist.txt).
SCORE_MIN_TITULO = 50.0
SCORE_MIN_ARTISTA = 35.0
SCORE_BOM_O_SUFICIENTE = 70.0  # encontrado isso, não precisa tentar query mais ampla


def _normalizar(texto: str) -> str:
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"\(.*?\)|\[.*?\]", " ", texto)  # remove "(Official Video)", "(feat. X)" etc.
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _similaridade(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio() * 100


def _pontuar_candidato(artista: str, titulo: str, entry: dict) -> float | None:
    """
    Retorna um score 0-100 de confiança de que `entry` é a música
    (artista, titulo) pedida, ou None se o candidato deve ser descartado
    (título não bate o suficiente, ou tem termo proibido sem equivalente
    no original — ex.: "Remix" quando a música pedida não é um remix).
    """
    titulo_video = entry.get("title", "") or ""
    uploader = entry.get("uploader", "") or entry.get("channel", "") or ""

    titulo_norm = _normalizar(titulo)
    artista_norm = _normalizar(artista)
    video_norm = _normalizar(titulo_video)
    uploader_norm = _normalizar(uploader)

    if not video_norm:
        return None

    penalidade = 0.0
    for palavra in PALAVRAS_PROIBIDAS:
        if palavra in video_norm and palavra not in titulo_norm:
            penalidade += 25.0

    # Compara o título sozinho e também "Artista Título" concatenado —
    # muitos uploads têm o título do vídeo nesse formato.
    score_titulo = max(
        _similaridade(titulo_norm, video_norm),
        _similaridade(f"{artista_norm} {titulo_norm}", video_norm),
    )

    score_artista = max(
        _similaridade(artista_norm, uploader_norm),
        100.0 if artista_norm and artista_norm in video_norm else 0.0,
    )

    if score_titulo < SCORE_MIN_TITULO or score_artista < SCORE_MIN_ARTISTA:
        return None

    score = (score_titulo * 0.65 + score_artista * 0.35) - penalidade
    return max(0.0, min(100.0, score))


def buscar_ytmusic(chave: str) -> str | None:
    """
    Busca URL no YouTube para músicas sem URL no cache.
    Usa ytsearch (suportado por todas as versões do yt-dlp), tentando
    queries progressivamente mais amplas, e pontua cada candidato por
    similaridade de título/artista — evita baixar a música errada (cover,
    remix, live, homônimo) silenciosamente. Descarta canais "vevo"
    (histórico de bloqueio por copyright nesse fluxo de download).
    """
    artista, titulo = parsear(chave)
    queries = [
        f"ytsearch5:{artista} {titulo} official audio",
        f"ytsearch5:{artista} {titulo} audio",
        f"ytsearch3:{artista} {titulo}",
    ]
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    if config.COOKIES_FILE.exists():
        opts["cookiefile"] = str(config.COOKIES_FILE)

    melhor_url = None
    melhor_score = -1.0
    melhor_titulo_video = ""

    for query in queries:
        try:
            from yt_dlp import YoutubeDL
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
                entries = info.get("entries", []) if info else []
        except Exception as e:
            log.debug(f"buscar_ytmusic falhou para query '{query}': {e}")
            continue

        for entry in entries:
            vid = entry.get("id", "")
            uploader = (entry.get("uploader", "") or entry.get("channel", "")).lower()
            if not vid or "vevo" in uploader:
                continue
            score = _pontuar_candidato(artista, titulo, entry)
            if score is not None and score > melhor_score:
                melhor_score = score
                melhor_url = f"https://www.youtube.com/watch?v={vid}"
                melhor_titulo_video = entry.get("title", "")

        if melhor_score >= SCORE_BOM_O_SUFICIENTE:
            break

    if melhor_url:
        log.debug(
            f"buscar_ytmusic: '{chave}' -> {melhor_url} "
            f"(score {melhor_score:.0f}, video '{melhor_titulo_video}')"
        )
        return melhor_url

    log.warning(f"buscar_ytmusic: nenhum candidato confiável encontrado para '{chave}'")
    return None
