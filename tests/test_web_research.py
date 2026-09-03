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
    args = (p["id"], "Python", 3, False, lambda _:None, checkpoint)
    first = await r.collect(*args)
    second = await r.collect(*args)
    assert len(calls) == 1 and second["cache_used"]
    assert len(first["sources"]) == 3 and "text" not in wr.public_research(first)["sources"][0]
    await r.collect(p["id"], "Python", 3, True, lambda _:None, checkpoint)
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
        await r.collect(p["id"], "Python", 3, True, lambda _:None, checkpoint)


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
