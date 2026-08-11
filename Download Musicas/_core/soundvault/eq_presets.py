"""
Presets de EQ/loudness aplicados por playlist (ver
playlists.reconciliar_links() e audio.renderizar_audio()).

Valores baseados em referências reais de mercado:
  - Loudness integrado (LUFS) em vez de pico de amostra: é como o Spotify
    normaliza (-14 LUFS no modo "Normal", -11 LUFS no modo "Loud") — pico
    de amostra sozinho não reflete o volume percebido (duas faixas com o
    mesmo pico podem soar bem diferente dependendo da dinâmica do master).
  - Curva em V (grave e agudo realçados) é o padrão de fones/caixas
    populares tipo JBL.
  - Som automotivo mira loudness mais alto (perto do "Loud" do Spotify)
    pra competir com ruído de estrada, com reforço de grave e cuidado pra
    não empurrar a faixa de 2-4kHz (fica estridente em volume alto).
"""

PRESET_PADRAO = "padrao"

PRESETS = {
    "padrao": {
        "label": "Padrão (Plano)",
        "loudnorm": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
        "eq_bands": [],
    },
    "fone": {
        "label": "Fone de Ouvido",
        "loudnorm": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
        "eq_bands": [(60, 1.0), (300, -1.0), (2500, 1.5), (10000, 1.0)],
    },
    "caixa": {
        "label": "Caixa de Som",
        "loudnorm": {"I": -14.0, "TP": -1.5, "LRA": 11.0},
        "eq_bands": [(60, 2.0), (300, -1.0), (2500, 1.5), (10000, 1.0)],
    },
    "carro": {
        "label": "Som Automotivo",
        "loudnorm": {"I": -11.0, "TP": -1.0, "LRA": 11.0},
        "eq_bands": [(63, 3.5), (125, 2.4), (2500, 1.5), (3500, -1.0), (12000, -1.0)],
    },
}


def preset_valido(preset_id: str) -> bool:
    return preset_id in PRESETS


def montar_eq_chain(preset_id: str) -> str:
    """Cadeia de filtros equalizer= do FFmpeg pro preset, com vírgula
    final (pra concatenar direto com o próximo filtro). String vazia se o
    preset não tem bandas de EQ (ex: Padrão)."""
    bandas = PRESETS[preset_id]["eq_bands"]
    if not bandas:
        return ""
    return "".join(
        f"equalizer=f={freq}:width_type=o:w=1:g={ganho},"
        for freq, ganho in bandas
    )


def loudnorm_alvo(preset_id: str) -> dict:
    return PRESETS[preset_id]["loudnorm"]
