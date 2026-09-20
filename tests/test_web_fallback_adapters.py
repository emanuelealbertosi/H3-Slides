"""Exercise real adapters and legacy/new request consent without external calls."""
import json
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from h3_slides import web_research as wr
from h3_slides.models import Generation, ProjectInput
from h3_slides.storage import Store
from h3_slides.worker import Worker


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path)
    yield value
    value.db.close()


@pytest.mark.asyncio
async def test_real_searxng_outage_advances_to_direct_wikipedia(store, monkeypatch):
    async def unavailable(_request):
        return web.Response(status=503, text="Service unavailable")
    app = web.Application()
    app.router.add_get("/search", unavailable)
    calls, events = [], []
    async def wikipedia(_session, language, **params):
        calls.append((language, params))
        if params.get("list") == "search":
            return {"query": {"search": [{"pageid": 1, "title": "Python"}]}}
        return {"query": {"pages": {"1": {"title": "Python", "extract": "Python è un linguaggio. " * 100,
            "fullurl": f"https://{language}.wikipedia.org/wiki/Python"}}}}
    monkeypatch.setattr(wr, "wikipedia_api", wikipedia)
    async def checkpoint():
        pass
    project = store.create(ProjectInput().model_dump())
    async with TestServer(app) as server:
        result = await wr.WebResearch(store).collect(project["id"], "Python", 3, False, events.append,
            checkpoint, provider="searxng", endpoint=str(server.make_url("")).rstrip("/"), fallback=True)
    assert result["provider_id"] == "wikipedia" and result["fallback_used"]
    assert result["requested_provider"] == "searxng" and result["sources"]
    assert result["fallback_attempts"][0]["status"] == "unavailable"
    assert calls and any("Ripiego gratuito: Wikipedia" in event for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (200, json.dumps({"results": [], "unresponsive_engines": [["engine", "CAPTCHA"]]})),
    (200, json.dumps({"results": [], "unresponsive_engines": [["engine", "access denied"]]})),
    (200, json.dumps({"results": [], "unresponsive_engines": [["engine", "unknown error"]]})),
    (503, "CAPTCHA required"), (503, "Access denied"), (429, "Too many requests"),
    (200, "not JSON"),
])
async def test_searxng_denials_or_invalid_responses_never_trigger_chain(store, monkeypatch, status, body):
    async def denied(_request):
        return web.Response(status=status, text=body)
    app = web.Application()
    app.router.add_get("/search", denied)
    async def unexpected(*args, **kwargs):
        pytest.fail("No direct provider may be used after a denial or invalid response")
    monkeypatch.setattr(wr, "wikipedia_api", unexpected)
    async def checkpoint():
        pass
    project = store.create(ProjectInput().model_dump())
    async with TestServer(app) as server:
        with pytest.raises(ValueError) as caught:
            await wr.WebResearch(store).collect(project["id"], "Python", 3, True, lambda _: None,
                checkpoint, provider="searxng", endpoint=str(server.make_url("")).rstrip("/"))
    assert not isinstance(caught.value, (wr.SearchUnavailable, wr.NoSearchResults))
    assert caught.value.fallback_attempts == [{"provider": "searxng", "status": "failed",
                                               "message": str(caught.value)[:350]}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,retryable", [
    (503, "Service unavailable", True), (503, "CAPTCHA required", False),
    (403, "Access denied", False), (429, "Limit", False), (200, "not JSON", False),
])
async def test_wikipedia_classifies_unavailability_separately(monkeypatch, status, body, retryable):
    async def reply(*args, **kwargs):
        return status, "text/html", body, "https://it.wikipedia.org/w/api.php"
    monkeypatch.setattr(wr, "bounded_get", reply)
    with pytest.raises(ValueError) as caught:
        await wr.wikipedia_api(None, "it", list="search", srsearch="Python")
    assert isinstance(caught.value, wr.SearchUnavailable) is retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
@pytest.mark.parametrize("preference", [True, False])
@pytest.mark.parametrize("extended_consent", [None, False, True])
async def test_worker_requires_extended_consent_and_snapshots_option(store, mode, preference, extended_consent):
    project = store.create(ProjectInput(web_enabled=True, web_provider="searxng",
        web_fallback=preference, web_query="Python").model_dump())
    worker = Worker(store, SimpleNamespace())
    captured = []
    async def run(_jid, _pid, _request, options):
        captured.append(options)
    worker.run = run
    values = {"provider": {"mode": mode, "model": "fake", "remote_consent": True},
              "prompt": "Spiega Python", "web_consent": True}
    if extended_consent is not None:
        values["web_fallback_consent"] = extended_consent
    request = Generation(**values)
    with pytest.raises(ValueError, match="Conferma"):
        worker.submit(project["id"], request.model_copy(update={"web_consent": False}))
    job = worker.submit(project["id"], request)
    changed = store.project(project["id"])
    changed["web_fallback"] = not preference
    store.save_project(changed)
    await worker.tasks[job["id"]]
    assert captured[0]["fallback"] is bool(preference and extended_consent)
    assert captured[0]["query"] == "Python"
    assert "provider" not in captured[0] or captured[0]["provider"] == "searxng"
