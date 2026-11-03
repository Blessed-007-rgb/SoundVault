"""PostToolUse (Edit|Write): confere o .py recém-editado com ruff (só erros reais).

Entrada: JSON do hook no stdin. Saída: exit 0 se ok/ignorado; exit 2 com o
relatório no stderr se o ruff achar erro (o Claude recebe o texto e corrige).
Nunca falha por ausência de ferramenta: sem ruff instalado, ignora em silêncio.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        dados = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    entrada = dados.get("tool_input") or {}
    resposta = dados.get("tool_response") or {}
    caminho = entrada.get("file_path") or (resposta.get("filePath") if isinstance(resposta, dict) else None)
    if not caminho:
        return 0
    arq = Path(caminho)
    if arq.suffix != ".py" or "_core" not in arq.parts or not arq.exists():
        return 0
    ruff = shutil.which("ruff")
    if not ruff:
        return 0
    r = subprocess.run(
        [ruff, "check", "--no-cache", "--select", "F,E9,B904", "--output-format", "concise", str(arq)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
    )
    if r.returncode == 0:
        return 0
    sys.stderr.write(f"ruff encontrou erros em {arq.name}:\n{r.stdout.strip()}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
