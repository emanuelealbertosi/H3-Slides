"""Public URL import contract; no external service or model is contacted."""
import asyncio
from pathlib import Path

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
import pytest

import h3_slides.app as app_module
from h3_slides.models import ProjectInput
from h3_slides import url_import, web_research


ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}
URL = "https://example.org/article"
TEXT = "Un documento pubblico con contenuti sufficienti per preparare una presentazione. " * 8


def source_fixture():
    return {"id": "url-source", "name": "Documento dal web", "kind": "url", "text": TEXT,
            "source_url": URL, "requested_url": URL, "images": [], "warnings": [], "retrieved_at": 100}


def test_url_request_normalizes_and_rejects_unknown_options():
    assert url_import.UrlSourceRequest(url="  https://example.org/article#part  ").url == URL
    with pytest.raises(ValueError):
        url_import.UrlSourceRequest(url=URL, headers={"Authorization": "not-supported"})


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["file:///document.txt", "http://localhost:8766/", "http://127.0.0.1/",
    "http://10.0.0.1/", "https://user:password@example.org/", "https://example.org:8766/", "http://printer.local/"])
async def test_url_import_rejects_non_public_targets_before_network(url, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid URLs must never create a network session")
    monkeypatch.setattr(url_import.aiohttp, "TCPConnector", forbidden)
    with pytest.raises(ValueError):
        await url_import.import_url(url)


@pytest.mark.asyncio
async def test_url_import_uses_existing_reader_and_safe_session(monkeypatch):
    async def bounded(session, url, **kwargs):
        assert url == URL
        assert not session.trust_env
        assert isinstance(session.cookie_jar, aiohttp.DummyCookieJar)
        assert isinstance(session.connector._resolver, web_research.PublicResolver)
        assert not session.connector._use_dns_cache
        assert kwargs["before_request"] is web_research.robots_allowed
        return 200, "text/html", f"<head><title>La fonte</title><script>ignored()</script></head><main><p>{TEXT}</p></main>", URL
    monkeypatch.setattr(web_research, "bounded_get", bounded)
    result = await url_import.import_url(URL)
    assert result["name"] == "La fonte"
    assert result["kind"] == "url" and result["source_url"] == URL
    assert result["requested_url"] == URL and result["retrieved_at"] > 0
    assert TEXT.strip() in result["text"] and "ignored" not in result["text"]
    assert not result["images"] and result["warnings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncio.TimeoutError(), aiohttp.ClientConnectionError(), OSError()])
async def test_url_network_errors_are_actionable(monkeypatch, error):
    async def unavailable(*args, **kwargs):
        raise error
    monkeypatch.setattr(url_import, "read_page", unavailable)
    with pytest.raises(ValueError, match="carica il documento"):
        await url_import.import_url(URL)


@pytest.mark.asyncio
async def test_unsupported_remote_pdf_is_not_interpreted_as_text(monkeypatch):
    async def bounded(*args, **kwargs):
        return 200, "application/pdf", "%PDF-1.7", URL
    monkeypatch.setattr(web_research, "bounded_get", bounded)
    with pytest.raises(ValueError, match="HTML/testo"):
        await url_import.import_url(URL)


@pytest.mark.asyncio
async def test_import_url_http_library_view_reuse_and_remove(tmp_path, monkeypatch):
    app = app_module.create_app(ROOT, tmp_path / "data")
    store = app["store"]
    project = store.create(ProjectInput(title="Importazione").model_dump())
    target = store.create(ProjectInput(title="Riuso").model_dump())
    calls = []
    async def acquire(url):
        calls.append(url)
        return source_fixture()
    monkeypatch.setattr(app_module, "import_url", acquire)
    base = f"/api/projects/{project['id']}/sources/url"
    async with TestClient(TestServer(app)) as client:
        response = await client.post(base, json={"url": URL})
        assert response.status == 403 and not calls
        response = await client.post(base, headers=HEADERS, json={"url": URL})
        assert response.status == 200, await response.text()
        result = await response.json()
        source = result["sources"][0]
        assert "text" not in source
        assert source["source_url"] == URL and source["library_id"] == source["id"]
        assert result["revision"] == project["revision"] + 1
        assert store.project(project["id"])["sources"][0]["text"] == TEXT
        documents = await (await client.get("/api/documents")).json()
        assert len(documents) == 1 and documents[0]["source_url"] == URL and documents[0]["viewable"]
        view = await client.get(f"/api/documents/{project['id']}/{source['id']}")
        assert view.status == 200 and await view.text() == TEXT
        duplicate = await client.post(base, headers=HEADERS, json={"url": URL + "#fragment"})
        assert duplicate.status == 400 and len(calls) == 1
        reused = await client.post(f"/api/projects/{target['id']}/sources/reuse", headers=HEADERS,
            json={"project_id": project["id"], "source_id": source["id"]})
        assert reused.status == 200, await reused.text()
        clone = (await reused.json())["sources"][0]
        assert clone["id"] != source["id"] and clone["library_id"] == source["id"]
        assert clone["source_url"] == URL
        documents = await (await client.get("/api/documents")).json()
        assert len(documents) == 1, "Reused page remains one logical document in upload history"
        removed = await client.delete(f"/api/projects/{project['id']}/sources/{source['id']}", headers=HEADERS)
        assert removed.status == 200
        assert store.project(target["id"])["sources"][0]["text"] == TEXT


@pytest.mark.asyncio
async def test_url_import_keeps_project_edits_made_during_download(tmp_path, monkeypatch):
    app = app_module.create_app(ROOT, tmp_path / "data")
    store = app["store"]
    project = store.create(ProjectInput(title="Prima").model_dump())
    async def acquire(url):
        changed = store.project(project["id"])
        changed["title"] = "Modificato durante download"
        store.save_project(changed)
        return source_fixture()
    monkeypatch.setattr(app_module, "import_url", acquire)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(f"/api/projects/{project['id']}/sources/url", headers=HEADERS, json={"url": URL})
        assert response.status == 200
        result = await response.json()
        assert result["title"] == "Modificato durante download" and len(result["sources"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("starts_during_fetch", [False, True])
async def test_url_import_respects_active_generation(tmp_path, monkeypatch, starts_during_fetch):
    app = app_module.create_app(ROOT, tmp_path / "data")
    store = app["store"]
    project = store.create(ProjectInput(title="Generazione").model_dump())
    state = {"active": not starts_during_fetch, "fetches": 0}
    monkeypatch.setattr(app["worker"], "active", lambda: state["active"])
    async def acquire(url):
        state.update(active=True, fetches=state["fetches"] + 1)
        return source_fixture()
    monkeypatch.setattr(app_module, "import_url", acquire)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(f"/api/projects/{project['id']}/sources/url", headers=HEADERS, json={"url": URL})
        assert response.status == 400
        assert not store.project(project["id"])["sources"]
        assert state["fetches"] == int(starts_during_fetch)


@pytest.mark.asyncio
async def test_workflow_routes_serve_app_on_reload(tmp_path):
    app = app_module.create_app(ROOT, tmp_path / "data")
    async with TestClient(TestServer(app)) as client:
        for route in ("/new", "/import", "/brief"):
            response = await client.get(route)
            assert response.status == 200 and response.content_type == "text/html"
