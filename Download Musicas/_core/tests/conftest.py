"""
Fixtures compartilhadas. IMPORTANTE: SOUNDVAULT_ROOT_DIR precisa apontar pra
uma pasta temporária ANTES de importar soundvault.config — o módulo cria o
perfil "Main" (pastas Musicas/ e Logs/) no momento do import, e os testes
nunca podem tocar na biblioteca real do usuário.
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

_RAIZ_TESTES = Path(tempfile.mkdtemp(prefix="soundvault_tests_"))
os.environ["SOUNDVAULT_ROOT_DIR"] = str(_RAIZ_TESTES)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from soundvault import config  # noqa: E402


@pytest.fixture
def perfil():
    """Perfil limpo e isolado (config.* apontando pra uma pasta nova)."""
    config.ativar_perfil(f"t_{uuid.uuid4().hex[:8]}")
    return config.BASE_DIR
