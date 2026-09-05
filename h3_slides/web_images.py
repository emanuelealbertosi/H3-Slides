"""Optional Wikimedia/Openverse images, downloaded locally with attribution.

Uses the Wikipedia -> Commons metadata -> licensed download approach of
H3-Documentary (pipeline/engine/acquire.py); no paid providers or API keys.
"""
import asyncio
import io
import json
import re
import warnings
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

import aiohttp
from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import uid
from .web_research import PublicResolver, public_url

MAX_IMAGE_BYTES = 20 * 1024 * 1024
AGENT = "H3-Slides/0.2 (https://github.com/emanuelealbertosi/H3-Slides)"
# Wikimedia now advertises thumbnails on a separate official host.
# Keep exact hosts (not a wildcard) and validate every redirect as before.
WIKIMEDIA_IMAGE_HOSTS = frozenset({"commons.wikimedia.org", "upload.wikimedia.org",
    "thumb.wikimedia.org", "it.wikipedia.org", "en.wikipedia.org"})


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)


def plain(value, limit=400):
    parser = PlainText()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())[:limit]


def open_license(value):
    name = plain(value).casefold().strip()
    return bool(name in ("public domain", "cc0", "cc0 1.0", "cc0-1.0") or
                re.fullmatch(r"cc[ -]by(?:[ -]sa)?(?:[ -]\d+(?:\.\d+)?)?", name))


def store_image(store, pid, raw, label, origin="upload", **metadata):
    """Decode and re-encode a still image; paths and MIME never come from a URL."""
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Usa un'immagine fino a 20 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ("JPEG", "PNG", "WEBP"):
                    raise ValueError("Formati supportati: JPG, PNG e WebP")
                if image.width*image.height > 32_000_000 or getattr(image, "n_frames", 1) > 1:
                    raise ValueError("Usa un'immagine fissa fino a 32 megapixel")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                name = uid()+".jpg"
                image.save(store.asset_path(pid, name), quality=92)
                return {"id": name, "label": plain(label, 180), "origin": origin,
                        "width": image.width, "height": image.height, **metadata}
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Immagine non valida o troppo grande") from exc


class WebImages:
    def __init__(self):
        from .openverse_images import OpenverseImages
        self.openverse = OpenverseImages()

    async def fetch(self, session, url, limit):
        for _ in range(4):
            url = public_url(url)
            if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in WIKIMEDIA_IMAGE_HOSTS:
                raise ValueError("Destinazione immagine non Wikimedia")
            async with session.get(url, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.content.iter_chunked(32768):
                    data.extend(chunk)
                    if len(data) > limit:
                        raise ValueError("Risposta immagini troppo grande")
                return bytes(data)
        raise ValueError("Troppi reindirizzamenti immagini")

    async def api(self, session, host, **params):
        raw = await self.fetch(session, "https://"+host+"/w/api.php?"+urlencode(
            {"action":"query", "format":"json", **params}), 1_500_000)
        return json.loads(raw)

    async def candidates(self, session, query):
        # Direct Commons search works for general topics, not only portraits.
        result = await self.api(session, "commons.wikimedia.org", generator="search",
                                gsrsearch=query+" filetype:bitmap", gsrnamespace=6, gsrlimit=5,
                                prop="imageinfo", iiprop="url|extmetadata|mime|size", iiurlwidth=1600)
        pages = sorted(result.get("query", {}).get("pages", {}).values(),
                       key=lambda page: page.get("index", 999))
        return [(page.get("title", query), info) for page in pages
                for info in page.get("imageinfo", [])[:1]]

    async def lead_image(self, session, query):
        # Same optional Wikipedia lead-image fallback as H3-Documentary.
        for language in ("it", "en"):
            page = await self.api(session, language+".wikipedia.org", titles=query,
                                  prop="pageimages", redirects=1)
            filename = next((p.get("pageimage") for p in page.get("query", {}).get("pages", {}).values()
                             if p.get("pageimage")), None)
            if filename:
                result = await self.api(session, "commons.wikimedia.org", titles="File:"+filename,
                                       prop="imageinfo", iiprop="url|extmetadata|mime|size", iiurlwidth=1600)
                return [(filename, info) for p in result.get("query", {}).get("pages", {}).values()
                        for info in p.get("imageinfo", [])[:1]]
        return []

    async def acquire(self, store, pid, query, use_openverse=False, event=None):
        """Openverse is contacted only after Wikimedia and only by explicit opt-in."""
        try:
            asset = await self.acquire_commons(store, pid, query, event)
            if asset:
                return asset
        except (ValueError, aiohttp.ClientError, OSError, TimeoutError):
            if not use_openverse:
                raise
            if event:
                event("Wikimedia non disponibile; estensione Openverse abilitata")
        if use_openverse:
            return await self.openverse.acquire(store, pid, query, event)
        return None

    async def acquire_commons(self, store, pid, query, event=None):
        event = event or (lambda _: None)
        query = " ".join(query.split())[:180]
        if not query:
            return None
        async with asyncio.timeout(35):
            connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
            async with aiohttp.ClientSession(connector=connector, trust_env=False,
                    cookie_jar=aiohttp.DummyCookieJar(),
                    headers={"User-Agent":AGENT}, timeout=aiohttp.ClientTimeout(total=12)) as session:
                candidates = await self.candidates(session, query)
                event(f"Wikimedia Commons: {len(candidates)} candidati per la query")
                rejected, downloads_failed = 0, 0
                for batch in (candidates, None):
                    if batch is None:
                        batch = await self.lead_image(session, query)
                        event(f"Wikipedia: {len(batch)} immagini dalla voce cercata")
                    for title, info in batch:
                        meta = info.get("extmetadata", {})
                        licence = plain(meta.get("LicenseShortName", {}).get("value"))
                        if not open_license(licence) or info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
                            rejected += 1
                            continue
                        if min(info.get("width", 0), info.get("height", 0)) < 300:
                            rejected += 1
                            continue
                        source = info.get("descriptionurl", "")
                        image_url = info.get("thumburl") or info.get("url", "")
                        try:
                            source = public_url(source)
                            if urlsplit(source).scheme != "https" or urlsplit(source).hostname != "commons.wikimedia.org":
                                rejected += 1
                                continue
                            raw = await self.fetch(session, image_url, MAX_IMAGE_BYTES)
                            return store_image(store, pid, raw, title.removeprefix("File:"), origin="web",
                                query=query, source=source, download_url=image_url, license=licence,
                                license_url=plain(meta.get("LicenseUrl", {}).get("value"), 500),
                                author=plain(meta.get("Artist", {}).get("value")), image_provider="Wikimedia Commons")
                        except (ValueError, aiohttp.ClientError, TimeoutError) as exc:
                            downloads_failed += 1
                            reason = (f"HTTP {exc.status}" if isinstance(exc, aiohttp.ClientResponseError) else
                                      "tempo esaurito" if isinstance(exc, TimeoutError) else
                                      "destinazione o immagine non valida" if isinstance(exc, ValueError) else
                                      "errore di connessione")
                            event("Wikimedia: candidato trovato ma download fallito · " + reason)
                            continue
                if rejected or downloads_failed:
                    event(f"Wikimedia: {rejected} candidati esclusi per licenza/formato/dimensioni; "
                          f"{downloads_failed} download falliti")
        return None
