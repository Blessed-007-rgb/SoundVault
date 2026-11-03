import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from . import config, eq_presets
from .console_log import log
from .procutil import sem_janela

from typing import Any

ID3: Any = None
TXXX: Any = None
ID3NoHeaderError: Any = None
try:
    from mutagen.id3 import ID3, TXXX, ID3NoHeaderError
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

_EQ_TAG_DESC = "ytdlp_eq_profile"
_RECEITA_VERSAO = "loudnorm-v1"


def perfil_atual(preset_id: str) -> str:
    """
    Hash curto dos parâmetros do preset em uso agora. Gravado como tag
    TXXX no MP3 da PLAYLIST (não mais no pool, que agora fica cru) após
    cada renderização bem-sucedida, e comparado por
    playlists.reconciliar_links() via render_state.json pra saber se uma
    música precisa ser re-renderizada (preset trocado, ou a receita de EQ
    mudou no código — _RECEITA_VERSAO garante isso mesmo se os valores
    dentro de um preset existente forem só ajustados).
    """
    preset = eq_presets.PRESETS[preset_id]
    bruto = f"{_RECEITA_VERSAO}|{preset_id}|{json.dumps(preset, sort_keys=True)}"
    return hashlib.md5(bruto.encode("utf-8")).hexdigest()[:12]


def _gravar_perfil_eq(caminho: Path, preset_id: str):
    if not MUTAGEN_OK:
        return
    try:
        try:
            tags = ID3(str(caminho))
        except ID3NoHeaderError:
            tags = ID3()
        tags[f"TXXX:{_EQ_TAG_DESC}"] = TXXX(encoding=3, desc=_EQ_TAG_DESC, text=perfil_atual(preset_id))
        tags.save(str(caminho), v2_version=3)
    except Exception as e:
        log.debug(f"Não foi possível gravar marca de perfil EQ em {caminho.name}: {e}")


_RE_LUFS = re.compile(r"^\s+I:\s+(\S+)\s+LUFS", re.MULTILINE)
_RE_TP = re.compile(r"^\s+Peak:\s+(\S+)\s+dBFS", re.MULTILINE)

# Teto de ganho aplicado — protege contra faixas quase silenciosas, onde
# o loudness medido é tão baixo que o ganho necessário estouraria o áudio.
_GANHO_MAX_DB = 20.0


def _medir_loudness(stderr: str) -> tuple[float, float] | None:
    """
    Lê o resumo final do filtro ebur128 (peak=true) no stderr do FFmpeg e
    devolve (loudness integrado em LUFS, true peak em dBFS), ou None se o
    resumo não existir ou o áudio for silêncio digital (-inf).

    Mede o mesmo valor que a primeira passada do loudnorm, só que ~4x mais
    rápido — o loudnorm gasta a maior parte do tempo em sobreamostragem
    interna de true-peak, que aqui não é necessária pra só medir.
    """
    resumo = stderr[stderr.rfind("Summary:"):]
    m_i, m_tp = _RE_LUFS.search(resumo), _RE_TP.search(resumo)
    if not m_i or not m_tp:
        return None
    try:
        lufs, tp = float(m_i.group(1)), float(m_tp.group(1))
    except ValueError:
        return None
    if lufs == float("-inf") or lufs != lufs:
        return None
    return lufs, tp


def renderizar_audio(origem: Path, destino: Path, preset_id: str) -> bool:
    """
    Renderiza `origem` (MP3 cru do pool central) em `destino` (dentro da
    pasta de uma playlist) aplicando o preset `preset_id`:

    Passo 1 — EQ do preset (equalizer= por banda, vazio se o preset não
    tiver nenhuma, ex: Padrão).

    Passo 2 — loudnorm (EBU R128) em duas passadas:
        • Passe 1 mede loudness integrado, true peak e range reais do
          áudio (já com EQ aplicado).
        • Passe 2 aplica ganho linear pro alvo do preset usando os
          valores medidos (measured_*) — mais preciso que medir e aplicar
          numa passada só, e mede TRUE peak (não só pico de amostra como
          o esquema antigo com volumedetect), o que evita por construção
          o overshoot de recodificação lossy que motivava uma margem de
          segurança arbitrária.

    `origem` é sempre o MP3 cru do pool — nunca um arquivo já processado
    — então chamar esta função de novo com um preset diferente nunca
    empilha processamento em cima de processamento anterior.

    Retorna False (sem exceção) se o FFmpeg não estiver disponível, se a
    normalização estiver desligada em config.NORMALIZAR_VOLUME, ou se
    qualquer etapa falhar — quem chama decide o que fazer (pular a
    música, tentar de novo no próximo reconcile).
    """
    log.debug(f"renderizar_audio: {origem.name} -> {destino.name} [{preset_id}]")
    if not config.NORMALIZAR_VOLUME:
        return False
    import shutil
    if not shutil.which("ffmpeg"):
        return False

    eq_chain = eq_presets.montar_eq_chain(preset_id)
    alvo = eq_presets.loudnorm_alvo(preset_id)
    tmp = destino.with_suffix(".render.mp3")

    try:
        cmd_probe = [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(origem),
            "-af", eq_chain + "ebur128=peak=true:framelog=quiet",
            "-vn", "-sn", "-dn",
            "-f", "null", "NUL" if os.name == "nt" else "/dev/null",
        ]
        probe = subprocess.run(
            cmd_probe, capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
            **sem_janela()
        )

        medido = _medir_loudness(probe.stderr)
        if medido is None:
            log.warning(f"renderizar_audio: não foi possível medir loudness de {origem.name} — renderização abortada.")
            return False
        lufs_in, _tp_in = medido

        # Ganho estático até o alvo de loudness (equivale ao loudnorm em
        # modo linear), seguido de um limiter no teto de true peak do
        # preset — cobre faixas cujo pico estouraria o teto depois do ganho.
        ganho_db = max(-_GANHO_MAX_DB, min(_GANHO_MAX_DB, alvo["I"] - lufs_in))
        teto = max(0.0625, min(1.0, 10 ** (alvo["TP"] / 20)))

        cmd = [
            "ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(origem),
            "-af", (
                eq_chain +
                f"volume={ganho_db:.3f}dB,"
                f"alimiter=limit={teto:.4f}:level=disabled"
            ),
            "-codec:a", "libmp3lame", "-q:a", "2",
            "-map_metadata", "0",
            str(tmp),
        ]
        result = subprocess.run(
            cmd, capture_output=True, timeout=180,
            **sem_janela()
        )
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 10240:
            tmp.replace(destino)
            log.info(f"Renderizado: {destino.name} [preset={preset_id} | {lufs_in}LUFS -> {alvo['I']}LUFS]")
            _gravar_perfil_eq(destino, preset_id)
            return True
        else:
            tmp.unlink(missing_ok=True)
            log.warning(f"renderizar_audio: aplicação falhou em {origem.name}")
            return False
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log.warning(f"renderizar_audio falhou em {origem.name}: {e}")
        return False
