import io
from types import SimpleNamespace

import pytest
from PIL import Image

from h3_slides.web_images import WebImages


class Response:
    def __init__(self, status=200, location="", raw=b"image"):
        self.status, self.headers, self.raw = status, {"Location": location}, raw
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def raise_for_status(self):
        assert self.status == 200

    async def iter_chunked(self, _):
        yield self.raw


class Session:
    def __init__(self, *responses):
        self.responses, self.urls = list(responses), []

    def get(self, url, *, allow_redirects):
        assert allow_redirects is False
        self.urls.append(url)
        return self.responses.pop(0)


THUMB = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Example.jpg/1920px-Example.jpg"
UPLOAD = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Example.jpg"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [THUMB, UPLOAD])
async def test_official_thumbnail_and_original_hosts_are_accepted(url):
    session = Session(Response())
    assert await WebImages().fetch(session, url, 100) == b"image"
    assert session.urls == [url]


@pytest.mark.asyncio
async def test_redirect_to_new_official_thumbnail_host_is_accepted():
    session = Session(Response(302, THUMB), Response())
    assert await WebImages().fetch(session, UPLOAD, 100) == b"image"
    assert session.urls == [UPLOAD, THUMB]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://thumb.wikimedia.org.evil.example/image.jpg",
    "https://evil.thumb.wikimedia.org/image.jpg",
    "https://thumb.wikimedia.org@evil.example/image.jpg",
    "https://user:secret@thumb.wikimedia.org/image.jpg",
    "http://thumb.wikimedia.org/image.jpg",
    "https://127.0.0.1/image.jpg",
])
async def test_new_host_does_not_allow_lookalikes_credentials_or_private_redirects(url):
    session = Session(Response(302, url))
    with pytest.raises(ValueError):
        await WebImages().fetch(session, THUMB, 100)
    assert session.urls == [THUMB]


@pytest.mark.asyncio
async def test_thumbnail_response_remains_size_bounded():
    with pytest.raises(ValueError, match="troppo grande"):
        await WebImages().fetch(Session(Response(raw=b"12345")), THUMB, 4)


@pytest.mark.asyncio
async def test_new_host_download_preserves_attribution_and_skips_openverse(tmp_path, monkeypatch):
    finder, events = WebImages(), []
    raw = io.BytesIO()
    Image.new("RGB", (640, 400), "navy").save(raw, format="PNG")
    info = {"mime": "image/png", "width": 640, "height": 400,
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                            "Artist": {"value": "Photographer"}},
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example.jpg",
            "thumburl": THUMB}
    async def candidates(*_):
        return [("File:Example.jpg", info)]
    original_fetch = finder.fetch
    async def fetch(_session, url, limit):
        return await original_fetch(Session(Response(raw=raw.getvalue())), url, limit)
    async def forbidden(*_):
        pytest.fail("Openverse must not replace a successful Wikimedia download")
    monkeypatch.setattr(finder, "candidates", candidates)
    monkeypatch.setattr(finder, "fetch", fetch)
    monkeypatch.setattr(finder.openverse, "acquire", forbidden)
    store = SimpleNamespace(asset_path=lambda pid, name: tmp_path / name)
    asset = await finder.acquire(store, "fixture", "Example", True, events.append)
    assert asset["download_url"] == THUMB and asset["image_provider"] == "Wikimedia Commons"
    assert asset["author"] == "Photographer" and asset["license"] == "CC BY-SA 4.0"
    assert (tmp_path / asset["id"]).is_file()
    assert any("1 candidati" in event for event in events)


@pytest.mark.asyncio
async def test_download_failures_are_not_reported_only_as_no_results(monkeypatch):
    finder, events = WebImages(), []
    async def candidates(*_):
        return [("File:Blocked.jpg", {"mime": "image/jpeg", "width": 640, "height": 400,
            "extmetadata": {"LicenseShortName": {"value": "Public domain"}},
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Blocked.jpg",
            "thumburl": "https://untrusted.example/image.jpg"})]
    async def no_lead(*_):
        return []
    monkeypatch.setattr(finder, "candidates", candidates)
    monkeypatch.setattr(finder, "lead_image", no_lead)
    assert await finder.acquire(None, "fixture", "Example", False, events.append) is None
    assert any("candidato trovato ma download fallito" in event for event in events)
    assert any("1 download falliti" in event for event in events)
