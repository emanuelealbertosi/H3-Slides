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
            assert schema["properties"]["slides"]["minItems"] == 2
            assert schema["properties"]["slides"]["maxItems"] == 2
            assert schema["properties"]["slides"]["items"]["additionalProperties"] is False
            return {"slides": [{"title": "Introduzione"}, {"title": "Conclusione"}]}
        if self.entered:
            self.entered.set()
            await self.release.wait()
        return SlideContent(title="Titolo dal modello", blocks=[
            {"heading":"Spiegazione", "text":"Una spiegazione completa presenta il concetto e lo collega alle sue conseguenze. Il lettore può così capire non soltanto che cosa accade, ma anche perché accade, grazie a frasi collegate e a un esempio concreto."},
            {"heading":"Un esempio", "kind":"example", "text":"Un caso concreto permette di applicare il concetto a una situazione riconoscibile. Si osserva prima la condizione iniziale, poi si descrive il cambiamento e infine si spiega il risultato, senza saltare i passaggi importanti."}
        ]).model_dump()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_prompt_only_generation_and_regeneration(store, mode):
    p = store.create(ProjectInput(prompt="La rivoluzione francese", count=2,
                                  use_manim_diagrams=True).model_dump())
    prompts = []
    class KnowledgeLLM(FakeLLM):
        async def json(self, prompt, **kwargs):
            prompts.append(prompt)
            assert "MODALITÀ CONOSCENZA DEL MODELLO" in prompt
            assert not kwargs.get("images")
            if "Proponi esattamente" in prompt:
                return await super().json(prompt, **kwargs)
            generated = await super().json(prompt, **kwargs)
            return SlideContent(title="La rivoluzione francese", blocks=generated["blocks"],
                                notes="n"*6000, sources=["Un libro mai allegato, p. 42"],
                                image_id="immagine-inventata.jpg",
                                diagram={"kind":"flow", "labels":["Crisi", "Rivoluzione"]}).model_dump()
    worker = Worker(store, SimpleNamespace())
    worker.clients = KnowledgeLLM
    req = Generation(provider={"mode":mode, "model":"fake"}, prompt="La rivoluzione francese", count=2)
    job = worker.submit(p["id"], req)
    await worker.tasks[job["id"]]
    assert store.job(job["id"])["status"] == "completed"
    assert store.job(job["id"])["source_mode"] == "knowledge"
    generated = store.project(p["id"])
    assert len(generated["slides"]) == 2
    for s in generated["slides"]:
        c = s["content"]
        assert c["sources"] == [] and c["image_id"] == ""
        assert c["notes"].startswith("Origine: conoscenza del modello")
        assert len(c["notes"]) <= 6000
        assert c["diagram"]["kind"] == "flow"
    assert len(prompts) == 3  # No document analysis or RAG LLM requests.
    sid = generated["slides"][0]["id"]
    req = req.model_copy(update={"slide_id": sid, "prompt": "Spiega meglio le cause"})
    regenerated = worker.submit(p["id"], req)
    await worker.tasks[regenerated["id"]]
    assert store.job(regenerated["id"])["status"] == "completed"
    assert store.project(p["id"])["slides"][0]["revision"] == 2
    assert "Spiega meglio le cause" in prompts[-1]


@pytest.mark.asyncio
async def test_regenerate_all_rewrites_every_slide_but_keeps_outline(store):
    p = store.create(ProjectInput(title="Corso", prompt="Spiega il corso", count=2).model_dump())
    p["slides"] = [
        {"id":"uno","revision":3,"status":"ready","purpose":"Aprire il tema",
         "block_count":2,"content":SlideContent(title="Introduzione").model_dump()},
        {"id":"due","revision":6,"status":"ready","purpose":"Concludere il tema",
         "block_count":2,"content":SlideContent(title="Conclusione").model_dump()},
    ]
    store.save_project(p)
    calls = []
    class RegenerateLLM(FakeLLM):
        async def json(self, prompt, **kwargs):
            calls.append(prompt)
            return await super().json(prompt, **kwargs)
    worker = Worker(store, SimpleNamespace())
    worker.clients = RegenerateLLM
    req = Generation(provider={"mode":"local","model":"fake"}, prompt=p["prompt"],
                     count=2, regenerate_all=True)
    job = worker.submit(p["id"], req)
    await worker.tasks[job["id"]]
    result = store.project(p["id"])
    assert store.job(job["id"])["status"] == "completed"
    assert [slide["id"] for slide in result["slides"]] == ["uno", "due"]
    assert [slide["purpose"] for slide in result["slides"]] == ["Aprire il tema", "Concludere il tema"]
    assert [slide["revision"] for slide in result["slides"]] == [4, 7]
    assert all(slide["content"]["title"] == "Titolo dal modello" for slide in result["slides"])
    assert len(calls) == 2  # La scaletta esistente non viene richiesta di nuovo.


def test_blank_topic_is_rejected():
    with pytest.raises(ValueError, match="Scrivi un argomento"):
        Generation(provider={"model":"fake"}, prompt=" \n\t ")


@pytest.mark.asyncio
async def test_prose_repair_before_save(store):
    p = project(store)
    class RepairLLM(FakeLLM):
        async def json(self, prompt, **kwargs):
            result = await super().json(prompt, **kwargs)
            if "Crea UNA slide" in prompt and "CORREGGI IL TENTATIVO" not in prompt:
                result["blocks"][0]["text"] = result["blocks"][0]["text"].rstrip(".")
            return result
    worker = Worker(store, SimpleNamespace())
    worker.clients = RepairLLM
    job = worker.submit(p["id"], request())
    await worker.tasks[job["id"]]
    assert store.job(job["id"])["status"] == "completed"
    assert sum("Correzione del testo" in e["message"] for e in store.job(job["id"])["events"]) == 2


@pytest.mark.asyncio
async def test_standalone_image_uses_vision_without_book_structure(store):
    p = store.create(ProjectInput(prompt="Spiega il diagramma nell'immagine", count=2).model_dump())
    raw = io.BytesIO()
    Image.new("RGB", (100, 100)).save(raw, format="PNG")
    p["sources"] = [ingest(store, p["id"], "diagramma.png", raw.getvalue())]
    store.save_project(p)
    seen = []
    class ImageLLM(FakeLLM):
        async def json(self, prompt, **kwargs):
            if kwargs.get("images"):
                seen.extend(kwargs["images"])
                return {"summary":"Nell'immagine è presente un diagramma."}
            return await super().json(prompt, **kwargs)
    worker = Worker(store, SimpleNamespace())
    worker.clients = ImageLLM
    job = worker.submit(p["id"], request())
    await worker.tasks[job["id"]]
    assert store.job(job["id"])["status"] == "completed"
    assert len(seen) == 1
    assert seen[0][0] == "diagramma.png"
