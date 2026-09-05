import asyncio
import io
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from h3_slides.models import ProjectInput
from h3_slides.openverse_images import OpenverseImages, API, MAX_SOURCE_PAGES, ImageHTTPError, retry_delay
from h3_slides.storage import Store
from h3_slides.web_images import WebImages


@pytest.fixture
def store(tmp_path):
    db = Store(tmp_path)
    yield db
    db.db.close()


def candidate(**changes):
    return dict({"id": "test-image", "title": "Eiffel Tower", "creator": "<b>Photographer</b>",
        "license": "by", "license_version": "4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "url": "https://images.example.org/tower.jpg",
        "foreign_landing_url": "https://museum.example.org/tower",
        "source": "museum", "mature": False, "width": 640, "height": 480}, **changes)


def original_page(row):
    obj = {"@context": "https://schema.org", "@type": "ImageObject", "name": row["title"],
           "contentUrl": row["url"], "license": row["license_url"]}
    return ('<script type="application/ld+json">' + json.dumps(obj) + '</script>').encode()


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), "navy").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,commons", [(False, False), (False, True), (True, True), (True, False)])
async def test_openverse_is_strict_opt_in_after_commons(store, monkeypatch, enabled, commons):
    p = store.create(ProjectInput().model_dump())
    assert not p["use_openverse_images"]
    search, calls = WebImages(), []
    async def first(*_):
        calls.append("commons")
        return {"id": "commons.jpg"} if commons else None
    async def second(*_):
        calls.append("openverse")
        return {"id": "openverse.jpg"}
    monkeypatch.setattr(search, "acquire_commons", first)
    monkeypatch.setattr(search.openverse, "acquire", second)
    result = await search.acquire(store, p["id"], "Eiffel Tower", enabled)
    assert calls == (["commons", "openverse"] if enabled and not commons else ["commons"])
    assert result == ({"id": "commons.jpg"} if commons else {"id": "openverse.jpg"} if enabled else None)


@pytest.mark.asyncio
async def test_openverse_source_verified_download_and_credits(store, monkeypatch):
    p = store.create(ProjectInput().model_dump())
    finder, row, calls = OpenverseImages(), candidate(), []
    async def fetch(session, url, limit, *, api=False):
        calls.append(url)
        if api:
            parsed = parse_qs(urlsplit(url).query)
            assert url.startswith(API) and parsed["q"] == ["Eiffel Tower"]
            assert parsed["license"] == ["cc0,pdm,by,by-sa"] and parsed["mature"] == ["false"]
            assert parsed["page_size"] == ["20"]
            return json.dumps({"results": [candidate(license="by-nc"), row]}).encode(), url, "application/json"
        if url == row["foreign_landing_url"]:
            return original_page(row), url, "text/html"
        assert url == row["url"]
        return png(), url, "image/png"
    monkeypatch.setattr(finder, "fetch", fetch)
    result = await finder.acquire(store, p["id"], "Eiffel Tower")
    assert len(calls) == 3 and result["image_provider"] == "Openverse"
    assert result["author"] == "Photographer" and result["license"] == "CC BY 4.0"
    assert result["source"] == row["foreign_landing_url"]
    assert result["license_evidence"]["method"] == "jsonld_imageobject"
    assert result["openverse_id"] == row["id"]
    assert Image.open(store.asset_path(p["id"], result["id"])).format == "JPEG"
    assert store.project(p["id"])["sources"] == []  # Illustration, never factual document evidence.


@pytest.mark.asyncio
async def test_no_source_evidence_never_downloads_bitmap_and_bounds_checks(store, monkeypatch):
    p = store.create(ProjectInput().model_dump())
    finder, calls = OpenverseImages(), []
    rows = [candidate(id=str(i), url=f"https://images.example.org/{i}.jpg",
                      foreign_landing_url=f"https://museum.example.org/{i}") for i in range(30)]
    async def fetch(session, url, limit, *, api=False):
        calls.append(url)
        if api:
            return json.dumps({"results": rows}).encode(), url, "application/json"
        assert url.startswith("https://museum.example.org/")
        return b'<footer><a rel="license">CC BY 4.0</a></footer>', url, "text/html"
    monkeypatch.setattr(finder, "fetch", fetch)
    assert await finder.acquire(store, p["id"], "Eiffel Tower") is None
    assert len(calls) == 1 + MAX_SOURCE_PAGES


class Response:
    def __init__(self, status=200, body=b"data", headers=None, mime="image/png"):
        self.status, self.body = status, body
        self.headers, self.content_type = headers or {}, mime
        self.content = self
    async def iter_chunked(self, _):
        yield self.body
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass


class Session:
    def __init__(self, *responses):
        self.responses, self.urls = list(responses), []
    def get(self, url, **kwargs):
        assert kwargs == {"allow_redirects": False}
        self.urls.append(url)
        return self.responses.pop(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", [
    "http://example.org/image", "https://127.0.0.1/image", "https://[::1]/image",
    "https://service.local/image", "https://user:pass@example.org/image",
    "https://example.org:8888/image"])
async def test_initial_and_redirect_destinations_are_checked(destination):
    finder = OpenverseImages()
    with pytest.raises(ValueError):
        await finder.fetch(None, destination, 100)
    session = Session(Response(302, headers={"Location": destination}))
    with pytest.raises(ValueError):
        await finder.fetch(session, "https://museum.example.org/image", 100)
    assert len(session.urls) == 1


@pytest.mark.asyncio
async def test_api_redirect_must_stay_on_openverse_search_endpoint():
    session = Session(Response(302, headers={"Location": "https://other.example.org/"}))
    with pytest.raises(ValueError):
        await OpenverseImages().fetch(session, API, 100, api=True)
    assert session.urls == [API]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [Response(body=b"x"*101), Response(headers={"Content-Length": "101"})])
async def test_stream_and_announced_size_are_bounded(response):
    with pytest.raises(ValueError, match="grande"):
        await OpenverseImages().fetch(Session(response), "https://museum.example.org/page", 100)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429])
async def test_service_denial_is_remembered_across_slides(store, monkeypatch, status):
    finder = OpenverseImages()
    session = Session(Response(status, headers={"Retry-After": "7200"}))
    before = time.monotonic()
    with pytest.raises(ImageHTTPError):
        await finder.fetch(session, API, 1000, api=True)
    assert finder.blocked_until["api.openverse.org"] >= before + 7200
    with pytest.raises(ValueError, match="sospesa"):
        await finder.fetch(session, API, 1000, api=True)
    p = store.create(ProjectInput().model_dump())
    assert await finder.acquire(store, p["id"], "Eiffel Tower") is None
    assert session.urls == [API]
    assert retry_delay(None) == 3600


@pytest.mark.asyncio
async def test_equivalent_dns_hostname_cannot_skip_source_cooldown():
    finder = OpenverseImages()
    session = Session(Response(429, headers={"Retry-After": "60"}))
    with pytest.raises(ImageHTTPError):
        await finder.fetch(session, "https://museum.example.org./image", 100)
    with pytest.raises(ValueError, match="sospesa"):
        await finder.fetch(session, "https://museum.example.org/image", 100)
    assert len(session.urls) == 1


@pytest.mark.asyncio
async def test_cancellation_is_not_hidden_as_missing_image(store, monkeypatch):
    finder, p = OpenverseImages(), store.create(ProjectInput().model_dump())
    async def cancel(*_, **__): raise asyncio.CancelledError
    monkeypatch.setattr(finder, "fetch", cancel)
    with pytest.raises(asyncio.CancelledError):
        await finder.acquire(store, p["id"], "Eiffel Tower")


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b"invalid json", b"[]", b'{"results": 123}', b'{"results": []}'])
async def test_unusable_api_response_is_optional(store, monkeypatch, raw):
    finder, p = OpenverseImages(), store.create(ProjectInput().model_dump())
    async def fetch(session, url, limit, *, api=False):
        assert api
        return raw, url, "application/json"
    monkeypatch.setattr(finder, "fetch", fetch)
    assert await finder.acquire(store, p["id"], "Eiffel Tower") is None
