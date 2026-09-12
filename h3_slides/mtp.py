"""Portable, read-only detection of an integrated llama.cpp MTP head.

No weights are allocated or read. Detection is evidence of a compatible head,
not certification that every weight, backend or available VRAM will load it.
"""
import copy
import os
import re
import struct
import subprocess
import threading
from pathlib import Path


MAX_SCAN_BYTES = 128 * 1024 * 1024
MAX_STRING_BYTES = 16 * 1024 * 1024
MAX_ARRAY_ITEMS = 2_000_000
MAX_RECORDS = 200_000
MAX_SHARDS = 64
MAX_HELP_BYTES = 2 * 1024 * 1024
_SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


class ScanLimit(ValueError):
    pass


class _Reader:
    def __init__(self, stream, size, budget):
        self.stream, self.size, self.budget = stream, size, budget

    def reserve(self, count):
        if count < 0 or self.stream.tell()+count > self.size:
            raise ValueError("GGUF troncato")
        if count > self.budget[0]:
            raise ScanLimit("Indice GGUF oltre il limite di lettura")
        self.budget[0] -= count

    def read(self, count):
        self.reserve(count)
        value = self.stream.read(count)
        if len(value) != count:
            raise ValueError("GGUF troncato")
        return value

    def skip(self, count):
        self.reserve(count)
        self.stream.seek(count, 1)

    def number(self, kind):
        return struct.unpack("<"+kind, self.read(struct.calcsize(kind)))[0]

    def string(self, capture=False, limit=MAX_STRING_BYTES):
        length = self.number("Q")
        if length > limit:
            raise ScanLimit("Stringa GGUF oltre il limite")
        if capture:
            return self.read(length).decode("utf-8", errors="strict")
        self.skip(length)

    def value(self, kind, capture=False, depth=0):
        if kind in _SCALARS:
            return self.number(_SCALARS[kind])
        if kind == 8:
            return self.string(capture)
        if kind != 9 or depth >= 3:
            raise ValueError("Tipo metadato GGUF non valido")
        subtype, count = self.number("I"), self.number("Q")
        if count > MAX_ARRAY_ITEMS:
            raise ScanLimit("Array GGUF oltre il limite")
        if subtype in _SCALARS:
            self.skip(count * struct.calcsize(_SCALARS[subtype]))
        elif subtype in (8, 9):
            for _ in range(count):
                self.value(subtype, False, depth+1)
        else:
            raise ValueError("Tipo array GGUF non valido")
        return None


def _signature(path):
    path = Path(path).expanduser().resolve(strict=True)
    stat = path.stat()
    if not path.is_file():
        raise ValueError("File non disponibile")
    return str(path), stat.st_size, stat.st_mtime_ns


def _model_signatures(model):
    first = _signature(model)
    path = Path(first[0])
    match = re.fullmatch(r"(.+)-(\d{5})-of-(\d{5})(\.gguf)", path.name, re.I)
    if not match:
        return (first,)
    part, total = int(match[2]), int(match[3])
    if part != 1 or not 1 <= total <= MAX_SHARDS:
        raise ValueError("Seleziona il primo GGUF di un modello suddiviso valido")
    signatures = []
    for index in range(1, total+1):
        target = path.parent / f"{match[1]}-{index:05}-of-{total:05}{match[4]}"
        signature = _signature(target)
        if Path(signature[0]).parent != path.parent:
            raise ValueError("Parte GGUF esterna alla cartella del modello")
        signatures.append(signature)
    return tuple(signatures)


def _metadata_and_tensors(signatures):
    budget, metadata, tensors = [MAX_SCAN_BYTES], {}, set()
    for name, size, _ in signatures:
        with open(name, "rb") as stream:
            reader = _Reader(stream, size, budget)
            if reader.read(4) != b"GGUF" or reader.number("I") not in (2, 3):
                raise ValueError("Formato GGUF non supportato")
            tensor_count, metadata_count = reader.number("Q"), reader.number("Q")
            if tensor_count > MAX_RECORDS or metadata_count > MAX_RECORDS:
                raise ScanLimit("Troppi record nell'indice GGUF")
            for _ in range(metadata_count):
                key = reader.string(True, limit=4096)
                wanted = key == "general.architecture" or key.endswith((".block_count", ".nextn_predict_layers", ".router_layer"))
                value = reader.value(reader.number("I"), wanted)
                if wanted:
                    if key in metadata and metadata[key] != value:
                        raise ValueError("Metadati GGUF incoerenti tra le parti")
                    metadata[key] = value
            for _ in range(tensor_count):
                tensor = reader.string(True, limit=4096)
                dimensions = reader.number("I")
                if not 1 <= dimensions <= 4:
                    raise ValueError("Dimensioni tensore GGUF non valide")
                for _ in range(dimensions):
                    if reader.number("Q") == 0:
                        raise ValueError("Dimensione tensore GGUF nulla")
                reader.number("I")  # GGML storage type: weights are not loaded.
                reader.number("Q")  # Tensor data offset: never followed.
                if re.fullmatch(r"blk\.\d+\.nextn\.eh_proj\.weight", tensor):
                    tensors.add(tensor)
    return metadata, tensors


def _model_support(signatures):
    try:
        metadata, tensors = _metadata_and_tensors(signatures)
    except ScanLimit:
        return {"model_supported": None, "architecture": None, "reason_code": "model_scan_limit",
                "reason": "Indice GGUF oltre il limite del controllo MTP; compatibilità non verificata."}
    except (OSError, ValueError, UnicodeError, struct.error):
        return {"model_supported": None, "architecture": None, "reason_code": "model_invalid",
                "reason": "Metadati GGUF non leggibili o incompleti; compatibilità MTP non verificata."}
    architecture = metadata.get("general.architecture")
    if not isinstance(architecture, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", architecture):
        return {"model_supported": None, "architecture": None, "reason_code": "model_architecture_unknown",
                "reason": "Architettura GGUF non disponibile; compatibilità MTP non verificata."}
    blocks, heads = metadata.get(architecture+".block_count"), metadata.get(architecture+".nextn_predict_layers")
    router = metadata.get(architecture+".router_layer", -1)
    if type(blocks) is not int or not 1 <= blocks <= MAX_RECORDS:
        return {"model_supported": None, "architecture": architecture, "reason_code": "model_layers_unknown",
                "reason": "Numero di blocchi GGUF non disponibile; compatibilità MTP non verificata."}
    supported = type(heads) is int and heads > 0 and heads <= blocks and f"blk.{blocks-1}.nextn.eh_proj.weight" in tensors
    if type(router) is int and router >= 0:
        supported = False
    return {"model_supported": supported, "architecture": architecture,
            "reason_code": "model_head_detected" if supported else "model_mtp_absent",
            "reason": ("Testa MTP integrata rilevata nei metadati e nei tensori GGUF; caricamento e memoria restano da verificare."
                       if supported else "Il GGUF non espone una testa MTP integrata utilizzabile: non basta il nome del modello.")}


def _live_options(help_text):
    blocks, current = [], []
    for line in help_text.splitlines():
        if line.lstrip().startswith("-") and re.search(r"--[a-z][a-z0-9-]*", line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return {flag: block for block in blocks if not re.search(r"\bREMOVED\b", block, re.I)
            for flag in re.findall(r"--[a-z][a-z0-9-]*", block.splitlines()[0])}


def _runtime_support(signature):
    executable = Path(signature[0])
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "timeout": 5,
              "check": False, "encoding": "utf-8", "errors": "replace", "cwd": str(executable.parent)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startup
    try:
        result = subprocess.run([str(executable), "--help"], **kwargs)
    except subprocess.TimeoutExpired:
        return {"runtime_supported": False, "spec_type": None, "predictions_flag": None,
                "reason_code": "runtime_timeout", "reason": "Il runtime non ha risposto al controllo MTP entro 5 secondi."}
    except OSError:
        return {"runtime_supported": False, "spec_type": None, "predictions_flag": None,
                "reason_code": "runtime_help_failed", "reason": "Non è possibile interrogare il runtime locale per MTP."}
    output = result.stdout or ""
    if result.returncode != 0 or len(output.encode("utf-8")) > MAX_HELP_BYTES:
        return {"runtime_supported": False, "spec_type": None, "predictions_flag": None,
                "reason_code": "runtime_help_failed", "reason": "Il runtime non ha restituito un elenco di opzioni utilizzabile."}
    options = _live_options(output)
    spec_help = options.get("--spec-type", "")
    spec = next((kind for kind in ("draft-mtp", "mtp") if re.search(r"(?<![\w-])"+kind+r"(?![\w-])", spec_help)), None)
    predictions = "--spec-draft-n-max" if "--spec-draft-n-max" in options else None
    supported = bool(spec and predictions)
    return {"runtime_supported": supported, "spec_type": spec, "predictions_flag": predictions,
            "reason_code": "runtime_mtp_available" if supported else "runtime_unsupported",
            "reason": "Il runtime espone MTP e il numero di predizioni." if supported else
                      "Questo runtime non espone opzioni MTP attive e configurabili; aggiorna llama.cpp."}


class MtpSupport:
    def __init__(self):
        self._runtime_cache, self._model_cache = {}, {}
        self._lock = threading.RLock()

    @staticmethod
    def _cache(cache, key, calculate, limit):
        if key not in cache:
            while len(cache) >= limit:
                del cache[next(iter(cache))]
            cache[key] = calculate()
        return cache[key]

    def probe(self, executable, model):
        with self._lock:
            try:
                key = _signature(executable)
                runtime = self._cache(self._runtime_cache, key, lambda: _runtime_support(key), 8)
            except (OSError, ValueError, TypeError):
                runtime = {"runtime_supported": False, "spec_type": None, "predictions_flag": None,
                           "reason_code": "runtime_missing", "reason": "Runtime locale non disponibile per il controllo MTP."}
            try:
                signatures = _model_signatures(model)
                details = self._cache(self._model_cache, signatures, lambda: _model_support(signatures), 32)
            except (OSError, ValueError, TypeError):
                details = {"model_supported": None, "architecture": None, "reason_code": "model_missing",
                           "reason": "Modello GGUF o una sua parte non disponibile; MTP non verificato."}
            supported = runtime["runtime_supported"] and details["model_supported"] is True
            reason = details if runtime["runtime_supported"] else runtime
            return copy.deepcopy({"supported": supported, "runtime_supported": runtime["runtime_supported"],
                "model_supported": details["model_supported"], "architecture": details["architecture"],
                "spec_type": runtime["spec_type"], "predictions_flag": runtime["predictions_flag"],
                "reason_code": "supported" if supported else reason["reason_code"], "reason": reason["reason"]})
