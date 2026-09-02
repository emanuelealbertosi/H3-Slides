import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from pypdf import PdfWriter
from PIL import Image
from h3_slides.ingest import ingest
from h3_slides.models import Generation, ProjectInput, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker


@pytest.fixture
def store(tmp_path):
    db = Store(tmp_path)
    yield db
    db.db.close()


def project(store):
    p = store.create(ProjectInput(title="Test", prompt="Spiega il documento", count=2).model_dump())
    p["sources"] = [ingest(store, p["id"], "fonte.md", b"# Energia\nFatto documentato.")]
    return store.save_project(p)


def test_ingest_markdown(store):
    p = project(store)
    assert "Energia" in p["sources"][0]["text"]


def test_ingest_image(store):
    p = project(store)
    raw = io.BytesIO()
    Image.new("RGB", (100, 100)).save(raw, format="PNG")
    source = ingest(store, p["id"], "example.png", raw.getvalue())
    assert len(source["images"]) == 1
    assert store.asset_path(p["id"], source["images"][0]["id"]).exists()


def test_scanned_pdf_warning(store):
    p = project(store)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    raw = io.BytesIO()
    writer.write(raw)
    source = ingest(store, p["id"], "scan.pdf", raw.getvalue())
    assert len(source["images"]) == 1
    assert "vision" in source["warnings"][0]


def test_paths_rejected(store):
    p = project(store)
    for path in ("../private", "..\\private", "C:\\private"):
        with pytest.raises(ValueError):
            store.asset_path(p["id"], path)


def test_slidev_treats_user_expressions_as_literal(store, tmp_path):
    from h3_slides.slidev import write_slidev
    p = project(store)
    p["slides"] = [{"content": SlideContent(title="{{ dangerous() }} <script>").model_dump()}]
    path = write_slidev(p, tmp_path, tmp_path / "slidev")
    text = path.read_text(encoding="utf-8")
    assert '<div v-pre>' in text
    assert '<script>' not in text


def test_live_sync_follows_saves(store):
    p = project(store)
    observed = []
    store.on_project_saved = lambda p: observed.append(p["title"])
    p["title"] = "Modifica live"
    store.save_project(p)
    assert observed == ["Modifica live"]


def test_restart_marks_jobs(tmp_path):
    db = Store(tmp_path)
    db.save_job({"id": "job", "status": "running"})
    db.db.close()
    db = Store(tmp_path)
    assert db.job("job")["status"] == "interrupted"
    db.db.close()


class FakeLLM:
    entered = None
    release = None
    def __init__(self, *_):
        pass
    async def prepare(self):
        pass
    async def json(self, prompt, schema=None, images=None):
        if "Estrai fatti" in prompt:
            return {"summary": "Fonte: energia."}
        if "Proponi esattamente" in prompt:
            return {"slides": [{"title": "Introduzione"}, {"title": "Conclusione"}]}
        if self.entered:
            self.entered.set()
            await self.release.wait()
        return SlideContent(title="Titolo dal modello", bullets=["Un punto documentato"]).model_dump()


def request():
    return Generation(provider={"mode":"local", "model":"fake", "api_key":"DO-NOT-SAVE"},
                      prompt="Spiega energia", count=2)


@pytest.mark.asyncio
async def test_incremental_generation_and_no_secrets(store):
    p = project(store)
    worker = Worker(store, SimpleNamespace())
    worker.clients = FakeLLM
    job = worker.submit(p["id"], request())
    await worker.tasks[job["id"]]
    assert store.job(job["id"])["status"] == "completed"
    assert len(store.project(p["id"])["slides"]) == 2
    assert "DO-NOT-SAVE" not in json.dumps(store.jobs())


@pytest.mark.asyncio
async def test_edits_survive_inflight_generation(store):
    p = project(store)
    worker = Worker(store, SimpleNamespace())
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowLLM(FakeLLM):
        pass
    SlowLLM.entered, SlowLLM.release = entered, release
    worker.clients = SlowLLM
    job = worker.submit(p["id"], request())
    await asyncio.wait_for(entered.wait(), 2)
    latest = store.project(p["id"])
    latest["slides"][0].update(revision=1, status="ready", content=SlideContent(title="Modifica dell'utente").model_dump())
    store.save_project(latest)
    release.set()
    await worker.tasks[job["id"]]
    assert store.project(p["id"])["slides"][0]["content"]["title"] == "Modifica dell'utente"


@pytest.mark.asyncio
async def test_duplicate_job_rejected_and_cancel(store):
    p = project(store)
    worker = Worker(store, SimpleNamespace())
    class SlowLLM(FakeLLM):
        async def prepare(self):
            await asyncio.sleep(60)
    worker.clients = SlowLLM
    job = worker.submit(p["id"], request())
    await asyncio.sleep(0)
    with pytest.raises(ValueError):
        worker.submit(p["id"], request())
    await worker.close()
    assert store.job(job["id"])["status"] == "interrupted"
