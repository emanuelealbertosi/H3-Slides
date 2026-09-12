"""Bounded, ephemeral image browser. Clients receive IDs, never fetchable URLs."""
import asyncio
import io
import json
import time
import warnings
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlencode, urlsplit

import aiohttp
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field

from .image_rights import openverse_candidate, source_license_evidence
from .openverse_images import API, MAX_PAGE_BYTES, ImageHTTPError
from .storage import uid
from .web_images import AGENT, MAX_IMAGE_BYTES, WIKIMEDIA_IMAGE_HOSTS, WebImages, open_license, plain
from .web_research import PublicResolver, public_url


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["web", "document"] = "web"
    include_pages: bool = False
    query: str = Field(default="", max_length=180)
    openverse: bool = False
    search_id: str = Field(default="", max_length=40)
    page: int = Field(default=0, ge=0, le=100000)


class ImageSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    search_id: str = Field(max_length=40)
    result_id: str = Field(max_length=40)
    revision: int = Field(ge=1)


@asynccontextmanager
async def public_session():
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    async with aiohttp.ClientSession(connector=connector, trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(), headers={"User-Agent": AGENT},
            timeout=aiohttp.ClientTimeout(total=15, connect=5)) as session:
        yield session


def commons_url(value, *, source=False):
    value = public_url(value)
    parts = urlsplit(value)
    allowed = {"commons.wikimedia.org"} if source else WIKIMEDIA_IMAGE_HOSTS
    if parts.scheme != "https" or parts.hostname not in allowed:
        raise ValueError("Destinazione immagine non Wikimedia")
    return value


def commons_result(title, info, query):
    meta = info.get("extmetadata", {})
    licence = plain(meta.get("LicenseShortName", {}).get("value"))
    if (not open_license(licence) or info.get("mime") not in ("image/jpeg", "image/png", "image/webp")
            or min(info.get("width", 0), info.get("height", 0)) < 300):
        return None
    try:
        url = commons_url(info.get("url", ""))
        preview = commons_url(info.get("thumburl") or url)
        source = commons_url(info.get("descriptionurl", ""), source=True)
    except ValueError:
        return None
    return {"label": plain(title.removeprefix("File:"), 180), "query": query,
            "source": source, "download_url": url, "preview": preview, "license": licence,
            "license_url": plain(meta.get("LicenseUrl", {}).get("value"), 500),
            "author": plain(meta.get("Artist", {}).get("value")), "image_provider": "Wikimedia Commons"}


class ImageSearch:
    ttl = 15 * 60

    def __init__(self):
        self.web = WebImages()
        self.searches = {}
        self.network = asyncio.Semaphore(4)

    def prune(self):
        now = time.monotonic()
        for key in list(self.searches):
            if self.searches[key]["expires"] < now:
                del self.searches[key]

    def lookup(self, pid, sid, ident):
        self.prune()
        state = self.searches.get(ident)
        if state is None or state["scope"] != (pid, sid):
            raise ValueError("Ricerca scaduta o non disponibile: premi Cerca per ripeterla")
        return state

    def result(self, pid, sid, search_id, result_id):
        state = self.lookup(pid, sid, search_id)
        if result_id not in state["results"]:
            raise KeyError()
        return state["results"][result_id]

    async def provider_page(self, session, state, provider):
        query = state["query"]
        if provider == "commons":
            data = await self.web.api(session, "commons.wikimedia.org", generator="search",
                gsrsearch=query+" filetype:bitmap", gsrnamespace=6, gsrlimit=10,
                prop="imageinfo", iiprop="url|extmetadata|mime|size", iiurlwidth=400,
                **(state["commons"] or {}))
            if "error" in data:
                raise ValueError("Wikimedia: ricerca non disponibile")
            pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 999))
            results = [commons_result(p.get("title", query), info, query)
                       for p in pages for info in p.get("imageinfo", [])[:1]]
            state[provider] = data.get("continue") or False
        else:
            raw, _, _ = await self.web.openverse.fetch(session, API+"?"+urlencode({
                "q": query, "license": "cc0,pdm,by,by-sa", "mature": "false",
                "page_size": 10, "page": state[provider]}), MAX_PAGE_BYTES, api=True)
            data = json.loads(raw)
            results = []
            for row in data.get("results", [])[:10]:
                candidate = openverse_candidate(row, query, manual_selection=True)
                if not candidate:
                    continue
                preview = candidate.get("thumbnail") or candidate["url"]
                try:
                    preview = public_url(preview)
                    if urlsplit(preview).scheme != "https":
                        continue
                except ValueError:
                    continue
                results.append({"label": candidate["title"], "query": query,
                    "source": candidate["foreign_landing_url"], "download_url": candidate["url"],
                    "preview": preview, "license": candidate["license_label"],
                    "license_url": candidate["license_url"], "author": candidate["author"],
                    "image_provider": "Openverse", "candidate": candidate})
            state[provider] = state[provider]+1 if data.get("next") else False
        return [r for r in results if r]

    async def search(self, pid, sid, request):
        if request.source != "web":
            raise ValueError("La ricerca nei documenti deve usare il catalogo locale")
        if request.page > 39:
            raise ValueError("Per altri risultati Internet avvia una nuova ricerca")
        self.prune()
        ident = request.search_id
        if not ident:
            query = " ".join(request.query.split())
            if len(query) < 2 or request.page:
                raise ValueError("Scrivi una ricerca di almeno 2 caratteri")
            # Bound metadata retained in RAM; no searches/assets are written to a project.
            while len(self.searches) >= 24:
                del self.searches[next(iter(self.searches))]
            ident = uid()
            self.searches[ident] = {"scope": (pid, sid), "expires": time.monotonic()+self.ttl,
                "query": query, "commons": {}, "openverse": 1 if request.openverse else False,
                "buffer": [], "seen": set(), "results": {}, "pages": [], "lock": asyncio.Lock()}
        state = self.lookup(pid, sid, ident)
        async with state["lock"]:
            if request.page < len(state["pages"]):
                return state["pages"][request.page]
            if request.page != len(state["pages"]):
                raise ValueError("Carica i risultati in ordine con Altro")
            messages = []
            async with self.network, public_session() as session:
                # Bounded attempts even when licences filter out an entire provider page.
                for _ in range(2):
                    if len(state["buffer"]) >= 10:
                        break
                    for provider in ("commons", "openverse"):
                        if state[provider] is False:
                            continue
                        try:
                            rows = await self.provider_page(session, state, provider)
                            for row in rows:
                                if row["download_url"] not in state["seen"]:
                                    state["seen"].add(row["download_url"])
                                    state["buffer"].append(row)
                        except (aiohttp.ClientError, ValueError, TimeoutError, OSError):
                            messages.append(("Wikimedia" if provider == "commons" else "Openverse")+
                                " non disponibile; premi Altro per riprovare oppure modifica la query.")
                    if messages:
                        break
            rows, state["buffer"] = state["buffer"][:10], state["buffer"][10:]
            public = []
            for row in rows:
                result_id = uid()
                state["results"][result_id] = row
                public.append({key: row[key] for key in ("label", "source", "license", "author", "image_provider")}
                              | {"id": result_id})
            more = request.page < 39 and bool(state["buffer"] or state["commons"] is not False or state["openverse"] is not False)
            page = {"search_id": ident, "page": request.page, "results": public, "has_more": more,
                    "message": " ".join(dict.fromkeys(messages))}
            state["pages"].append(page)
            return page

    async def preview(self, row):
        async with self.network, public_session() as session:
            if row["image_provider"] == "Wikimedia Commons":
                raw = await self.web.fetch(session, row["preview"], 4*1024*1024)
            else:
                try:
                    raw, _, _ = await self.web.openverse.fetch(session, row["preview"], 4*1024*1024)
                except ImageHTTPError as exc:
                    # Openverse's thumbnail proxy returns 424 when its upstream cache fails.
                    # Try the API-declared original only for missing/broken thumbnails,
                    # never for a refusal, authentication failure or rate limit.
                    if exc.status not in (404, 424, 502, 503) or row["preview"] == row["download_url"]:
                        raise
                    raw, _, _ = await self.web.openverse.fetch(session, row["download_url"], 8*1024*1024)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP") or image.width*image.height > 16_000_000:
                        raise ValueError("Anteprima non disponibile")
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.thumbnail((400, 300))
                    out = io.BytesIO()
                    image.save(out, format="JPEG", quality=80)
                    return out.getvalue()
        except (OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise ValueError("Anteprima non disponibile") from exc

    async def download(self, row):
        metadata = {key: value for key, value in row.items() if key not in ("preview", "candidate")}
        async with self.network, public_session() as session:
            if row["image_provider"] == "Wikimedia Commons":
                raw = await self.web.fetch(session, row["download_url"], MAX_IMAGE_BYTES)
            else:
                candidate = row["candidate"]
                page, final, mime = await self.web.openverse.fetch(session, row["source"], MAX_PAGE_BYTES)
                evidence = source_license_evidence(page, final, candidate) if mime in ("text/html", "application/xhtml+xml") else None
                if not evidence:
                    raise ValueError("Licenza non verificabile sulla fonte: scegli un'altra immagine")
                raw, final_image, mime = await self.web.openverse.fetch(session, row["download_url"], MAX_IMAGE_BYTES)
                if mime not in ("image/jpeg", "image/png", "image/webp"):
                    raise ValueError("Formato immagine non supportato")
                metadata.update(source=final, download_url=final_image, license_evidence=evidence,
                    openverse_id=candidate["id"], openverse_source=plain(candidate.get("source") or candidate.get("provider")))
        return raw, metadata
