import asyncio
import base64
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.parse import urlparse
import aiohttp
from .models import SYSTEM


def parse_json(text):
    text = text.strip()
    if text.startswith("~~~"):
        text = text[3:].removeprefix("json").strip().removesuffix("~~~").strip()
    if text.startswith(chr(96) * 3):
        text = text[3:].removeprefix("json").strip().removesuffix(chr(96) * 3).strip()
    return json.loads(text)


class ChildGuard:
    """Kill only our child processes on owner exit, including an abrupt Windows close."""
    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        from ctypes import wintypes as w
        class BASIC(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                        ("Flags", w.DWORD), ("MinWS", ctypes.c_size_t), ("MaxWS", ctypes.c_size_t),
                        ("Active", w.DWORD), ("Affinity", ctypes.c_size_t),
                        ("Priority", w.DWORD), ("Scheduling", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("r", "w", "o", "rb", "wb", "ob")]
        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("IO", IO), ("ProcessMemory", ctypes.c_size_t),
                        ("JobMemory", ctypes.c_size_t), ("PeakProcess", ctypes.c_size_t),
                        ("PeakJob", ctypes.c_size_t)]
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = w.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.CloseHandle.argtypes = [w.HANDLE]
        handle = k.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not handle or not k.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("Impossibile proteggere i processi figli con un Windows Job Object")
        self.handle, self.kernel = handle, k

    def assign(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            process.kill()
            raise OSError("Impossibile associare il processo figlio; avvio annullato")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class LlamaManager:
    def __init__(self, root, config, guard):
        self.root, self.config, self.guard = root, config, guard
        self.process = None
        self.model = None
        self.log = None
        self.last_used = time.time()
        self.lock = asyncio.Lock()

    def catalog(self):
        models = []
        for folder in self.config["model_roots"]:
            path = Path(folder)
            if not path.is_absolute():
                path = self.root / path
            if not path.exists():
                continue
            for model in path.rglob("*.gguf"):
                if "mmproj" in model.name.lower():
                    continue
                projections = sorted(model.parent.glob("*mmproj*.gguf"))
                models.append({"id": str(model.resolve()), "name": model.stem,
                               "size_gb": round(model.stat().st_size / 1024**3, 2),
                               "vision": bool(projections),
                               "mmproj": str(projections[0]) if projections else ""})
        return sorted(models, key=lambda m: (not m["vision"], m["name"]))

    def status(self):
        running = self.process is not None and self.process.poll() is None
        return {"running": running, "model": self.model if running else None,
                "port": self.config["llama_port"], "managed": True}

    async def start(self, model_id):
        async with self.lock:
            if self.status()["running"] and self.model == model_id:
                self.last_used = time.time()
                return
            found = next((m for m in self.catalog() if m["id"] == model_id), None)
            if not found:
                raise ValueError("Seleziona un modello GGUF presente nel catalogo locale")
            await self.stop()
            executable = Path(self.config["llama_executable"])
            if not executable.is_absolute():
                executable = self.root / executable
            if not executable.is_file():
                raise ValueError("llama-server non installato: controlla config.local.json")
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", self.config["llama_port"])) == 0:
                    raise ValueError("Porta llama.cpp occupata da un altro processo; non lo terminerò")
            args = [str(executable), "-m", found["id"], "--host", "127.0.0.1",
                    "--port", str(self.config["llama_port"]), "-c", str(self.config["context_size"]),
                    "-ngl", str(self.config["gpu_layers"]), "--parallel", "1",
                    "--alias", "h3-slides-local", "--jinja", "--no-webui"]
            if found["mmproj"]:
                args += ["--mmproj", found["mmproj"]]
            self.log = (self.root / "logs" / "llama.log").open("ab", buffering=0)
            self.process = subprocess.Popen(args, cwd=executable.parent, stdout=self.log,
                                            stderr=subprocess.STDOUT,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.guard.assign(self.process)
            self.model = model_id
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
                    for _ in range(240):
                        if self.process.poll() is not None:
                            raise RuntimeError("llama.cpp non si è avviato. Dettagli in logs/llama.log (controlla VRAM e GGUF)")
                        try:
                            async with session.get(f"http://127.0.0.1:{self.config['llama_port']}/health") as response:
                                if response.status == 200:
                                    self.last_used = time.time()
                                    return
                        except (aiohttp.ClientError, TimeoutError):
                            pass
                        await asyncio.sleep(1)
                raise TimeoutError("Caricamento modello oltre il limite di 4 minuti")
            except BaseException:
                await self.stop()
                raise

    async def stop(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(asyncio.to_thread(self.process.wait), timeout=10)
                except TimeoutError:
                    self.process.kill()
                    await asyncio.to_thread(self.process.wait)
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
        self.model = None


class LLM:
    def __init__(self, provider, manager):
        self.provider, self.manager = provider, manager

    async def prepare(self):
        if self.provider.mode == "local":
            await self.manager.start(self.provider.model)
            self.url = f"http://127.0.0.1:{self.manager.config['llama_port']}/v1"
            self.model = "h3-slides-local"
        else:
            parsed = urlparse(self.provider.base_url)
            if not self.provider.remote_consent:
                raise ValueError("Conferma l'invio dei documenti al provider remoto")
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("API remota: usa un URL HTTPS senza credenziali, query o frammenti")
            if not self.provider.model:
                raise ValueError("Inserisci il nome del modello remoto")
            self.url = self.provider.base_url.rstrip("/")
            self.model = self.provider.model

    async def json(self, prompt, schema=None, images=None):
        content = [{"type": "text", "text": prompt}]
        if images:
            if not self.provider.vision:
                raise ValueError("Questo documento richiede vision: abilita un modello multimodale")
            for label, path in images:
                content.append({"type": "text", "text": label})
                data = base64.b64encode(path.read_bytes()).decode()
                content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + data}})
        body = {"model": self.model, "messages": [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": content}], "temperature": 0.35,
                "max_tokens": 3500, "stream": False}
        # Local llama.cpp supports constrained JSON decoding. Remote APIs vary.
        if self.provider.mode == "local" and schema:
            body["response_format"] = {"type": "json_object", "schema": schema}
        headers = {"Authorization": "Bearer " + self.provider.api_key} if self.provider.mode == "remote" and self.provider.api_key else {}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=360)) as session:
            async with session.post(self.url + "/chat/completions", json=body, headers=headers) as response:
                if response.status >= 400:
                    # Never log remote response bodies: they may echo keys or source contents.
                    raise RuntimeError(f"LLM HTTP {response.status}: verifica modello, supporto vision, contesto e credenziali")
                result = await response.json()
        self.manager.last_used = time.time()
        try:
            raw = result["choices"][0]["message"]["content"]
            return parse_json(raw)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Il modello non ha restituito JSON valido; cambia modello o riduci il prompt") from exc
