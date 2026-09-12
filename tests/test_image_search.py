import copy
import io
import json
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from h3_slides.app import create_app
from h3_slides.image_search import ImageSearch, SearchRequest, commons_result
from h3_slides.image_rights import openverse_candidate
from h3_slides.models import ProjectInput, SlideContent

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


def info(index=0):
    return {"url": f"https://upload.wikimedia.org/{index}.jpg",
        "thumburl": f"https://thumb.wikimedia.org/{index}.jpg", "mime": "image/jpeg",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{index}.jpg",
        "width": 640, "height": 480, "extmetadata": {
            "LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<b>Author</b>"}}}


def png():
    out = io.BytesIO()
    Image.new("RGB", (640, 400), "navy").save(out, format="PNG")
    return out.getvalue()


def mock_commons(monkeypatch, finder, count=23):
    calls = []
    async def api(session, host, **params):
        assert host == "commons.wikimedia.org"
        calls.append(params)
        start = params.get("gsroffset", 0)
        data = {"query": {"pages": {str(i): {"title": f"File:Odysseus {i}", "index": i,
            "imageinfo": [info(i)]} for i in range(start, min(count, start+10))}}}
        if start+10 < count:
            data["continue"] = {"gsroffset": start+10, "continue": "gsroffset||"}
        return data
    monkeypatch.setattr(finder.web, "api", api)
    return calls


@pytest.mark.asyncio
async def test_ten_at_a_time_continuation_retry_scope_and_expiry(monkeypatch):
    finder = ImageSearch()
    calls = mock_commons(monkeypatch, finder)
    async def forbidden(*args, **kwargs):
        pytest.fail("Openverse must remain opt-in")
    monkeypatch.setattr(finder.web.openverse, "fetch", forbidden)
    first = await finder.search("p", "s", SearchRequest(query="Odysseus"))
    ident = first["search_id"]
    assert len(first["results"]) == 10 and first["has_more"]
    assert "download_url" not in first["results"][0]
    assert len(calls) == 1
    assert await finder.search("p", "s", SearchRequest(search_id=ident)) == first
    assert len(calls) == 1, "Retrying a page must not advance its cursor"
    second = await finder.search("p", "s", SearchRequest(search_id=ident, page=1))
    last = await finder.search("p", "s", SearchRequest(search_id=ident, page=2))
    assert len(second["results"]) == 10 and len(last["results"]) == 3 and not last["has_more"]
    assert len({r["id"] for page in (first, second, last) for r in page["results"]}) == 23
    with pytest.raises(ValueError):
        finder.result("another-project", "s", ident, first["results"][0]["id"])
    with pytest.raises(ValueError):
        finder.result("p", "another-slide", ident, first["results"][0]["id"])
    finder.searches[ident]["expires"] = time.monotonic()-1
    with pytest.raises(ValueError, match="scaduta"):
        finder.lookup("p", "s", ident)


def openverse_row():
    return {"id": "ov", "title": "Ulysses ancient painting", "creator": "Painter", "license": "by",
        "license_version": "4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "url": "https://images.example.org/painting.jpg",
        "foreign_landing_url": "https://museum.example.org/painting"}


@pytest.mark.asyncio
async def test_openverse_adds_to_commons_and_requires_source_licence(monkeypatch):
    finder = ImageSearch()
    calls = mock_commons(monkeypatch, finder, 1)
    row = openverse_row()
    assert openverse_candidate(row, "Odysseus") is None
    assert openverse_candidate(row, "Odysseus", manual_selection=True)
    assert openverse_candidate({**row, "license": "by-nc"}, "Odysseus", manual_selection=True) is None
    requests = []
    async def fetch(session, url, limit, **kwargs):
        requests.append(url)
        if kwargs.get("api"):
            return json.dumps({"results": [row], "next": None}).encode(), url, "application/json"
        return b"No licence", url, "text/html"
    monkeypatch.setattr(finder.web.openverse, "fetch", fetch)
    page = await finder.search("p", "s", SearchRequest(query="Odysseus", openverse=True))
    assert calls and len(requests) == 1
    assert [r["image_provider"] for r in page["results"]] == ["Wikimedia Commons", "Openverse"]
    chosen = finder.result("p", "s", page["search_id"], page["results"][1]["id"])
    with pytest.raises(ValueError, match="Licenza"):
        await finder.download(chosen)
    assert row["url"] not in requests, "No original downloaded when source licence is absent"


@pytest.mark.parametrize("change", [
    {"url": "https://127.0.0.1/a.jpg"}, {"thumburl": "https://evil.test/a.jpg"},
    {"descriptionurl": "https://evil.test/wiki/File:a.jpg"}, {"mime": "image/svg+xml"},
    {"width": 20}, {"extmetadata": {"LicenseShortName": {"value": "CC BY-NC 4.0"}}},
])
def test_invalid_candidates_never_reach_browser(change):
    assert commons_result("File:Test", {**info(), **change}, "test") is None


@pytest.mark.asyncio
async def test_preview_decodes_reencodes_and_never_saves(monkeypatch):
    finder = ImageSearch()
    async def fetch(*args): return png()
    monkeypatch.setattr(finder.web, "fetch", fetch)
    raw = await finder.preview(commons_result("File:Test", info(), "test"))
    image = Image.open(io.BytesIO(raw))
    assert image.format == "JPEG" and image.width <= 400 and image.height <= 300


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_selection_preserves_slide_and_checks_revision_after_network(tmp_path, monkeypatch, changed):
    app = create_app(ROOT, tmp_path / "data")
    store, finder = app["store"], app["image_search"]
    p = store.create(ProjectInput(title="Immagini", prompt="Test", count=1).model_dump())
    content = SlideContent(title="Titolo intatto", bullets=["Testo intatto"], image_placeholder=True,
        image_query="Odysseus", layout="freeform", freeform={"visual": {"x": 600, "y": 200, "w": 500, "h": 400}}).model_dump()
    p["slides"] = [{"id": "slide-test", "revision": 1, "status": "ready", "content": content,
                    "diagram_render": {"asset": "keep-render.png"}}]
    store.save_project(p)
    mock_commons(monkeypatch, finder, 1)
    async def download(row):
        if changed:
            latest = store.project(p["id"])
            latest["slides"][0]["revision"] = 2
            latest["slides"][0]["content"]["title"] = "Modifica concorrente"
            store.save_project(latest)
        return png(), {k: v for k, v in row.items() if k != "preview"}
    monkeypatch.setattr(finder, "download", download)
    async with TestClient(TestServer(app)) as client:
        base = f"/api/projects/{p['id']}/slides/slide-test/image-search"
        assert (await client.post(base, json={"query": "Odysseus"})).status == 403
        response = await client.post(base, json={"query": "Odysseus"}, headers=HEADERS)
        assert response.status == 200
        page = await response.json()
        assert store.project(p["id"])["slides"] == p["slides"]
        payload = {"search_id": page["search_id"], "result_id": page["results"][0]["id"], "revision": 1}
        invalid = await client.post(base+"/select", json={**payload, "url": "https://localhost/"}, headers=HEADERS)
        assert invalid.status == 400
        response = await client.post(base+"/select", json=payload, headers=HEADERS)
        saved = store.project(p["id"])
        if changed:
            assert response.status == 409
            assert saved["slides"][0]["content"]["title"] == "Modifica concorrente"
            assert not saved.get("visual_assets")
            assert not list((store.root / "assets" / p["id"]).glob("*.jpg"))
        else:
            assert response.status == 200, await response.text()
            item = saved["slides"][0]
            assert item["revision"] == 2 and item["diagram_render"] == p["slides"][0]["diagram_render"]
            for key in content:
                if key not in ("image_id", "image_origin", "image_placeholder"):
                    assert item["content"][key] == content[key]
            asset = saved["visual_assets"][0]
            assert asset["source"].startswith("https://commons.") and asset["license"] == "CC BY-SA 4.0"
            assert store.asset_path(p["id"], asset["id"]).exists()
            assert (await client.post(base+"/select", json=payload, headers=HEADERS)).status == 409
