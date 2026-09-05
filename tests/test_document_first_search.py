"""Worker integration for document-first, optional gap-filling web research."""
import asyncio
import copy
import time
from types import SimpleNamespace

import pytest

from h3_slides.models import Generation, ProjectInput, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker


DOCUMENT_TEXT = "Python definisce funzioni con def. PRIVATE_DOCUMENT_FRAGMENT"
MISSING_TOPIC = "Python parametri keyword-only"


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path)
    yield value
    value.db.close()


def project_with_document(store, **overrides):
    values = {"title": "Python", "prompt": "Spiega Python e le funzioni", "count": 1,
              "text_density": "brief", "web_enabled": True, "web_query": "",
              "source_priority": "documents", **overrides}
    project = store.create(ProjectInput.model_validate(values).model_dump())
    project["sources"] = [{"id": "document", "name": "Manuale.md", "kind": "md",
                          "text": DOCUMENT_TEXT, "images": [], "warnings": []}]
    project["web_research"] = {
        "status": "completed", "provider": "Old research", "query": "Old topic",
        "sources": [{"id": "W1", "url": "https://old.example/source", "title": "Old"}],
        "warnings": [], "job_id": "old-job"}
    store.save_project(project)
    return project


def request_for(project, mode="local", **overrides):
    return Generation(provider={"mode": mode, "model": "fixture", "remote_consent": True,
        "base_url": "https://provider.example/v1"}, prompt=project["prompt"],
        count=1, web_consent=True, **overrides)


def web_bundle(query):
    return {"provider": "Wikipedia diretta", "query": query, "created_at": time.time(),
            "sources": [{"id": "W1", "title": "Python functions",
                "url": "https://docs.python.org/3/tutorial/controlflow.html",
                "text": "Python keyword-only parameters provide named function arguments. " * 20,
                "retrieved_at": time.time()}], "warnings": [], "cache_used": False}


def coverage_result(status):
    return {"status": status, "reason": {
        "sufficient": "Il documento spiega già i concetti richiesti.",
        "missing": "Mancano i parametri keyword-only.",
        "uncertain": "Non è possibile verificare con sicurezza la copertura.",
    }[status], "missing_topics": [MISSING_TOPIC] if status == "missing" else [],
        "evidence": [{"source": "Manuale.md", "quote": DOCUMENT_TEXT}]}


def generation_client(trace, *, with_web=False, query=None, check_query=None):
    class Client:
        def __init__(self, provider, *_):
            self.provider = provider
        async def prepare(self):
            trace.append("prepare")
        async def json(self, prompt, **kwargs):
            if "Estrai fatti" in prompt:
                trace.append("document")
                assert DOCUMENT_TEXT in prompt
                return {"summary": "Manuale.md: Python definisce funzioni con def."}
            if "RICAVA LA QUERY" in prompt:
                trace.append("query")
                assert query is not None, "No query may be generated after skipping web"
                assert "PRIVATE_DOCUMENT_FRAGMENT" not in prompt
                if check_query:
                    check_query(prompt)
                return {"query": query}
            if with_web:
                # Remote mode may omit the overall summary, but receives per-slide evidence.
                assert "FONTI WEB ACQUISITE" in prompt or "ESTRATTI WEB PER QUESTA SLIDE" in prompt
            else:
                assert "FONTI WEB ACQUISITE" not in prompt
                assert "ESTRATTI WEB PER QUESTA SLIDE" not in prompt
            assert "MODALITÀ CONOSCENZA DEL MODELLO" not in prompt
            if "Proponi esattamente" in prompt:
                trace.append("outline")
                return {"slides": [{"title": "Python", "purpose": "Le funzioni",
                                    "layout": "cover", "block_count": 1}]}
            trace.append("slide")
            return SlideContent(title="Python", bullets=["Le funzioni riutilizzano istruzioni."],
                sources=["Manuale.md", "W1"] if with_web else ["Manuale.md"]).model_dump()
    return Client


async def finish(store, worker, project, request):
    job = worker.submit(project["id"], request)
    await asyncio.wait_for(worker.tasks[job["id"]], timeout=5)
    result = store.job(job["id"])
    assert result["status"] == "completed", result.get("error") or result["events"]
    return store.project(project["id"]), result


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
@pytest.mark.parametrize("status,reason", [
    ("sufficient", "documents_sufficient"), ("uncertain", "coverage_uncertain")])
async def test_covered_or_uncertain_documents_skip_all_web_calls(store, monkeypatch, mode, status, reason):
    project = project_with_document(store)
    trace, assessments = [], []
    worker = Worker(store, SimpleNamespace())
    worker.clients = generation_client(trace)
    async def assess(self, client, current, request, context, jid, brief):
        trace.append("coverage")
        assessments.append(copy.deepcopy(brief))
        assert "Manuale.md" in context
        assert current["sources"] == project["sources"]
        assert request.prompt in str(brief)
        return coverage_result(status)
    class ForbiddenResearch:
        async def collect(self, *args, **kwargs):
            pytest.fail("Covered/uncertain documents must not trigger web research")
    monkeypatch.setattr(Worker, "assess_document_coverage", assess)
    worker.researcher = ForbiddenResearch()
    saved, result = await finish(store, worker, project, request_for(project, mode))
    assert trace == ["prepare", "document", "coverage", "outline", "slide"]
    assert len(assessments) == 1 and result["source_mode"] == "documents"
    assert saved["web_enabled"] is True and saved["web_query"] == ""
    assert saved["sources"] == project["sources"]
    metadata = saved["web_research"]
    assert metadata["status"] == "skipped" and metadata["skipped_reason"] == reason
    assert metadata["sources"] == [] and metadata["attempted_queries"] == [] and metadata["query"] == ""
    assert metadata["coverage"]["status"] == status and "evidence" not in metadata["coverage"]
    assert "PRIVATE_DOCUMENT_FRAGMENT" not in str(metadata)
    assert "old.example" not in str(metadata)
    assert result["web_research"] == metadata and metadata["job_id"] == result["id"]
    assert saved["slides"][0]["content"]["sources"] == ["Manuale.md"]
    if status == "uncertain":
        assert metadata["warnings"], "Uncertain coverage must remain visible to the user"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_missing_topics_produce_targeted_query_after_document_analysis(store, monkeypatch, mode):
    project = project_with_document(store)
    trace, queries = [], []
    def check_query(prompt):
        assert MISSING_TOPIC in prompt
    worker = Worker(store, SimpleNamespace())
    worker.clients = generation_client(trace, with_web=True, query=MISSING_TOPIC, check_query=check_query)
    async def assess(self, client, current, request, context, jid, brief):
        trace.append("coverage")
        assert "Manuale.md" in context
        return coverage_result("missing")
    class Research:
        async def collect(self, pid, **options):
            trace.append("web")
            assert options["provider"] == "wikipedia" and pid == project["id"]
            assert "document_brief" not in options and "always_search" not in options
            queries.append(options["query"])
            return web_bundle(options["query"])
    monkeypatch.setattr(Worker, "assess_document_coverage", assess)
    worker.researcher = Research()
    saved, result = await finish(store, worker, project, request_for(project, mode))
    assert trace == ["prepare", "document", "coverage", "query", "web", "outline", "slide"]
    assert queries == [MISSING_TOPIC] and saved["web_query"] == ""
    assert saved["web_research"]["status"] == "completed"
    assert saved["web_research"]["query"] == MISSING_TOPIC
    assert result["source_mode"] == "documents+web"
    assert "Manuale.md" in saved["slides"][0]["content"]["sources"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
@pytest.mark.parametrize("priority,always_search", [("documents", True), ("web", False)])
async def test_explicit_always_search_or_web_priority_bypasses_coverage(
        store, monkeypatch, mode, priority, always_search):
    project = project_with_document(store, web_query="Python", source_priority=priority,
                                    web_always_search=always_search)
    assert project.get("web_always_search") is always_search
    trace = []
    worker = Worker(store, SimpleNamespace())
    worker.clients = generation_client(trace, with_web=True)
    async def forbidden_assessment(*args, **kwargs):
        pytest.fail("Explicit always-search/web priority must bypass automatic coverage")
    class Research:
        async def collect(self, pid, **options):
            trace.append("web")
            assert options["query"] == "Python"
            assert "always_search" not in options and "document_brief" not in options
            return web_bundle("Python")
    monkeypatch.setattr(Worker, "assess_document_coverage", forbidden_assessment)
    worker.researcher = Research()
    saved, result = await finish(store, worker, project, request_for(project, mode))
    prefix = ["prepare", "document", "web"] if priority == "documents" else ["web", "prepare", "document"]
    assert trace == prefix + ["outline", "slide"]
    assert saved["web_always_search"] is always_search and saved["web_query"] == "Python"
    assert saved["web_research"]["status"] == "completed"


@pytest.mark.asyncio
async def test_cancellation_during_coverage_does_not_start_search_or_generation(store, monkeypatch):
    project = project_with_document(store)
    trace, entered = [], asyncio.Event()
    worker = Worker(store, SimpleNamespace())
    worker.clients = generation_client(trace)
    async def waiting_assessment(*args, **kwargs):
        trace.append("coverage")
        entered.set()
        await asyncio.Event().wait()
    class ForbiddenResearch:
        async def collect(self, *args, **kwargs):
            pytest.fail("Cancelled assessment must never start web research")
    monkeypatch.setattr(Worker, "assess_document_coverage", waiting_assessment)
    worker.researcher = ForbiddenResearch()
    job = worker.submit(project["id"], request_for(project))
    await asyncio.wait_for(entered.wait(), timeout=5)
    await worker.close()
    assert store.job(job["id"])["status"] == "interrupted"
    assert trace == ["prepare", "document", "coverage"]
    assert store.project(project["id"])["slides"] == []


@pytest.mark.asyncio
async def test_coverage_uses_submitted_brief_not_concurrent_project_edit(store, monkeypatch):
    project = project_with_document(store)
    trace, entered, release, briefs = [], asyncio.Event(), asyncio.Event(), []
    worker = Worker(store, SimpleNamespace())
    parent_client = generation_client(trace)
    class Client(parent_client):
        async def json(self, prompt, **kwargs):
            if "Estrai fatti" in prompt:
                entered.set()
                await release.wait()
            return await super().json(prompt, **kwargs)
    worker.clients = Client
    async def assess(self, client, current, request, context, jid, brief):
        briefs.append(copy.deepcopy(brief))
        return coverage_result("sufficient")
    class ForbiddenResearch:
        async def collect(self, *args, **kwargs): pytest.fail("No web for complete documents")
    monkeypatch.setattr(Worker, "assess_document_coverage", assess)
    worker.researcher = ForbiddenResearch()
    req = request_for(project)
    job = worker.submit(project["id"], req)
    await asyncio.wait_for(entered.wait(), timeout=5)
    edited = store.project(project["id"])
    edited["prompt"] = "Concurrent instructions for the next generation"
    store.save_project(edited)
    release.set()
    await asyncio.wait_for(worker.tasks[job["id"]], timeout=5)
    assert store.job(job["id"])["status"] == "completed"
    assert len(briefs) == 1 and req.prompt in str(briefs[0])
    assert "Concurrent instructions" not in str(briefs[0])
    assert store.project(project["id"])["prompt"] == edited["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_missing_coverage_respects_explicit_manual_query(store, monkeypatch, mode):
    manual_query = "Python documentazione ufficiale parametri"
    project = project_with_document(store, web_query=manual_query)
    trace, queries = [], []
    worker = Worker(store, SimpleNamespace())
    # query=None makes the mock fail if the app tries to replace a manual query.
    worker.clients = generation_client(trace, with_web=True)
    async def assess(self, client, current, request, context, jid, brief):
        trace.append("coverage")
        return coverage_result("missing")
    class Research:
        async def collect(self, pid, **options):
            trace.append("web")
            queries.append(options["query"])
            assert "document_coverage" not in options and "document_brief" not in options
            return web_bundle(options["query"])
    monkeypatch.setattr(Worker, "assess_document_coverage", assess)
    worker.researcher = Research()
    saved, result = await finish(store, worker, project, request_for(project, mode))
    assert trace == ["prepare", "document", "coverage", "web", "outline", "slide"]
    assert queries == [manual_query] and saved["web_query"] == manual_query
    metadata = saved["web_research"]
    assert metadata["status"] == "completed" and metadata["query_mode"] == "manual"
    assert metadata["query"] == manual_query and metadata["attempted_queries"] == [manual_query]
    assert metadata["coverage"]["status"] == "missing"
    assert metadata["coverage"]["missing_topics"] == [MISSING_TOPIC]
    assert "evidence" not in metadata["coverage"]
    assert "PRIVATE_DOCUMENT_FRAGMENT" not in str(metadata)
    assert result["web_research"] == metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_disabled_web_bypasses_coverage_even_if_always_search_is_saved(store, monkeypatch, mode):
    project = project_with_document(store, web_enabled=False, web_always_search=True)
    trace = []
    worker = Worker(store, SimpleNamespace())
    worker.clients = generation_client(trace)
    async def forbidden_assessment(*args, **kwargs):
        pytest.fail("Web disabled must bypass coverage assessment")
    class ForbiddenResearch:
        async def collect(self, *args, **kwargs):
            pytest.fail("A saved always-search preference cannot enable disabled web research")
    monkeypatch.setattr(Worker, "assess_document_coverage", forbidden_assessment)
    worker.researcher = ForbiddenResearch()
    req = request_for(project, mode).model_copy(update={"web_consent": False})
    saved, result = await finish(store, worker, project, req)
    assert trace == ["prepare", "document", "outline", "slide"]
    assert result["source_mode"] == "documents"
    assert "web_research" not in result
    assert saved["web_enabled"] is False and saved["web_always_search"] is True
    assert saved["slides"][0]["content"]["sources"] == ["Manuale.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_always_search_never_replaces_required_web_consent(store, monkeypatch, mode):
    project = project_with_document(store, web_always_search=True)
    trace = []
    worker = Worker(store, SimpleNamespace())
    worker.clients = generation_client(trace, with_web=True)
    async def forbidden_assessment(*args, **kwargs):
        pytest.fail("No assessment before required web consent")
    class ForbiddenResearch:
        async def collect(self, *args, **kwargs):
            pytest.fail("Always-search is not authorization to contact a provider")
    monkeypatch.setattr(Worker, "assess_document_coverage", forbidden_assessment)
    worker.researcher = ForbiddenResearch()
    req = request_for(project, mode).model_copy(update={"web_consent": False})
    before = store.project(project["id"])
    with pytest.raises(ValueError, match="Conferma"):
        worker.submit(project["id"], req)
    assert trace == [] and worker.tasks == {}
    assert store.jobs() == [] and store.project(project["id"]) == before
