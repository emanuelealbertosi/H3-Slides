"""Read-only installation diagnostics. Does not load models or modify projects."""
import argparse
import importlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys


def inspect_installation(root, core_only=False):
    errors, warnings = [], []
    if sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        errors.append("Serve Python 3.12 a 64 bit; esegui Installa-H3-slides.bat con l'interprete corretto.")
    try:
        config = json.loads((root / "config.example.json").read_text(encoding="utf-8-sig"))
        if (root / "config.local.json").exists():
            config.update(json.loads((root / "config.local.json").read_text(encoding="utf-8-sig")))
        if not isinstance(config["model_roots"], list) or not isinstance(config["llama_executable"], str):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        errors.append("Configurazione non valida: controlla config.example.json e config.local.json.")
        return errors, warnings
    modules = ["aiohttp", "pydantic", "pypdf", "fitz", "PIL"]
    if not core_only:
        modules += ["manim", "manim_slides"]
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception:
            errors.append(f"Componente Python {module} mancante o non funzionante: riesegui Installa-H3-slides.bat.")
    if not core_only:
        node = root / "runtime/node/node.exe"
        if not node.is_file():
            errors.append("Node dedicato mancante: riesegui Installa-H3-slides.bat.")
        else:
            probe = (
                "require('pptxgenjs');"
                "if(!require('node:fs').existsSync('node_modules/@slidev/cli/bin/slidev.mjs'))throw Error('Slidev mancante');"
                "(async()=>{await (await import('./scripts/dependency-check.mjs')).verifyDependencies();"
                "const b=await require('playwright-chromium').chromium.launch({headless:true});"
                "await b.close()})().catch(e=>{console.error(e.message);process.exitCode=1})"
            )
            env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(root / "runtime/browsers"))
            try:
                result = subprocess.run([str(node), "--input-type=commonjs", "-e", probe], cwd=root, env=env,
                                        capture_output=True, timeout=30,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                if result.returncode:
                    errors.append("Slidev, PPTX o Chromium non pronti: riesegui Installa-H3-slides.bat. " +
                                  result.stderr.decode("utf-8", errors="replace")[-350:])
            except (OSError, subprocess.TimeoutExpired):
                errors.append("Node/Chromium non si avvia: controlla antivirus e runtime, poi riesegui l'installazione.")
    executable = Path(config["llama_executable"])
    if not executable.is_absolute():
        executable = root / executable
    if not executable.is_file():
        warnings.append("Motore LLM locale assente: aggiungi llama-server.exe e DLL in runtime/llama, oppure usa API remota.")
    # Keep missing weights non-fatal: the web app is where the user chooses a file.
    try:
        from .llm import LlamaManager
        manager = LlamaManager(root, config, None)
        if not manager.catalog():
            warnings.append("Nessun modello GGUF trovato. Avvia l'app: verra chiesto di sceglierlo dal disco, senza copiarlo.")
    except Exception as exc:
        warnings.append("Catalogo modelli da controllare: " + str(exc)[:200])
    return errors, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    errors, warnings = inspect_installation(root, args.core_only)
    for message in errors:
        print("ERRORE: " + message)
    for message in warnings:
        print("AVVISO: " + message)
    if not errors:
        print("Verifica componenti completata. I modelli non sono stati caricati.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
