"""Opt-in anonymous Openverse images with source-specific licence verification."""
import asyncio
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urljoin, urlsplit

import aiohttp

from .image_rights import openverse_candidate, source_license_evidence
from .web_research import PublicResolver, public_url

API = "https://api.openverse.org/v1/images/"
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_RESULTS = 20
MAX_SOURCE_PAGES = 3
AGENT = "H3-Slides/0.2 (https://github.com/emanuelealbertosi/H3-Slides)"


class ImageHTTPError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Fonte immagini HTTP {status}")


def retry_delay(value):
    """Respect Retry-After (seconds or HTTP date), without retrying in this call."""
    try:
        return max(60, int(value))
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(60, (date - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 3600


class OpenverseImages:
    def __init__(self):
        # Keep refusal/rate-limit state across slides; no token, proxy or paid fallback.
        self.blocked_until = {}

    async def fetch(self, session, url, limit, *, api=False):
        for _ in range(4):
            url = public_url(url)
            parts = urlsplit(url)
            host = parts.hostname.lower().rstrip(".")
            if parts.scheme != "https":
                raise ValueError("Le fonti immagini Openverse devono usare HTTPS")
            if api and (parts.hostname != "api.openverse.org" or parts.path != "/v1/images/"):
                raise ValueError("Destinazione API Openverse non consentita")
            if self.blocked_until.get(host, 0) > time.monotonic():
                raise ValueError("Fonte immagini temporaneamente sospesa: rispetto del limite o rifiuto del servizio")
            async with session.get(url, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Redirect immagini senza destinazione")
                    url = urljoin(url, location)
                    continue
                if response.status in (401, 403, 429):
                    self.blocked_until[host] = time.monotonic() + retry_delay(
                        response.headers.get("Retry-After"))
                if response.status != 200:
                    raise ImageHTTPError(response.status)
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > limit:
                    raise ValueError("Risposta immagini troppo grande")
                data = bytearray()
                async for chunk in response.content.iter_chunked(32768):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ValueError("Risposta immagini troppo grande")
                return bytes(data), url, response.content_type
        raise ValueError("Troppi reindirizzamenti immagini")

    async def acquire(self, store, pid, query, event=None):
        from .web_images import MAX_IMAGE_BYTES, plain, store_image
        event = event or (lambda _: None)
        query = " ".join(query.split())[:180]
        if not query:
            return None
        if self.blocked_until.get("api.openverse.org", 0) > time.monotonic():
            event("Openverse temporaneamente sospeso dopo un limite o rifiuto del servizio")
            return None
        async with asyncio.timeout(35):
            connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
            async with aiohttp.ClientSession(connector=connector, trust_env=False,
                    cookie_jar=aiohttp.DummyCookieJar(), headers={"User-Agent": AGENT},
                    timeout=aiohttp.ClientTimeout(total=12, connect=5)) as session:
                event("Ricerca Openverse · " + query)
                try:
                    raw, _, _ = await self.fetch(session, API + "?" + urlencode({
                        "q": query, "license": "cc0,pdm,by,by-sa", "page_size": MAX_RESULTS,
                        "mature": "false"}), MAX_PAGE_BYTES, api=True)
                    data = json.loads(raw)
                except (ValueError, aiohttp.ClientError, OSError, TimeoutError):
                    event("Openverse non disponibile; nessun nuovo tentativo su questo servizio")
                    return None
                rows = data.get("results", []) if isinstance(data, dict) else []
                if not isinstance(rows, list):
                    return None
                candidates, seen = [], set()
                for row in rows[:MAX_RESULTS]:
                    candidate = openverse_candidate(row, query)
                    if not candidate or candidate["url"] in seen:
                        continue
                    seen.add(candidate["url"])
                    candidates.append(candidate)
                for candidate in candidates[:MAX_SOURCE_PAGES]:
                    try:
                        page, final_url, mime = await self.fetch(
                            session, candidate["foreign_landing_url"], MAX_PAGE_BYTES)
                        if mime not in ("text/html", "application/xhtml+xml"):
                            continue
                        evidence = source_license_evidence(page, final_url, candidate)
                        if not evidence:
                            continue
                        raw, image_url, mime = await self.fetch(session, candidate["url"], MAX_IMAGE_BYTES)
                        if mime not in ("image/jpeg", "image/png", "image/webp"):
                            continue
                        return store_image(store, pid, raw, candidate["title"], origin="web",
                            query=query, source=final_url, download_url=image_url,
                            license=candidate["license_label"], license_url=candidate["license_url"],
                            author=candidate["author"], image_provider="Openverse",
                            openverse_id=candidate["id"],
                            openverse_source=plain(candidate.get("source") or candidate.get("provider")),
                            license_evidence=evidence)
                    except (ValueError, aiohttp.ClientError, OSError, TimeoutError):
                        continue
                event("Openverse: nessuna immagine pertinente con licenza verificabile sulla fonte")
        return None
