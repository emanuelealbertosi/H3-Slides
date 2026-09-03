"""Explicit links to user-selected GGUF files, kept outside source control."""
import asyncio
import json
import os
from pathlib import Path
import re
import struct
import subprocess


def validate_model(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("Scegli un file GGUF dal disco")
    path = Path(value.strip().strip('"')).expanduser()
    if not path.is_absolute():
        raise ValueError("Inserisci il percorso completo del file GGUF")
    try:
        path = path.resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != ".gguf":
            raise ValueError("Seleziona un file .gguf, non una cartella o un altro formato")
        if "mmproj" in path.name.lower():
            raise ValueError("Questo e un proiettore vision: scegli il modello principale, non mmproj")
        with path.open("rb") as stream:
            header = stream.read(24)
        if len(header) != 24:
            raise ValueError("Il file GGUF e vuoto o incompleto")
        magic, version, tensors, metadata = struct.unpack("<4sIQQ", header)
        if magic != b"GGUF" or version not in (2, 3) or not tensors or not metadata:
            raise ValueError("Il file non contiene un'intestazione GGUF di modello valida")
        split = re.fullmatch(r"(.+)-(\d{5})-of-(\d{5})\.gguf", path.name, re.I)
        if split:
            prefix, index, total = split.groups()
            if index != "00001":
                raise ValueError("Modello suddiviso: scegli il primo file, 00001-of-xxxxx.gguf")
            if not 1 <= int(total) <= 1024:
                raise ValueError("Numero di parti GGUF non valido")
            if any(not (path.parent / f"{prefix}-{i:05}-of-{total}.gguf").is_file()
                   for i in range(1, int(total)+1)):
                raise ValueError("Modello suddiviso incompleto: alcune parti GGUF mancano nella cartella")
    except OSError as exc:
        raise ValueError("File non trovato o non leggibile: controlla percorso, permessi e disco collegato") from exc
    return path


class LocalModelFiles:
    def __init__(self, data_root):
        self.path = Path(data_root) / "model_files.json"

    def read(self):
        if not self.path.exists():
            return {"files": [], "default_model": ""}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("files"), list):
                raise ValueError()
            if not all(isinstance(p, str) for p in data["files"]) or not isinstance(data.get("default_model", ""), str):
                raise ValueError()
            return data
        except (OSError, ValueError) as exc:
            raise ValueError("Configurazione modelli locali non leggibile: controlla data/model_files.json") from exc

    def register(self, value):
        model = validate_model(value)
        data = self.read()
        files = {os.path.normcase(p): p for p in data["files"]}
        files[os.path.normcase(str(model))] = str(model)
        data = {"files": list(files.values()), "default_model": str(model)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
        return str(model)


async def choose_model_file(root, guard):
    if os.name != "nt":
        raise ValueError("Selettore nativo disponibile su Windows; incolla il percorso completo")
    # No user-supplied shell command/arguments. Cancellation never changes the registry.
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    process = subprocess.Popen([str(executable), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                                "-File", str(root / "scripts/pick-model.ps1")],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    communication = None
    try:
        guard.assign(process)
        communication = asyncio.create_task(asyncio.to_thread(process.communicate))
        stdout, _ = await asyncio.wait_for(asyncio.shield(communication), timeout=180)
        if process.returncode:
            raise ValueError("Selettore file non disponibile: incolla il percorso completo del GGUF")
        return stdout.decode("utf-8-sig").strip()
    except TimeoutError as exc:
        raise ValueError("Selezione scaduta: riprova o incolla il percorso del GGUF") from exc
    finally:
        if process.poll() is None:
            process.kill()
        if communication:
            await communication
        else:
            await asyncio.to_thread(process.wait)
            process.stdout.close()
            process.stderr.close()
