import hashlib
import os
import subprocess
from pathlib import Path

from . import config
from .console_log import log

try:
    from mutagen.id3 import ID3, TXXX, ID3NoHeaderError
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

_EQ_TAG_DESC = "ytdlp_eq_profile"


def _montar_eq_chain() -> str:
    if not config.EQ_ATIVO:
        return ""
    return (
        "equalizer=f=80:width_type=o:w=1:g=0.5,"
        "equalizer=f=300:width_type=o:w=1:g=-1.5,"
        "equalizer=f=3000:width_type=o:w=1:g=1.0,"
        "equalizer=f=10000:width_type=o:w=1:g=1.5,"
    )


def _perfil_atual(eq_chain: str) -> str:
    """
    Hash curto dos parâmetros de EQ/normalização em uso agora. Gravado
    como tag TXXX no MP3 após cada normalização bem-sucedida — permite
    que "Reaplicar Áudio" pule arquivos que já foram processados com
    esse perfil exato, em vez de aplicar o mesmo EQ de novo em cima do
    EQ já aplicado (os ganhos somam e cada passagem recodifica com
    perda, degradando a qualidade progressivamente a cada reprocessamento).
    """
    bruto = f"{config.EQ_ATIVO}|{config.PEAK_TARGET}|{eq_chain}"
    return hashlib.md5(bruto.encode("utf-8")).hexdigest()[:12]


def ja_processado_com_perfil_atual(caminho: Path) -> bool:
    """True se o MP3 já tem a marca do perfil de EQ/normalização atual."""
    if not MUTAGEN_OK:
        return False
    try:
        tags = ID3(str(caminho))
        frame = tags.get(f"TXXX:{_EQ_TAG_DESC}")
        if frame is None or not frame.text:
            return False
        return frame.text[0] == _perfil_atual(_montar_eq_chain())
    except Exception:
        return False


def _gravar_perfil_eq(caminho: Path, perfil: str):
    if not MUTAGEN_OK:
        return
    try:
        try:
            tags = ID3(str(caminho))
        except ID3NoHeaderError:
            tags = ID3()
        tags[f"TXXX:{_EQ_TAG_DESC}"] = TXXX(encoding=3, desc=_EQ_TAG_DESC, text=perfil)
        tags.save(str(caminho), v2_version=3)
    except Exception as e:
        log.debug(f"Não foi possível gravar marca de perfil EQ em {caminho.name}: {e}")


def normalizar_volume(caminho: Path) -> bool:
    """
    Pipeline de áudio em dois passos:

    Passo 1 — EQ para fone de ouvido fechado (se EQ_ATIVO=True):
        • +0.5 dB em 80 Hz   — sub-bass suave
        • -1.5 dB em 300 Hz  — corta barro nos médio-graves
        • +1.0 dB em 3 kHz   — presença e clareza vocal
        • +1.5 dB em 10 kHz  — ar e brilho suave

    Passo 2 — Normalização por pico (volumedetect + volume):
        • Mede o pico real da faixa já com EQ aplicado
        • Aplica ganho para que o pico chegue a PEAK_TARGET (-3.0 dBFS)
        • Zero compressão — dinâmica 100% preservada

    Por que -3.0 dBFS e não -1.0: a recodificação com perdas pra MP3 gera
    picos "entre amostras" que podem exceder o pico medido antes da
    codificação. Com só 1dB de margem esse overshoot comia toda a
    redução e o pico final ficava preso no teto (0 dBFS) de forma
    inconsistente entre faixas — masters "mais altas" (hip-hop, pop)
    sofriam mais que faixas com mastering mais dinâmico, resultando em
    volume final desigual entre músicas mesmo depois de normalizadas.
    """
    log.debug(f"normalizar_volume: {caminho.name}")
    if not config.NORMALIZAR_VOLUME:
        return False
    import shutil
    if not shutil.which("ffmpeg"):
        return False
    tmp = caminho.with_suffix(".norm.mp3")
    try:
        eq_chain = _montar_eq_chain()

        cmd_probe = [
            "ffmpeg", "-i", str(caminho),
            "-af", eq_chain + "volumedetect",
            "-vn", "-sn", "-dn",
            "-f", "null", "NUL" if os.name == "nt" else "/dev/null",
        ]
        probe = subprocess.run(
            cmd_probe, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})
        )

        # Bug 15: se não conseguir medir o pico real, NÃO assume 0.0 dB —
        # isso aplicaria um ganho errado silenciosamente. Aborta a
        # normalização e mantém o arquivo como veio do download.
        max_vol = None
        for line in probe.stderr.splitlines():
            if "max_volume" in line:
                try:
                    max_vol = float(line.split(":")[-1].strip().replace(" dB", ""))
                except ValueError:
                    pass
        if max_vol is None:
            log.warning(f"normalizar_volume: não foi possível medir o pico de {caminho.name} — normalização abortada.")
            return False

        ganho = config.PEAK_TARGET - max_vol
        log.debug(f"volumedetect {caminho.name}: pico={max_vol:.1f} ganho={ganho:+.1f} -> {config.PEAK_TARGET} dBFS")

        cmd = [
            "ffmpeg", "-y", "-i", str(caminho),
            "-af", eq_chain + f"volume={ganho:.2f}dB",
            "-codec:a", "libmp3lame", "-q:a", "2",
            "-map_metadata", "0",
            str(tmp),
        ]
        result = subprocess.run(
            cmd, capture_output=True, timeout=120,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})
        )
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 10240:
            tmp.replace(caminho)
            log.info(f"Normalizado: {caminho.name} [pico {max_vol:.1f} -> {config.PEAK_TARGET} dBFS | ganho {ganho:+.1f} dB]")
            _gravar_perfil_eq(caminho, _perfil_atual(eq_chain))
            return True
        else:
            tmp.unlink(missing_ok=True)
            log.warning(f"normalizar_volume aplicação falhou em {caminho.name}")
            return False
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log.warning(f"normalizar_volume falhou em {caminho.name}: {e}")
        return False
