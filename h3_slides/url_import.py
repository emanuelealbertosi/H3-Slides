"""Explicit import of a public HTML/text page, using the web reader's safeguards."""
import asyncio
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .storage import uid
from .web_research import AGENT, PublicResolver, public_url, read_page


class UrlSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=3000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        return public_url(value.strip())


async def import_url(url):
    """Fetch only the chosen page: no scripts, images, search, credentials or LLM."""
    url = public_url(url)
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    try:
        async with aiohttp.ClientSession(
            connector=connector, trust_env=False, cookie_jar=aiohttp.DummyCookieJar(),
            headers={"User-Agent": AGENT}, timeout=aiohttp.ClientTimeout(total=18, connect=7),
        ) as session:
            page = await read_page(session, {"url": url, "title": urlsplit(url).hostname})
    except asyncio.TimeoutError as exc:
        raise ValueError("Il sito non ha risposto in tempo. Riprova o carica il documento dal computer.") from exc
    except (aiohttp.ClientError, OSError) as exc:
        raise ValueError("Pagina non raggiungibile: usa un link pubblico o carica il documento dal computer.") from exc
    warnings = ["Importato il testo della pagina; immagini, allegati e contenuti interattivi non sono inclusi."]
    if page.get("truncated"):
        warnings.append("Testo limitato a 240.000 caratteri: verifica che la sezione desiderata sia presente.")
    return {
        "id": uid(), "name": page["title"], "kind": "url", "text": page["text"],
        "images": [], "warnings": warnings, "source_url": page["url"],
        "requested_url": url, "retrieved_at": page["retrieved_at"],
    }
