import asyncio
import base64
import ctypes
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import time
import aiohttp
from .models import SYSTEM
from .runtime_settings import LoadingSettings, InferenceSettings, ModelProfile
from .local_models import LocalModelFiles, validate_model
from .remote_models import remote_api_url


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
    def __init__(self, root, config, guard, profile_root=None):
        self.root, self.config, self.guard = root, config, guard
        self.process = None
        self.model = None
        self.log = None
        self.last_used = time.time()
        self.lock = asyncio.Lock()
        self.profile_path = Path(profile_root or root / "data") / "llm_profiles.json"
        self.local_files = LocalModelFiles(profile_root or root / "data")
        self.loaded_settings = None

    def profiles(self):
        if not self.profile_path.exists():
            return {}
        return json.loads(self.profile_path.read_text(encoding="utf-8"))

    def profile(self, model):
        default_loading = LoadingSettings(context_size=self.config["context_size"],
                                          gpu_layers=self.config["gpu_layers"]).model_dump()
        saved = self.profiles().get(model, {})
        return ModelProfile.model_validate({"model": model, "loading": saved.get("loading", default_loading),
                                           "inference": saved.get("inference", {})}).model_dump()

    def save_profile(self, value):
        profile = ModelProfile.model_validate(value).model_dump()
        if not any(m["id"] == profile["model"] for m in self.catalog()):
            raise ValueError("Il modello deve essere presente nel catalogo locale")
        profiles = self.profiles()
        profiles[profile["model"]] = profile
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.profile_path.with_suffix(".tmp")
        temp.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.profile_path)
        return profile

    def catalog(self):
        models, candidates, seen = [], [], set()
        for folder in self.config["model_roots"]:
            path = Path(folder)
            if not path.is_absolute():
                path = self.root / path
            if not path.exists():
                continue
            try:
                candidates.extend(path.rglob("*.gguf"))
            except OSError:
                continue
        candidates.extend(Path(p) for p in self.local_files.read()["files"])
        for model in candidates:
            try:
                key = os.path.normcase(str(model.resolve()))
                if key in seen or not model.is_file() or "mmproj" in model.name.lower():
                    continue
                projections = sorted(model.parent.glob("*mmproj*.gguf"))
                models.append({"id": str(model.resolve()), "name": model.stem,
                               "size_gb": round(model.stat().st_size / 1024**3, 2),
                               "vision": bool(projections),
                               "mmproj": str(projections[0]) if projections else ""})
                seen.add(key)
            except OSError:
                continue  # A disconnected drive must not prevent the app from opening.
        return sorted(models, key=lambda m: (not m["vision"], m["name"]))

    def executable_path(self):
        path = Path(self.config["llama_executable"])
        return path if path.is_absolute() else self.root / path

    def status(self):
        running = self.process is not None and self.process.poll() is None
        return {"running": running, "model": self.model if running else None,
                "port": self.config["llama_port"], "managed": True,
                "loading": self.loaded_settings if running else None}

    async def start(self, model_id):
        async with self.lock:
            loading = self.profile(model_id)["loading"]
            if self.status()["running"] and self.model == model_id and self.loaded_settings == loading:
                self.last_used = time.time()
                return
            found = next((m for m in self.catalog() if m["id"] == model_id), None)
            if not found:
                raise ValueError("Seleziona un modello GGUF presente nel catalogo locale")
            validate_model(found["id"])
            await self.stop()
            executable = self.executable_path()
            if not executable.is_file():
                raise ValueError("Manca il motore llama.cpp: metti llama-server.exe e le sue DLL in runtime/llama, oppure configura un'API remota")
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", self.config["llama_port"])) == 0:
                    raise ValueError("Porta llama.cpp occupata da un altro processo; non lo terminerò")
            args = [str(executable), "-m", found["id"], "--host", "127.0.0.1",
                    "--port", str(self.config["llama_port"]), "-c", str(loading["context_size"]),
                    "-ngl", str(loading["gpu_layers"]), "--parallel", "1",
                    "--threads", str(loading["threads"]), "--batch-size", str(loading["batch_size"]),
                    "--ubatch-size", str(loading["ubatch_size"]), "--flash-attn", loading["flash_attention"],
                    "--cache-type-k", loading["cache_type_k"], "--cache-type-v", loading["cache_type_v"],
                    "--load-mode", loading["load_mode"], "--n-cpu-moe", str(loading["cpu_moe_layers"]),
                    "--alias", "h3-slides-local", "--jinja", "--no-webui"]
            if found["mmproj"]:
                args += ["--mmproj", found["mmproj"]]
            self.log = (self.root / "logs" / "llama.log").open("ab", buffering=0)
            self.process = subprocess.Popen(args, cwd=executable.parent, stdout=self.log,
                                            stderr=subprocess.STDOUT,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.guard.assign(self.process)
            self.model = model_id
            self.loaded_settings = loading
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
        self.loaded_settings = None


class LLM:
    def __init__(self, provider, manager):
        self.provider, self.manager = provider, manager

    async def prepare(self):
        if self.provider.mode == "local":
            await self.manager.start(self.provider.model)
            self.url = f"http://127.0.0.1:{self.manager.config['llama_port']}/v1"
            self.model = "h3-slides-local"
            self.sampling = self.manager.profile(self.provider.model)["inference"]
        else:
            if not self.provider.remote_consent:
                raise ValueError("Conferma l'invio del prompt e degli eventuali allegati al provider remoto")
            self.url = remote_api_url(self.provider.base_url)
            if not self.provider.model:
                raise ValueError("Inserisci il nome del modello remoto")
            self.model = self.provider.model
            self.sampling = self.provider.inference.model_dump()

    async def json(self, prompt, schema=None, images=None):
        if schema:
            # Grammar constrains tokens but does not tell the model what the
            # fields mean. Include the contract in the actual conversation too.
            prompt = "Schema JSON richiesto:\n" + json.dumps(schema, ensure_ascii=False) + "\n\n" + prompt
        content = [{"type": "text", "text": prompt}]
        if images:
            if not self.provider.vision:
                raise ValueError("Questo documento richiede vision: abilita un modello multimodale")
            for label, path in images:
                content.append({"type": "text", "text": label})
                data = base64.b64encode(path.read_bytes()).decode()
                content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + data}})
        sampling = getattr(self, "sampling", InferenceSettings().model_dump())
        body = {"model": self.model, "messages": [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": content}], "temperature": sampling["temperature"],
                "top_p": sampling["top_p"], "stream": False}
        if sampling["max_tokens"] is not None:
            body["max_tokens"] = sampling["max_tokens"]
        # Local llama.cpp supports constrained JSON decoding. Remote APIs vary.
        if self.provider.mode == "local":
            # Bounded document extraction needs the final JSON, not a long
            # reasoning channel consuming the entire completion budget.
            body.update({k: sampling[k] for k in ("top_k", "min_p", "repeat_penalty", "seed")})
            body["chat_template_kwargs"] = {"enable_thinking": sampling["thinking"]}
            if not sampling["thinking"]:
                body["reasoning_effort"] = "none"
            body["response_format"] = {"type": "json_object"}
            if schema:
                body["response_format"]["schema"] = schema
        headers = {"Authorization": "Bearer " + self.provider.api_key} if self.provider.mode == "remote" and self.provider.api_key else {}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=sampling.get("timeout_seconds", 360))) as session:
            async with session.post(self.url + "/chat/completions", json=body, headers=headers,
                                    allow_redirects=False) as response:
                if 300 <= response.status < 400:
                    raise ValueError("Il server API reindirizza la richiesta: configura il suo indirizzo finale. "
                                     "Prompt, documenti e chiave non vengono inoltrati altrove.")
                if response.status >= 400:
                    # Never log remote response bodies: they may echo keys or source contents.
                    raise RuntimeError(f"LLM HTTP {response.status}: verifica modello, supporto vision, contesto e credenziali")
                result = await response.json()
        self.manager.last_used = time.time()
        usage = result.get("usage", {})
        logging.info("LLM completato: input=%s output=%s finish=%s",
                     usage.get("prompt_tokens"), usage.get("completion_tokens"),
                     result.get("choices", [{}])[0].get("finish_reason"))
        if result.get("choices", [{}])[0].get("finish_reason") == "length":
            limit = sampling["max_tokens"]
            detail = f"limite richiesto: {limit} token" if limit is not None else "limite deciso dal server"
            raise ValueError(f"Risposta LLM troncata ({detail}). Controlla il massimo token di output in "
                             "Admin e il contesto/limite del server, oppure riduci il contenuto richiesto.")
        try:
            raw = result["choices"][0]["message"]["content"]
            return parse_json(raw)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Il modello non ha restituito JSON valido; cambia modello o riduci il prompt") from exc
