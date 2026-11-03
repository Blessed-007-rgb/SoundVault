"""Stop: se há .py de _core alterado, roda pytest + pyright antes de encerrar o turno.

Falhou -> exit 2 com o resumo no stderr (o Claude continua e corrige). Para não
rodar de novo sem necessidade, guarda uma impressão digital (caminho+mtime+tamanho)
dos .py alterados que já passaram. `stop_hook_active` evita laço infinito.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
CORE = RAIZ / "Download Musicas" / "_core"


def py_alterados() -> list[Path]:
    r = subprocess.run(
        ["git", "status", "--porcelain", "--", "*.py"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    achados = []
    for linha in r.stdout.splitlines():
        rel = linha[3:].strip().strip('"')
        p = RAIZ / rel
        if p.suffix == ".py" and "_core" in p.parts and p.exists():
            achados.append(p)
    return achados


def impressao(arqs: list[Path]) -> str:
    h = hashlib.sha1()
    for p in sorted(arqs):
        st = p.stat()
        h.update(f"{p}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    return h.hexdigest()


def executar(cmd: list[str], limite: int) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(cmd, cwd=CORE, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=limite, env=env)


def main() -> int:
    try:
        dados = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        dados = {}
    if dados.get("stop_hook_active"):
        return 0
    if not CORE.exists() or not shutil.which("git"):
        return 0
    arqs = py_alterados()
    if not arqs:
        return 0
    marca = Path(tempfile.gettempdir()) / f"soundvault_hook_ok_{hashlib.sha1(str(RAIZ).encode()).hexdigest()[:8]}.txt"
    atual = impressao(arqs)
    if marca.exists() and marca.read_text(encoding="utf-8").strip() == atual:
        return 0

    problemas = []
    t = executar([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--tb=short", "-x"], 150)
    if t.returncode != 0:
        problemas.append("pytest falhou:\n" + "\n".join((t.stdout + t.stderr).strip().splitlines()[-25:]))
    pyright = shutil.which("pyright")
    if pyright:
        p = executar([pyright], 120)
        if p.returncode != 0:
            problemas.append("pyright encontrou erros:\n" + "\n".join(p.stdout.strip().splitlines()[-25:]))
    if problemas:
        sys.stderr.write("\n\n".join(problemas) + "\n")
        return 2
    marca.write_text(atual, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
