import asyncio
import json
import socket
import time
from types import SimpleNamespace
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest
from h3_slides.models import ProjectInput, Generation, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker
from h3_slides.search_settings import SearchSettings
from h3_slides import web_research as wr


@pytest.fixture
def store(tmp_path):
    db = Store(tmp_path)
    yield db
    db.db.close()


def bundle():
    return {"provider":"Fixture SearXNG", "query":"Python", "created_at":time.time(),
            "sources":[{"id":"W1", "title":"Python tutorial", "url":"https://docs.python.org/3/tutorial/",
                        "text":"Python tutorial: interprete, tipi e funzioni. "*100,
                        "retrieved_at":time.time()}], "warnings":[], "cache_used":False}


@pytest.mark.parametrize("url", ["file:///tmp/test", "http://localhost/x", "http://127.0.0.1/",
    "http://10.1.1.1/", "http://169.254.169.254/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
    "http://user:pass@example.com/", "https://example.com:1234/", "http://printer.local/",
    "http://example.com\\@localhost/", "http://[fc00::1]/"])
def test_private_urls_rejected(url):
    with pytest.raises(ValueError):
        wr.public_url(url)


def test_public_ipv6_and_local_engine_config():
    assert wr.public_url("https://[2606:4700:4700::1111]/")
    assert SearchSettings(searxng_url="http://127.0.0.1:9999/").searxng_url.endswith(":9999")
    for url in ["https://external.example/", "http://127.0.0.1/private", "http://user@localhost:8080", "http://localhost:0"]:
        with pytest.raises(ValueError):
            SearchSettings(searxng_url=url)


@pytest.mark.asyncio
async def test_dns_rebinding_rejected(monkeypatch):
    resolver = wr.PublicResolver()
    async def private(*_):
        return [{"host":"127.0.0.1", "port":80, "family":socket.AF_INET}]
    monkeypatch.setattr(resolver.inner, "resolve", private)
    with pytest.raises(OSError, match="pubblica"):
        await resolver.resolve("apparently-public.example", 80)
    await resolver.close()


def test_html_and_result_extraction():
    p = wr.TextExtractor()
    p.feed("<head><title>Fonte</title><script>STEAL</script></head><nav>MENU</nav><main><p>"+
           "Informazione utile. "*20+"</p><div hidden>HIDDEN</div></main><footer>FOOTER</footer>")
    text, title = p.result()
    assert title == "Fonte" and "Informazione" in text
    assert not any(s in text for s in ["STEAL", "MENU", "HIDDEN", "FOOTER"])
    results = wr.SearchResults()
    results.feed('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Test</a>'+
                 '<a class="result__a" href="http://127.0.0.1/">Private</a>')
    assert results.results == [{"url":"https://example.com/page", "title":"Test"}]


@pytest.mark.asyncio
async def test_searxng_json_adapter_and_query_only(store):
    queries = []
    async def search(request):
        queries.append(dict(request.query))
        return web.json_response({"results":[{"url":"https://docs.python.org/3/", "title":"Python"},
                                             {"url":"http://127.0.0.1/private", "title":"Private"}]})
    app = web.Application()
    app.router.add_get("/search", search)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        results = await wr.WebResearch(store).search(session, "Python", "searxng", str(server.make_url("")).rstrip("/"))
    assert len(results) == 1
    assert queries[0] == {"q":"Python", "format":"json", "categories":"general", "language":"it", "safesearch":"1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 403, 429])
async def test_local_engine_never_follows_redirect_or_bypasses_denial(store, status):
    async def search(_):
        return web.Response(status=status, headers={"Location":"http://127.0.0.1/private"})
    app = web.Application()
    app.router.add_get("/search", search)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        with pytest.raises(ValueError):
            await wr.WebResearch(store).search(session, "Python", "searxng", str(server.make_url("")).rstrip("/"))


@pytest.mark.asyncio
async def test_ddg_captcha_is_terminal(store, monkeypatch):
    async def denied(*_, **__):
        return 202, "text/html", "anomaly.js", wr.SEARCH_URL
    monkeypatch.setattr(wr, "bounded_get", denied)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(ValueError, match="CAPTCHA"):
            await wr.WebResearch(store).search(session, "Python", "duckduckgo", "")


@pytest.mark.asyncio
async def test_cache_refresh_and_no_readable_results(store, monkeypatch):
    p = store.create(ProjectInput().model_dump())
    r = wr.WebResearch(store)
    calls = []
    async def search(*_):
        calls.append(1)
        return [{"title":"Python", "url":f"https://example.com/{i}"} for i in range(3)]
    async def read(_, candidate):
        return {**candidate, "text":"Python tutorial. "*30, "retrieved_at":time.time()}
    async def checkpoint(): pass
    monkeypatch.setattr(r, "search", search)
    monkeypatch.setattr(wr, "read_page", read)
    args = (p["id"], "Python", 3, False, lambda _:None, checkpoint, "searxng")
    first = await r.collect(*args)
    second = await r.collect(*args)
    assert len(calls) == 1 and second["cache_used"]
    assert len(first["sources"]) == 3 and "text" not in wr.public_research(first)["sources"][0]
    await r.collect(p["id"], "Python", 3, True, lambda _:None, checkpoint, provider="searxng")
    assert len(calls) == 2
    for cache in store.root.rglob("web-*.json"):
        data = json.loads(cache.read_text())
        data["created_at"] = 0
        cache.write_text(json.dumps(data), encoding="utf-8")
    await r.collect(*args)
    assert len(calls) == 3
    async def denied(*_): raise ValueError("blocked")
    monkeypatch.setattr(wr, "read_page", denied)
    with pytest.raises(ValueError, match="Nessuna pagina"):
        await r.collect(p["id"], "Python", 3, True, lambda _:None, checkpoint, provider="searxng")


@pytest.mark.asyncio
async def test_direct_wikipedia_reads_pages_without_search_server(store, monkeypatch):
    calls = []
    async def reply(_session, url, **kwargs):
        from urllib.parse import urlsplit, parse_qs
        calls.append(url)
        assert urlsplit(url).hostname == "it.wikipedia.org"
        assert await kwargs["before_request"](None, url)
        assert not await kwargs["before_request"](None, "https://external.example/")
        params = parse_qs(urlsplit(url).query)
        if params.get("list") == ["search"]:
            assert params["srsearch"] == ["Rivoluzione francese"]
            data = {"query": {"search": [{"pageid": i, "title": f"Voce {i}"} for i in range(1, 7)]}}
        else:
            page_id = params["pageids"][0]
            assert "exintro" not in params  # Read more than the introductory snippet.
            data = {"query": {"pages": {page_id: {"title": f"Voce {page_id}",
                "extract": "La Rivoluzione francese e le sue cause. "*150,
                "fullurl": f"https://it.wikipedia.org/wiki/Voce_{page_id}"}}}}
        return 200, "application/json", json.dumps(data), url
    monkeypatch.setattr(wr, "bounded_get", reply)
    async def checkpoint(): pass
    p = store.create(ProjectInput().model_dump())
    researcher = wr.WebResearch(store)
    result = await researcher.collect(p["id"], "Rivoluzione francese", 3, False, lambda _: None,
                                     checkpoint, endpoint="not even a valid search server")
    assert len(calls) == 4 and len(result["sources"]) == 3
    assert result["provider"] == "Wikipedia diretta"
    assert "non fonti indipendenti" in result["warnings"][0]
    assert len(result["sources"][0]["text"]) > 1200
    assert "text" not in wr.public_research(result)["sources"][0]
    cached = await researcher.collect(p["id"], "Rivoluzione francese", 3, False, lambda _: None, checkpoint)
    assert cached["cache_used"] and len(calls) == 4


@pytest.mark.asyncio
async def test_wikipedia_english_extension_and_disambiguation(store, monkeypatch):
    languages = []
    async def reply(_session, language, **params):
        languages.append(language)
        if params.get("list"):
            return {"query": {"search": [] if language == "it" else [{"pageid": 12, "title": "Python"}]}}
        return {"query": {"pages": {"12": {"extract": "Ambiguous title. "*50,
                                          "pageprops": {"disambiguation": ""}}}}}
    monkeypatch.setattr(wr, "wikipedia_api", reply)
    results = await wr.WebResearch(store).search(None, "Python", "wikipedia", "")
    assert languages == ["it", "en"] and results[0]["wiki_page_id"] == 12
    with pytest.raises(ValueError, match="disambiguazione"):
        await wr.read_wikipedia(None, results[0])


def test_source_citations_never_accept_invented_links():
    data = bundle()
    assert "docs.python.org" in wr.source_citations(["W1", "https://invented.example"], data, [])[0]
    with pytest.raises(ValueError):
        wr.source_citations(["https://invented.example"], data, [])


@pytest.mark.asyncio
async def test_worker_consent_snapshot_grounding_and_no_silent_fallback(store):
    p = store.create(ProjectInput(prompt="Spiega Python", count=1, web_enabled=True, web_query="Python").model_dump())
    w = Worker(store, SimpleNamespace())
    calls = []
    entered, release = asyncio.Event(), asyncio.Event()
    class Research:
        async def collect(self, pid, **kwargs):
            calls.append(kwargs)
            entered.set()
            await release.wait()
            return bundle()
    class LLM:
        async def prepare(self): pass
        def __init__(self, *_): pass
        async def json(self, prompt, **kwargs):
            assert "FONTI WEB ACQUISITE" in prompt
            assert "MODALITÀ CONOSCENZA DEL MODELLO" not in prompt
            if "Proponi esattamente" in prompt:
                return {"slides":[{"title":"Python", "purpose":"Interprete e funzioni"}]}
            return SlideContent(title="Python", sources=["W1"], blocks=[
                {"heading":"Interprete", "text":"Python esegue istruzioni attraverso un interprete. Le funzioni permettono di organizzare le operazioni e di riutilizzare il codice in contesti diversi, rendendo più chiara la struttura del programma.", "source":"W1"},
                {"heading":"Un esempio", "text":"Un programma può essere diviso in piccole funzioni che svolgono compiti specifici. Il risultato di una funzione può essere passato a un'altra operazione per costruire un comportamento più complesso e verificabile.", "kind":"example"}
            ]).model_dump()
    w.researcher, w.clients = Research(), LLM
    req = Generation(provider={"model":"test"}, prompt="Spiega Python", count=1)
    with pytest.raises(ValueError, match="Conferma"):
        w.submit(p["id"], req)
    assert not calls
    job = w.submit(p["id"], req.model_copy(update={"web_consent":True}))
    await entered.wait()
    latest = store.project(p["id"])
    latest["web_query"] = "non inviare questa nuova query"
    store.save_project(latest)
    release.set()
    await w.tasks[job["id"]]
    assert calls[0]["query"] == "Python"
    assert store.job(job["id"])["status"] == "completed"
    slide = store.project(p["id"])["slides"][0]
    assert "docs.python.org" in slide["content"]["sources"][0]
    assert "fonti web" in slide["content"]["notes"]
    assert "text" not in slide["web_research"]["sources"][0]
    assert store.job(job["id"])["source_mode"] == "web"


@pytest.mark.asyncio
async def test_web_failure_stops_before_loading_model_and_can_cancel(store):
    p = store.create(ProjectInput(prompt="Test", web_enabled=True, web_query="Test").model_dump())
    w = Worker(store, SimpleNamespace())
    class Research:
        async def collect(self, *_args, **_kwargs):
            raise ValueError("Motore non disponibile")
    w.researcher = Research()
    w.clients = lambda *_: pytest.fail("No LLM must load after failed research")
    job = w.submit(p["id"], Generation(provider={"model":"test"}, prompt="Test", web_consent=True))
    await w.tasks[job["id"]]
    assert store.job(job["id"])["status"] == "failed"
    assert not store.project(p["id"])["slides"]
    entered = asyncio.Event()
    class Waiting:
        async def collect(self, *_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()
    w.researcher = Waiting()
    job = w.submit(p["id"], Generation(provider={"model":"test"}, prompt="Test", web_consent=True))
    await entered.wait()
    await w.close()
    assert store.job(job["id"])["status"] == "interrupted"


class FakeResponse:
    def __init__(self, status=200, location=None, body=b"content"):
        self.status = status
        self.headers = {"Location":location} if location else {}
        self.content_type, self.charset = "text/html", "utf-8"
        self.body, self.content = body, self

    async def iter_chunked(self, _):
        yield self.body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_automatic_query_uses_new_brief_one_client_and_keeps_input_empty(store, mode):
    p = store.create(ProjectInput(title="Progetto", prompt="Vecchio argomento", count=1,
        text_density="brief", web_enabled=True, web_query="  ").model_dump())
    calls, prepared, instances = [], [], []
    class LLM:
        def __init__(self, provider, *_):
            instances.append(self)
            assert provider.mode == mode
        async def prepare(self):
            prepared.append(1)
        async def json(self, prompt, **kwargs):
            if "RICAVA LA QUERY DI RICERCA" in prompt:
                assert '"istruzioni_attuali": "Spiega Python con 6 slide colorate"' in prompt
                assert "Vecchio argomento" not in prompt
                assert kwargs["schema"]["required"] == ["query"]
                return {"query": "Python"}
            assert "FONTI WEB ACQUISITE" in prompt
            if "Proponi esattamente" in prompt:
                return {"slides": [{"title": "Python"}]}
            return SlideContent(title="Python", bullets=["Un linguaggio di programmazione."],
                                sources=["W1"]).model_dump()
    class Research:
        async def collect(self, pid, **kwargs):
            assert len(prepared) == 1
            assert kwargs["query"] == "Python"
            assert "automatic_brief" not in kwargs
            calls.append(kwargs)
            return bundle()
    worker = Worker(store, SimpleNamespace())
    worker.clients, worker.researcher = LLM, Research()
    req = Generation(provider={"mode": mode, "model": "fake", "remote_consent": True,
                    "base_url": "https://provider.example/v1", "api_key": "NEVER-TO-SEARCH"},
                    prompt="Spiega Python con 6 slide colorate", count=1, web_consent=True)
    with pytest.raises(ValueError, match="Conferma"):
        worker.submit(p["id"], req.model_copy(update={"web_consent": False}))
    assert instances == []
    for regeneration in (False, True):
        job = worker.submit(p["id"], req.model_copy(update={"regenerate_all": regeneration}))
        await worker.tasks[job["id"]]
        assert store.job(job["id"])["status"] == "completed", store.job(job["id"])["events"]
        saved = store.project(p["id"])
        assert saved["web_query"].strip() == ""
        assert saved["web_research"]["query"] == "Python"
        assert saved["web_research"]["query_mode"] == "automatic"
        assert any(e["message"] == "Query automatica: Python" for e in store.job(job["id"])["events"])
        assert len(instances) == 1 and len(prepared) == 1 and len(calls) == 1
        assert "NEVER-TO-SEARCH" not in str(calls) + str(store.job(job["id"]))
        calls.clear(); prepared.clear(); instances.clear()


@pytest.mark.asyncio
async def test_automatic_query_snapshots_brief_and_excludes_document_bodies(store):
    p = store.create(ProjectInput(prompt="Prima", web_enabled=True).model_dump())
    p["sources"] = [{"name": "Documento", "text": "PRIVATE ATTACHMENT BODY", "images": []}]
    store.save_project(p)
    entered, release = asyncio.Event(), asyncio.Event()
    class LLM:
        def __init__(self, *_): pass
        async def prepare(self):
            entered.set()
            await release.wait()
        async def json(self, prompt, **kwargs):
            assert "PRIVATE ATTACHMENT BODY" not in prompt
            assert '"istruzioni_attuali": "Argomento originale"' in prompt
            assert "Modifica successiva" not in prompt
            return {"query": "Argomento originale"}
    calls = []
    class Research:
        async def collect(self, pid, **kwargs):
            calls.append(kwargs["query"])
            raise ValueError("End of fixture")
    worker = Worker(store, SimpleNamespace())
    worker.clients, worker.researcher = LLM, Research()
    job = worker.submit(p["id"], Generation(provider={"model": "fake"}, prompt="Argomento originale",
                                           web_consent=True))
    await entered.wait()
    changed = store.project(p["id"])
    changed.update(prompt="Modifica successiva", web_query="Altra ricerca")
    store.save_project(changed)
    release.set()
    await worker.tasks[job["id"]]
    assert calls == ["Argomento originale"]
    assert store.project(p["id"])["web_query"] == "Altra ricerca"
    assert "PRIVATE ATTACHMENT BODY" not in str(store.job(job["id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("first", [
    {"query": ""}, {"query": "x" * 201}, {"other": "wrong field"}, ["Python"], {"query": None},
    {"query": "word " * 19}, {"query": "https://example.com/?token=secret"},
    {"query": "person@example.com"}, {"query": "C:\\Users\\someone\\private.txt"},
    {"query": "HTTPS://example.test/private-topic"}, {"query": "/home/alice/private/report.pdf"},
    {"query": "F:/Private/report.pdf"}, {"query": "\\\\server\\private"}, {"query": "api_key=private"},
])
async def test_automatic_query_repairs_invalid_output_without_searching(first):
    responses = [first, {"query": "  Python   programmazione  "}]
    class LLM:
        async def json(self, *_args, **_kwargs):
            return responses.pop(0)
    async def checkpoint(): pass
    query = await wr.automatic_query(LLM(), {"istruzioni_attuali": "Spiega Python"}, checkpoint)
    assert query == "Python programmazione" and not responses


@pytest.mark.asyncio
async def test_automatic_query_bad_json_retry_and_cancellation(store):
    calls = []
    class LLM:
        async def json(self, *_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("Il modello non ha restituito JSON valido")
            return {"query": "Python"}
    async def checkpoint(): pass
    assert await wr.automatic_query(LLM(), {}, checkpoint) == "Python"
    entered = asyncio.Event()
    class Waiting:
        def __init__(self, *_): pass
        async def prepare(self): pass
        async def json(self, *_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()
    p = store.create(ProjectInput(prompt="Python", web_enabled=True).model_dump())
    worker = Worker(store, SimpleNamespace())
    worker.clients = Waiting
    class NeverSearch:
        async def collect(self, *_, **__):
            pytest.fail("An interrupted query must not launch a web search")
    worker.researcher = NeverSearch()
    job = worker.submit(p["id"], Generation(provider={"model": "fake"}, prompt="Python", web_consent=True))
    await entered.wait()
    await worker.close()
    assert store.job(job["id"])["status"] == "interrupted"


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, **kwargs):
        assert kwargs["allow_redirects"] is False
        self.calls.append(url)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_redirect_guard_prevents_private_network_fetch():
    session = FakeSession([FakeResponse(302, "http://127.0.0.1/private")])
    with pytest.raises(ValueError, match="privata"):
        await wr.bounded_get(session, "https://example.com/start")
    assert session.calls == ["https://example.com/start"]


@pytest.mark.asyncio
async def test_robots_checked_again_before_redirect_destination():
    session = FakeSession([FakeResponse(302, "https://other.example/denied")])
    checked = []
    async def allowed(_session, url):
        checked.append(url)
        return not url.endswith("/denied")
    with pytest.raises(ValueError, match="permette"):
        await wr.bounded_get(session, "https://example.com/start", before_request=allowed)
    assert len(session.calls) == 1
    assert checked == ["https://example.com/start", "https://other.example/denied"]


@pytest.mark.asyncio
async def test_page_body_is_bounded():
    session = FakeSession([FakeResponse(body=b"x"*100)])
    with pytest.raises(ValueError, match="limite"):
        await wr.bounded_get(session, "https://example.com/page", limit=50)


@pytest.mark.asyncio
async def test_robots_denial_respected(monkeypatch):
    async def robots(*_args, **_kwargs):
        return 200, "text/plain", "User-agent: *\nDisallow: /private\n", "https://example.com/robots.txt"
    monkeypatch.setattr(wr, "bounded_get", robots)
    assert not await wr.robots_allowed(None, "https://example.com/private/page")
    assert await wr.robots_allowed(None, "https://example.com/public")
