"""Read an OpenAI-compatible model catalog without sending project contents."""
import asyncio
import json
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CATALOG_BYTES = 2 * 1024 * 1024
CATALOG_TIMEOUT = 15
MAX_MODELS = 2000


def remote_api_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlparse(value)
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment
                 and not any(c.isspace() or ord(c) < 32 for c in value))
        parsed.port  # Validate malformed or out-of-range ports too.
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("API remota: usa un URL HTTPS senza credenziali, query o frammenti")
    return value


class RemoteModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(default="", max_length=8192, repr=False)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        return remote_api_url(value)

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value):
        value = value.strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("La chiave API contiene caratteri non validi")
        return value


def normalize_catalog(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Il server non restituisce un elenco modelli compatibile (campo data). "
                         "Controlla la Base URL API oppure usa un ID manuale.")
    models = {}
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if (not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 512
                or any(ord(c) < 32 or ord(c) == 127 for c in model_id)):
            continue
        model_id = model_id.strip()
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            name = model_id
        models.setdefault(model_id, {"id": model_id, "name": name.strip()[:200]})
    if payload["data"] and not models:
        raise ValueError("Il catalogo del server non contiene identificativi di modello validi.")
    ordered = sorted(models.values(), key=lambda model: model["id"].casefold())
    return {"models": ordered[:MAX_MODELS], "truncated": len(ordered) > MAX_MODELS}


async def list_remote_models(settings: RemoteModelRequest):
    headers = {"Accept": "application/json"}
    if settings.api_key:
        headers["Authorization"] = "Bearer " + settings.api_key
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=CATALOG_TIMEOUT), trust_env=False
        ) as session:
            async with session.get(
                settings.base_url + "/models", headers=headers, allow_redirects=False
            ) as response:
                if response.status in (401, 403):
                    raise ValueError("Accesso al catalogo negato: inserisci o verifica la chiave API e i suoi permessi.")
                if response.status == 404:
                    raise ValueError("Elenco modelli non trovato: verifica la Base URL API "
                                     "(spesso termina con /v1), oppure usa un ID manuale.")
                if response.status == 429:
                    raise ValueError("Il server ha limitato le richieste al catalogo. Riprova tra poco.")
                if 300 <= response.status < 400:
                    raise ValueError("Il server reindirizza il catalogo: inserisci la Base URL API finale. "
                                     "La chiave non viene inoltrata a un altro indirizzo.")
                if response.status != 200:
                    raise ValueError(f"Catalogo modelli non disponibile (HTTP {response.status}). Riprova tra poco.")
                raw = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw) > MAX_CATALOG_BYTES:
                        raise ValueError("Il catalogo modelli supera il limite di 2 MB.")
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise ValueError("Il server non ha restituito JSON valido. Controlla la Base URL API.") from None
    except asyncio.TimeoutError:
        raise ValueError("Il server non ha risposto entro 15 secondi. Controlla la connessione e riprova.") from None
    except aiohttp.ClientError:
        # Do not include exception URLs, headers or provider error bodies.
        raise ValueError("Impossibile collegarsi al server API. Verifica URL, rete e certificato HTTPS.") from None
    return normalize_catalog(payload)
