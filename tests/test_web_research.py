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
                assert '"instructions": "Spiega Python con 6 slide colorate"' in prompt
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
    p = store.create(ProjectInput(prompt="Prima", web_enabled=True, source_priority="web").model_dump())
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
            assert '"instructions": "Argomento originale"' in prompt
            assert "Modifica successiva" not in prompt
            return {"query": "Argomento originale"}
    calls = []
    class Research:
        async def collect(self, pid, **kwargs):
            calls.append(kwargs["query"])
            raise ValueError("End of fixture")
    worker = Worker(store, SimpleNamespace())
    worker.clients, worker.researcher = LLM, Research()
    async def stop_after_search(*_):
        # This fixture checks query privacy only; document reading is a later, consented stage.
        raise ValueError("End of fixture")
    worker.sources_context = stop_after_search
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


def document_project(store, **overrides):
    project = store.create(ProjectInput(prompt="Spiega Python e le funzioni", count=1,
        text_density="brief", web_enabled=True, **overrides).model_dump())
    project["sources"] = [{"id": "doc", "name": "Manuale.md", "kind": "md",
        "text": "Python permette di definire funzioni riutilizzabili usando def.",
        "images": [], "warnings": []}]
    project["web_research"] = {**wr.public_research(bundle()), "job_id": "old-job"}
    store.save_project(project)
    return project


def test_web_priority_requires_actual_web_sources_and_document_default_is_validated():
    from h3_slides.worker import source_priority_rule
    from h3_slides.models import SYSTEM
    assert ProjectInput().source_priority == "documents"
    with pytest.raises(ValueError):
        ProjectInput(source_priority="implicit")
    project = {"sources": [{"name": "Manuale.md"}], "web_enabled": True}
    # In diagram-only jobs web is enabled in the project but no research is performed.
    assert "DOCUMENTI ALLEGATI" in source_priority_rule(project, "web")
    assert "WEB (scelta esplicita)" in source_priority_rule(project, "web", web_available=True)
    assert "PRIORITÀ FONTI" in SYSTEM
    assert "per gli allegati cita nome e pagina" in wr.web_context(bundle())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
@pytest.mark.parametrize("manual", [False, True])
async def test_simpler_query_success_reuses_client_and_preserves_choice(store, mode, manual):
    original = "Python programmazione funzioni"
    p = store.create(ProjectInput(prompt="Spiega Python", count=1, text_density="brief",
        web_enabled=True, web_query=original if manual else "").model_dump())
    prepared, instances, queries = [], [], []
    class LLM:
        def __init__(self, provider, *_):
            instances.append(self)
            assert provider.mode == mode
        async def prepare(self):
            prepared.append(1)
        async def json(self, prompt, **kwargs):
            if "SECONDO TENTATIVO" in prompt:
                assert '"query_originale": "' + original + '"' in prompt
                return {"query": "Python"}
            if "RICAVA LA QUERY" in prompt:
                assert not manual
                return {"query": original}
            assert "FONTI WEB ACQUISITE" in prompt
            if "Proponi esattamente" in prompt:
                return {"slides": [{"title": "Python"}]}
            return SlideContent(title="Python", bullets=["Le funzioni organizzano istruzioni."],
                                sources=["W1"]).model_dump()
    class Research:
        async def collect(self, pid, **kwargs):
            queries.append(kwargs["query"])
            assert kwargs["provider"] == "wikipedia"
            if len(queries) == 1:
                raise wr.NoSearchResults("Zero risultati")
            return bundle()
    w = Worker(store, SimpleNamespace())
    w.clients, w.researcher = LLM, Research()
    req = Generation(provider={"mode": mode, "model": "fake", "remote_consent": True,
        "base_url": "https://provider.example/v1"}, prompt="Spiega Python", count=1, web_consent=True)
    job = w.submit(p["id"], req)
    await w.tasks[job["id"]]
    saved, result = store.project(p["id"]), store.job(job["id"])
    assert result["status"] == "completed", result["events"]
    assert len(instances) == len(prepared) == 1
    assert queries == [original, "Python"]
    assert saved["web_query"] == (original if manual else "")
    assert saved["web_research"]["status"] == "completed"
    assert saved["web_research"]["attempted_queries"] == queries
    assert saved["web_research"]["query_mode"] == ("manual" if manual else "automatic")
    assert "docs.python.org" in saved["slides"][0]["content"]["sources"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
@pytest.mark.parametrize("provider", ["wikipedia", "duckduckgo", "searxng"])
async def test_empty_web_results_continue_from_documents_without_stale_web_sources(store, mode, provider):
    p = document_project(store, web_provider=provider, web_always_search=True)
    old_note = "Origine: fonti web lette dall'app; ricerca «vecchia». Verificare le affermazioni prima dell'uso."
    p["text_density"] = "detailed"
    p["slides"] = [{"id": "existing", "revision": 2, "status": "ready",
        "content": SlideContent(title="Python", notes=old_note+"\n\nNota utile del relatore.",
                                sources=["W1", "https://old.example"]).model_dump(),
        "web_research": wr.public_research(bundle())}]
    store.save_project(p)
    queries, prepares = [], []
    class LLM:
        def __init__(self, *_): pass
        async def prepare(self):
            prepares.append(1)
        async def json(self, prompt, **kwargs):
            if "SECONDO TENTATIVO" in prompt:
                return {"query": "Python"}
            if "RICAVA LA QUERY" in prompt:
                return {"query": "Python programmazione funzioni"}
            if "Estrai fatti" in prompt:
                return {"summary": "Manuale.md: Python usa def per definire funzioni."}
            assert "RICERCA WEB SENZA FONTI" in prompt
            assert "FONTI WEB ACQUISITE" not in prompt
            assert "MODALITÀ CONOSCENZA DEL MODELLO" not in prompt
            if "Proponi esattamente" in prompt:
                return {"slides": [{"title": "Python"}]}
            assert old_note not in prompt and "https://old.example" not in prompt
            # Simulate legacy web citations being echoed during a regeneration.
            return SlideContent(title="Python", notes=old_note+"\n\nNota utile del relatore.",
                sources=["W1", "https://old.example", "Manuale.md"],
                blocks=[{"text": "Una funzione permette di riutilizzare una sequenza di istruzioni. "
                    "In Python la parola def introduce la definizione e rende riconoscibile il blocco di codice.",
                    "source": "W1"}]).model_dump()
    class Research:
        async def collect(self, pid, **kwargs):
            assert kwargs["provider"] == provider
            queries.append(kwargs["query"])
            raise wr.NoSearchResults("Zero risultati")
    w = Worker(store, SimpleNamespace())
    w.clients, w.researcher = LLM, Research()
    job = w.submit(p["id"], Generation(provider={"mode": mode, "model": "fake",
        "remote_consent": True, "base_url": "https://provider.example/v1"},
        prompt="Spiega Python", count=1, web_consent=True, regenerate_all=True))
    await w.tasks[job["id"]]
    saved, result = store.project(p["id"]), store.job(job["id"])
    assert result["status"] == "completed", result["events"]
    assert result["source_mode"] == "documents"
    assert queries == ["Python programmazione funzioni", "Python"] and prepares == [1]
    assert saved["web_query"] == "" and saved["web_enabled"]
    assert saved["sources"] == p["sources"]
    metadata = saved["web_research"]
    assert metadata["status"] == "document_fallback" and metadata["sources"] == []
    assert metadata["job_id"] == job["id"] and metadata["attempted_queries"] == queries
    assert result["web_research"] == metadata
    slide = saved["slides"][0]
    assert slide["status"] == "ready" and slide["content"]["sources"] == ["Manuale.md"]
    assert slide["content"]["blocks"][0]["source"] == ""
    assert "nessuna verifica sul web" in slide["content"]["notes"].lower()
    assert old_note not in slide["content"]["notes"] and "Nota utile del relatore." in slide["content"]["notes"]
    assert slide["id"] == "existing" and slide["revision"] == 3
    assert slide["web_research"]["status"] == "document_fallback"
    assert any("uso i documenti" in e["message"] for e in result["events"])
    assert "docs.python.org" not in str(metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    ValueError("DuckDuckGo richiede un CAPTCHA"), ValueError("Wikipedia HTTP 429"),
    ValueError("Nessuna pagina ha permesso la lettura"), OSError("Rete non disponibile")])
async def test_unavailable_or_denied_web_does_not_retry_and_only_uses_attached_documents(store, failure):
    p = document_project(store, web_query="Python", web_always_search=True)
    calls = []
    class Research:
        async def collect(self, pid, **kwargs):
            calls.append(kwargs["query"])
            raise failure
    class LLM:
        def __init__(self, *_): pass
        async def prepare(self): pass
        async def json(self, prompt, **kwargs):
            assert "RICAVA LA QUERY" not in prompt
            if "Estrai fatti" in prompt:
                return {"summary": "Manuale.md: le funzioni riutilizzano istruzioni."}
            if "Proponi esattamente" in prompt:
                return {"slides": [{"title": "Python"}]}
            return SlideContent(title="Python", bullets=["Una funzione riutilizza istruzioni."],
                                sources=["Manuale.md"]).model_dump()
    w = Worker(store, SimpleNamespace())
    w.clients, w.researcher = LLM, Research()
    job = w.submit(p["id"], Generation(provider={"model": "fake"}, prompt="Spiega Python",
                                      count=1, web_consent=True))
    await w.tasks[job["id"]]
    result = store.job(job["id"])
    assert result["status"] == "completed", result["events"]
    assert calls == ["Python"] and result["web_research"]["status"] == "document_fallback"
    assert str(failure) in result["web_research"]["warnings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("simplified", ["Python", "Python funzioni", "Python argomento ancora più lungo"])
async def test_no_document_means_no_knowledge_fallback_or_duplicate_search(store, simplified):
    p = store.create(ProjectInput(prompt="Python", web_enabled=True, web_query="Python funzioni").model_dump())
    p["web_research"] = wr.public_research(bundle())
    store.save_project(p)
    queries = []
    class Research:
        async def collect(self, pid, **kwargs):
            queries.append(kwargs["query"])
            raise wr.NoSearchResults("Zero risultati")
    class LLM:
        def __init__(self, *_): pass
        async def prepare(self): pass
        async def json(self, prompt, **kwargs):
            assert "SECONDO TENTATIVO" in prompt
            return {"query": simplified}
    w = Worker(store, SimpleNamespace())
    w.clients, w.researcher = LLM, Research()
    job = w.submit(p["id"], Generation(provider={"model": "fake"}, prompt="Python", web_consent=True))
    await w.tasks[job["id"]]
    result, saved = store.job(job["id"]), store.project(p["id"])
    assert result["status"] == "failed" and "nessun documento" in result["error"]
    assert not saved["slides"]
    assert queries == (["Python funzioni", "Python"] if simplified == "Python" else ["Python funzioni"])
    assert saved["web_research"]["status"] == "failed" and saved["web_research"]["sources"] == []
    assert saved["web_query"] == "Python funzioni"


@pytest.mark.asyncio
async def test_cancellation_while_simplifying_never_starts_document_fallback(store):
    p = document_project(store, web_query="Python funzioni", source_priority="web")
    entered = asyncio.Event()
    queries = []
    class Research:
        async def collect(self, pid, **kwargs):
            queries.append(kwargs["query"])
            raise wr.NoSearchResults("Zero risultati")
    class LLM:
        def __init__(self, *_): pass
        async def prepare(self): pass
        async def json(self, prompt, **kwargs):
            entered.set()
            await asyncio.Event().wait()
    w = Worker(store, SimpleNamespace())
    w.clients, w.researcher = LLM, Research()
    job = w.submit(p["id"], Generation(provider={"model": "fake"}, prompt="Python", web_consent=True))
    await entered.wait()
    await w.close()
    result = store.job(job["id"])
    assert result["status"] == "interrupted" and queries == ["Python funzioni"]
    assert not store.project(p["id"])["slides"]
    assert not any("uso i documenti" in e["message"] for e in result["events"])


@pytest.mark.asyncio
@pytest.mark.parametrize("priority", ["documents", "web", "legacy"])
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_documents_are_read_and_cited_first_unless_web_priority_is_explicit(store, priority, mode):
    p = document_project(store, web_query="Python", web_always_search=True)
    if priority == "legacy":
        p.pop("source_priority")
    else:
        p["source_priority"] = priority
    store.save_project(p)
    calls = []
    class Research:
        async def collect(self, *_args, **kwargs):
            assert "source_priority" not in kwargs
            calls.append("web")
            return bundle()
    class LLM:
        def __init__(self, *_): pass
        async def prepare(self):
            calls.append("prepare")
        async def json(self, prompt, **kwargs):
            if "Estrai fatti" in prompt:
                calls.append("document")
                return {"summary": "Manuale.md: Python usa def per definire funzioni."}
            assert ("PRIORITÀ FONTI — WEB (scelta esplicita)" if priority == "web" else
                    "PRIORITÀ FONTI — DOCUMENTI ALLEGATI") in prompt
            if "Proponi esattamente" in prompt:
                return {"slides": [{"title": "Python"}]}
            return SlideContent(title="Python", bullets=["Le funzioni riutilizzano istruzioni."],
                                sources=["Manuale.md", "W1"]).model_dump()
    w = Worker(store, SimpleNamespace())
    w.clients, w.researcher = LLM, Research()
    job = w.submit(p["id"], Generation(provider={"model": "fake", "mode": mode,
        "remote_consent": True, "base_url": "https://provider.example/v1"},
        prompt="Spiega Python", count=1, web_consent=True))
    await w.tasks[job["id"]]
    saved, result = store.project(p["id"]), store.job(job["id"])
    assert result["status"] == "completed", result["error"]
    assert calls == (["web", "prepare", "document"] if priority == "web" else ["prepare", "document", "web"])
    assert saved["slides"][0]["content"]["sources"][0] == "Manuale.md"
    assert ("documenti allegati (fonti principali)" in saved["slides"][0]["content"]["notes"]) == (priority != "web")


@pytest.mark.asyncio
async def test_unreadable_primary_document_is_not_silently_replaced_by_web(store):
    p = document_project(store, web_query="Python")
    class LLM:
        def __init__(self, *_): pass
        async def prepare(self): pass
        async def json(self, *_args, **_kwargs): return {"summary": ""}
    class Research:
        async def collect(self, *_, **__):
            pytest.fail("Do not silently replace an unreadable primary document with the web")
    w = Worker(store, SimpleNamespace())
    w.clients, w.researcher = LLM, Research()
    job = w.submit(p["id"], Generation(provider={"model": "fake"}, prompt="Python", web_consent=True))
    await w.tasks[job["id"]]
    result = store.job(job["id"])
    assert result["status"] == "failed" and "Sintesi documento" in result["error"]
    assert not store.project(p["id"])["slides"]


@pytest.mark.asyncio
async def test_invalid_optional_query_does_not_block_primary_document_generation(store):
    p = document_project(store, web_always_search=True)
    calls = []
    class LLM:
        def __init__(self, *_): pass
        async def prepare(self): pass
        async def json(self, prompt, **kwargs):
            if "Estrai fatti" in prompt:
                calls.append("document")
                return {"summary": "Manuale.md: Python definisce funzioni riutilizzabili."}
            if "RICAVA LA QUERY" in prompt:
                calls.append("query")
                assert "Python definisce funzioni riutilizzabili" not in prompt
                return {"query": ""}
            if "Proponi esattamente" in prompt:
                return {"slides": [{"title": "Python"}]}
            return SlideContent(title="Python", bullets=["Le funzioni riutilizzano istruzioni."],
                                sources=["Manuale.md"]).model_dump()
    class Research:
        async def collect(self, *_, **__):
            pytest.fail("An invalid query must never be sent to a search provider")
    w = Worker(store, SimpleNamespace())
    w.clients, w.researcher = LLM, Research()
    job = w.submit(p["id"], Generation(provider={"model": "fake"}, prompt="Spiega Python", count=1,
                                      web_consent=True))
    await w.tasks[job["id"]]
    result = store.job(job["id"])
    assert result["status"] == "completed", result["error"]
    assert calls == ["document", "query", "query"]
    assert result["source_mode"] == "documents"
    assert result["web_research"]["attempted_queries"] == []
    assert result["web_research"]["sources"] == []


@pytest.mark.asyncio
async def test_search_empty_is_distinct_from_access_failure(store, monkeypatch):
    p = store.create(ProjectInput().model_dump())
    r = wr.WebResearch(store)
    async def empty(*_): return []
    async def checkpoint(): pass
    monkeypatch.setattr(r, "search", empty)
    with pytest.raises(wr.NoSearchResults):
        await r.collect(p["id"], "Python", 3, False, lambda _: None, checkpoint)


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
