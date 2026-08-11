import hashlib
import json
import os
import subprocess
from pathlib import Path

from . import config, eq_presets
from .console_log import log

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


def _extrair_json_loudnorm(stderr: str) -> dict | None:
    """
    loudnorm em print_format=json escreve um bloco JSON solto no meio do
    resto do log do FFmpeg no stderr — isola o bloco entre a primeira '{'
    e a última '}' pra conseguir parsear.
    """
    inicio = stderr.find("{")
    fim = stderr.rfind("}")
    if inicio == -1 or fim == -1 or fim < inicio:
        return None
    try:
        return json.loads(stderr[inicio:fim + 1])
    except json.JSONDecodeError:
        return None


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
            "ffmpeg", "-i", str(origem),
            "-af", eq_chain + f"loudnorm=I={alvo['I']}:TP={alvo['TP']}:LRA={alvo['LRA']}:print_format=json",
            "-vn", "-sn", "-dn",
            "-f", "null", "NUL" if os.name == "nt" else "/dev/null",
        ]
        probe = subprocess.run(
            cmd_probe, capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})
        )

        medido = _extrair_json_loudnorm(probe.stderr)
        if medido is None:
            log.warning(f"renderizar_audio: não foi possível medir loudness de {origem.name} — renderização abortada.")
            return False

        cmd = [
            "ffmpeg", "-y", "-i", str(origem),
            "-af", (
                eq_chain +
                f"loudnorm=I={alvo['I']}:TP={alvo['TP']}:LRA={alvo['LRA']}:"
                f"measured_I={medido['input_i']}:measured_TP={medido['input_tp']}:"
                f"measured_LRA={medido['input_lra']}:measured_thresh={medido['input_thresh']}:"
                f"offset={medido['target_offset']}:linear=true:print_format=summary"
            ),
            "-codec:a", "libmp3lame", "-q:a", "2",
            "-map_metadata", "0",
            str(tmp),
        ]
        result = subprocess.run(
            cmd, capture_output=True, timeout=180,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {})
        )
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 10240:
            tmp.replace(destino)
            log.info(f"Renderizado: {destino.name} [preset={preset_id} | {medido['input_i']}LUFS -> {alvo['I']}LUFS]")
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
