import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from h3_slides.models import Generation, ProjectInput, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker


class TextLLM:
    def __init__(self, *_):
        pass

    async def prepare(self):
        pass

    async def json(self, *_args, **_kwargs):
        return SlideContent(title="Ricerca aggiornata", blocks=[
            {"heading": "Metodo", "text": "La ricerca controlla ogni elemento in ordine e termina quando trova il valore desiderato oppure raggiunge la fine della collezione."}
        ], diagram={"kind": "manim", "brief": "Mostra la ricerca"}).model_dump()


def setup_worker(tmp_path):
    store = Store(tmp_path / "isolated")
    project = store.create(ProjectInput(engine="classic", prompt="Spiega la ricerca", count=2,
                                        use_manim_diagrams=True).model_dump())
    project["slides"] = [
        {"id": f"slide-{i}", "revision": 1, "status": "ready", "purpose": "Ricerca",
         "content": SlideContent(title="Ricerca originale").model_dump()}
        for i in range(2)
    ]
    store.save_project(project)
    worker = Worker(store, SimpleNamespace())
    worker.clients = TextLLM
    return store, project, worker


def request(**kwargs):
    return Generation(provider={"mode": "local", "model": "fake"},
                      prompt="Rigenera", count=2, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, OSError, TimeoutError])
@pytest.mark.parametrize("stage", ["design", "recovered_render"])
async def test_classic_optional_diagram_failure_keeps_both_slides(tmp_path, monkeypatch, error_type, stage):
    store, project, worker = setup_worker(tmp_path)
    diagram = {"kind": "manim", "brief": "Mostra la ricerca", "scene": None}
    design = AsyncMock(side_effect=(error_type("errore diagramma") if stage == "design"
                                   else ValueError("scena non valida")))
    monkeypatch.setattr("h3_slides.worker.design_diagram", design)
    if stage == "recovered_render":
        monkeypatch.setattr("h3_slides.worker.fallback_diagram", lambda *_: diagram)
        worker.renderer = SimpleNamespace(render=AsyncMock(side_effect=error_type("render fallito")))
    job = worker.submit(project["id"], request(regenerate_all=True))
    await worker.tasks[job["id"]]

    assert store.job(job["id"])["status"] == "completed"
    assert design.await_count == 2
    for slide in store.project(project["id"])["slides"]:
        assert slide["status"] == "ready" and slide["revision"] == 2
        assert slide["content"]["title"] == "Ricerca aggiornata"
        assert slide["content"]["blocks"][0]["text"].startswith("La ricerca")
        assert slide["content"]["diagram"]["scene"] is None
        assert slide["diagram_error"]
        assert "diagram_render" not in slide
    store.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type,status", [(asyncio.CancelledError, "cancelled"),
                                               (RuntimeError, "failed")])
async def test_classic_checkpoint_error_is_not_an_optional_diagram_failure(tmp_path, monkeypatch, error_type, status):
    store, project, worker = setup_worker(tmp_path)
    original_checkpoint, inside_diagram = worker.checkpoint, False

    async def checkpoint(jid):
        if inside_diagram:
            raise error_type("controllo interrotto")
        await original_checkpoint(jid)

    async def design(*args):
        nonlocal inside_diagram
        inside_diagram = True
        await args[-1]()

    monkeypatch.setattr(worker, "checkpoint", checkpoint)
    monkeypatch.setattr("h3_slides.worker.design_diagram", design)
    job = worker.submit(project["id"], request(regenerate_all=True))
    await worker.tasks[job["id"]]

    assert store.job(job["id"])["status"] == status
    for slide in store.project(project["id"])["slides"]:
        assert slide["revision"] == 1
        assert slide["content"]["title"] == "Ricerca originale"
        assert "diagram_error" not in slide
    store.db.close()


@pytest.mark.asyncio
async def test_classic_diagram_batch_continues_without_destroying_old_render(tmp_path, monkeypatch):
    store, project, worker = setup_worker(tmp_path)
    old_render = {"engine": "manim", "asset": "manim-old.png"}
    project["slides"][0]["diagram_render"] = old_render
    store.save_project(project)
    new_render = {"engine": "manim", "asset": "manim-new.png"}
    diagram = {"kind": "manim", "brief": "Mostra la ricerca", "scene": None}
    design = AsyncMock(side_effect=[OSError("renderer non disponibile"), (diagram, new_render)])
    monkeypatch.setattr("h3_slides.worker.design_diagram", design)
    job = worker.submit(project["id"], request(diagram_only=True, replace_diagrams=True))
    await worker.tasks[job["id"]]

    assert store.job(job["id"])["status"] == "completed"
    first, second = store.project(project["id"])["slides"]
    assert first["diagram_render"] == old_render and first["revision"] == 1
    assert second["diagram_render"] == new_render and second["revision"] == 2
    assert design.await_count == 2
    store.db.close()
