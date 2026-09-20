import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from h3_slides.models import Generation, ProjectInput, Provider, SlideContent
from h3_slides.page_layout import ordered_leaves
from h3_slides.page_v2 import PageSpec
from h3_slides.storage import Store
from h3_slides.worker import Worker
from h3_slides.worker_v2 import run_pages


PHOTO = "abc-123.jpg"
DIAGRAM = "manim-" + "d" * 64 + ".png"
SOURCES = ["Appunti, pagina 2", "Appunti, pagina 3"]


def data_page(label, heavy=False, media=False):
    nodes = [{"id": "title", "kind": "heading", "role": "title", "text": "Titolo " + label},
             {"id": "group", "kind": "group", "style": {"flow": "columns", "columns": [1, 1]}}]
    count = 2 if media else 3 if heavy else 1
    nodes.extend({"id": "body" + str(i), "parent": "group", "kind": "text",
                  "text": (f"{label} parte {i}. " * 32), "source": SOURCES[i % 2]} for i in range(count))
    if media:
        nodes.extend([
            {"id": "photo", "parent": "group", "kind": "image", "asset_id": PHOTO,
             "text": "Foto " + label, "query": "Query fotografica conservata"},
            {"id": "diagram", "parent": "group", "kind": "diagram", "text": "Schema " + label,
             "query": "Query schema conservata", "source": "Fonte diagramma"},
        ])
    return PageSpec.model_validate({"nodes": nodes, "notes": "Note complete " + label,
                                   "sources": SOURCES}).model_dump()


def setup_worker(tmp_path, monkeypatch):
    store = Store(tmp_path / "isolated")
    project = store.create(ProjectInput(engine="v2", count=2, use_source_images=False,
        use_manim_diagrams=True, slide_format="16:9", canvas_mode="adaptive").model_dump())
    project["sources"] = [{"id": "source", "name": "Appunti", "kind": "text", "images": []}]
    project["visual_assets"] = [{"id": PHOTO, "origin": "local", "source": "Archivio foto",
                                  "author": "Autore", "license": "CC0", "label": "Foto"}]
    store.save_project(project)
    store.save_job({"id": "job", "status": "running", "events": []})
    worker = Worker(store, SimpleNamespace())
    monkeypatch.setattr("h3_slides.worker_v2.slide_evidence", lambda *args: "Passaggi sintetici della fonte")
    calls = []

    async def diagram(*args):
        calls.append(args[6])
        return {"kind": "manim", "brief": args[6]}, {"asset": DIAGRAM, "engine": "manim"}

    monkeypatch.setattr("h3_slides.worker_v2.design_diagram", diagram)
    return store, project["id"], worker, calls


class Probe:
    def __init__(self, hook=None):
        self.pages = []
        self.hook = hook

    async def measure(self, project, page):
        self.pages.append(page.model_copy(deep=True))
        if self.hook:
            await self.hook(project, page, len(self.pages))
        leaves = [n for n in ordered_leaves(page) if n.kind != "heading"]
        kinds = {n.kind for n in leaves}
        # Each media item needs its own continuation; two ordinary paragraphs fit.
        overflow = len(leaves) > 2 or {"image", "diagram"}.issubset(kinds)
        return {"overflow": overflow, "height": 828 if overflow else 720,
                "neededHeight": 1400 if overflow else 700, "baseHeight": 720,
                "maxHeight": 828, "nodes": len(page.nodes)}


class Client:
    def __init__(self, store, pid, pages, outline_count=2):
        self.store, self.pid = store, pid
        self.pages = pages
        self.outline_count = outline_count
        self.outlines = []
        self.generated = []
        self.reflows = []
        self.before_page = []

    async def json(self, prompt, schema=None, **kwargs):
        if "slides" in schema.get("properties", {}):
            self.outlines.append({"prompt": prompt, "schema": schema})
            return {"slides": [{"title": "Pagina " + str(i + 1), "purpose": "Uno sviluppo leggibile"}
                               for i in range(self.outline_count)]}
        if "on_text" not in kwargs:
            assert "pages" in schema.get("properties", {}), "Only the bounded layout reflow is allowed"
            self.reflows.append({"prompt": prompt, "schema": schema})
            raise ValueError("Fixture: usa il fallback lossless")
        self.before_page.append(self.store.project(self.pid))
        assert len(self.generated) < len(self.pages), "Continuations must not be generated again"
        data = copy.deepcopy(self.pages[len(self.generated)])
        self.generated.append(data)
        await kwargs["on_text"](json.dumps(data, ensure_ascii=False))
        return data


def request():
    return Generation(provider=Provider(), prompt="Una sequenza chiara", count=2)


@pytest.mark.parametrize("format_name", ["4:3", "16:10", "1:1"])
def test_classic_nonstandard_format_is_rejected_before_job_or_llm(tmp_path, format_name):
    store = Store(tmp_path / "classic-isolated")
    project = store.create(ProjectInput(engine="classic", slide_format=format_name).model_dump())
    worker = Worker(store, SimpleNamespace())
    worker.clients = lambda *a, **k: pytest.fail("No LLM may be contacted for an unsupported classic format")
    before = store.project(project["id"])
    with pytest.raises(ValueError, match="richiedono il motore V2"):
        worker.submit(project["id"], request())
    assert store.project(project["id"]) == before
    assert not store.jobs() and not worker.tasks


@pytest.mark.asyncio
async def test_continuations_are_inserted_ready_in_order_with_sources_and_media(tmp_path, monkeypatch):
    store, pid, worker, diagram_calls = setup_worker(tmp_path, monkeypatch)
    worker.page_measurer = Probe()
    original_a, original_b = data_page("A", media=True), data_page("B")
    client = Client(store, pid, [original_a, original_b])
    await run_pages(worker, client, "job", pid, request(), "Testo dalle fonti", [])
    project = store.project(pid)
    assert project["count"] == 2 and len(project["slides"]) == 4
    assert [s["status"] for s in project["slides"]] == ["ready"] * 4
    assert len(client.generated) == 2 and len(client.reflows) == 1
    original_ids = [s["id"] for s in client.before_page[0]["slides"]]
    assert project["slides"][0]["id"] == original_ids[0]
    assert project["slides"][-1]["id"] == original_ids[1]
    assert len({s["id"] for s in project["slides"]}) == 4
    assert [s["status"] for s in client.before_page[1]["slides"]] == ["ready", "ready", "ready", "generating"]
    pages = [PageSpec.model_validate(s["content"]["page"]) for s in project["slides"]]
    assert [ordered_leaves(p)[0].text for p in pages] == ["Titolo A"] * 3 + ["Titolo B"]
    actual_a = [n for p in pages[:3] for n in ordered_leaves(p) if n.kind != "heading"]
    expected_a = [n for n in ordered_leaves(PageSpec.model_validate(original_a)) if n.kind != "heading"]
    assert [(n.id, n.kind, n.text, n.query) for n in actual_a] == [(n.id, n.kind, n.text, n.query) for n in expected_a]
    for slide, page in zip(project["slides"], pages):
        assert page.sources == SOURCES and slide["content"]["sources"] == SOURCES
        assert page.notes == ("Note complete A" if slide is not project["slides"][-1] else "Note complete B")
        diagrams = {n.id for n in page.nodes if n.kind == "diagram"}
        assert set(slide.get("page_diagrams", {})) == diagrams
        for diagram_id in diagrams:
            assert slide["page_diagrams"][diagram_id]["render"]["asset"] == DIAGRAM
        assert not {"page_draft", "page_stream", "page_error"} & slide.keys()
    photo = next(n for n in actual_a if n.kind == "image")
    diagram = next(n for n in actual_a if n.kind == "diagram")
    assert photo.asset_id == PHOTO and photo.source == "Archivio foto · Autore · CC0"
    assert diagram.asset_id == DIAGRAM and diagram.source == "Fonte diagramma"
    assert diagram_calls == ["Schema A"]
    assert next(n for n in worker.page_measurer.pages[0].nodes if n.kind == "diagram").asset_id == DIAGRAM, "Resolve media precedes measurement"
    assert store.job("job")["status"] == "completed"


@pytest.mark.asyncio
async def test_extra_budget_is_global_across_original_target_pages(tmp_path, monkeypatch):
    store, pid, worker, _ = setup_worker(tmp_path, monkeypatch)
    worker.page_measurer = Probe()
    client = Client(store, pid, [data_page("A", media=True), data_page("B", heavy=True)])
    with pytest.raises(ValueError, match="Bozza conservata"):
        await run_pages(worker, client, "job", pid, request(), "", [])
    project = store.project(pid)
    assert project["count"] == 2 and len(project["slides"]) == 4
    assert [s["status"] for s in project["slides"]] == ["ready", "ready", "ready", "failed"]
    assert len(client.reflows) == 2
    assert "1 fino a 3 pagine" in client.reflows[0]["prompt"]
    assert "1 fino a 1 pagine" in client.reflows[1]["prompt"]
    draft = PageSpec.model_validate(project["slides"][-1]["page_draft"])
    assert [n.text for n in ordered_leaves(draft)] == [n.text for n in ordered_leaves(PageSpec.model_validate(client.pages[1]))]
    assert store.job("job")["status"] != "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("overflow", [False, True])
async def test_outline_may_use_two_extra_pages_without_increasing_the_target(tmp_path, monkeypatch, overflow):
    store, pid, worker, _ = setup_worker(tmp_path, monkeypatch)
    worker.page_measurer = Probe()
    client = Client(store, pid, [data_page(str(i), heavy=overflow and i == 0) for i in range(4)], outline_count=4)
    if overflow:
        with pytest.raises(ValueError, match="Bozza conservata"):
            await run_pages(worker, client, "job", pid, request(), "", [])
        assert len(client.generated) == 1 and len(client.reflows) == 1
        assert "1 fino a 1 pagine" in client.reflows[0]["prompt"]
    else:
        await run_pages(worker, client, "job", pid, request(), "", [])
        assert len(client.generated) == 4 and not client.reflows
        assert all(s["status"] == "ready" for s in store.project(pid)["slides"])
        assert store.job("job")["status"] == "completed"
    project = store.project(pid)
    assert len(project["slides"]) == 4 and project["count"] == 2
    schema = client.outlines[0]["schema"]["properties"]["slides"]
    assert schema["minItems"] == 2 and schema["maxItems"] == 4


@pytest.mark.asyncio
async def test_concurrent_user_revision_during_measurement_is_not_overwritten(tmp_path, monkeypatch):
    store, pid, worker, _ = setup_worker(tmp_path, monkeypatch)
    saved = {}

    async def edit(project, page, number):
        if number != 1:
            return
        current = store.project(pid)
        item = current["slides"][0]
        item["revision"] += 1
        item["status"] = "ready"
        item["content"] = SlideContent(title="Modifica utente", page={"nodes": [
            {"id": "user", "kind": "text", "text": "Testo scritto dall’utente"}]}).model_dump()
        saved.update(copy.deepcopy(item))
        store.save_project(current)

    worker.page_measurer = Probe(edit)
    client = Client(store, pid, [data_page("A"), data_page("B")])
    with pytest.raises(ValueError, match="modificat"):
        await run_pages(worker, client, "job", pid, request(), "", [])
    project = store.project(pid)
    assert len(project["slides"]) == 2 and project["count"] == 2
    assert project["slides"][0] == saved
    assert project["slides"][1]["status"] == "pending"
    assert len(client.generated) == len(worker.page_measurer.pages) == 1 and not client.reflows
    assert store.job("job")["status"] != "completed"


@pytest.mark.asyncio
async def test_cancellation_received_during_probe_stops_before_saving_ready(tmp_path, monkeypatch):
    store, pid, worker, _ = setup_worker(tmp_path, monkeypatch)

    async def cancel(project, page, number):
        job = store.job("job")
        job["status"] = "cancelled"
        store.save_job(job)

    worker.page_measurer = Probe(cancel)
    client = Client(store, pid, [data_page("A"), data_page("B")])
    with pytest.raises(asyncio.CancelledError):
        await run_pages(worker, client, "job", pid, request(), "", [])
    project = store.project(pid)
    assert len(project["slides"]) == 2 and project["slides"][1]["status"] == "pending"
    assert project["slides"][0]["status"] != "ready" and project["slides"][0].get("page_draft")
    assert len(client.generated) == len(worker.page_measurer.pages) == 1
    assert store.job("job")["status"] == "cancelled"
