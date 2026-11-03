"""O projeto promete funcionar sem o pacote 'rich' (interface simplificada).
Simula a ausência dele num processo separado e confere que tudo importa e
que o console substituto imprime sem as marcações [cor]."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

RAIZ_CORE = Path(__file__).resolve().parent.parent


def test_modulos_importam_e_imprimem_sem_rich(tmp_path):
    codigo = textwrap.dedent("""
        import sys
        for m in ("rich", "rich.console", "rich.table", "rich.panel", "rich.progress",
                  "rich.prompt", "rich.text", "rich.box"):
            sys.modules[m] = None          # `import rich...` passa a levantar ImportError
        import soundvault.console_log as c
        assert c.RICH_OK is False
        import soundvault.menu, soundvault.sync, soundvault.audit, soundvault.rebuild
        import soundvault.dedupe, soundvault.cache_maint, soundvault.cookies
        import soundvault.__main__
        c.console.print("[bold red]sem marcacao[/] ok")
        c.cprint("[green]cprint ok[/]")
        print("IMPORT_OK")
    """)
    env = {**os.environ, "SOUNDVAULT_ROOT_DIR": str(tmp_path), "PYTHONPATH": str(RAIZ_CORE),
           "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "IMPORT_OK" in r.stdout
    assert "sem marcacao ok" in r.stdout and "[bold" not in r.stdout
