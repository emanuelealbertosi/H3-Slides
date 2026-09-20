import asyncio
import json
from types import SimpleNamespace

import pytest

from h3_slides.models import Generation, ProjectInput, Provider, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker
from h3_slides.worker_v2 import DIAGRAM_UNAVAILABLE, run_pages


OLD_ASSET = "manim-" + "a" * 64 + ".png"
NEW_ASSET = "manim-" + "b" * 64 + ".png"


def setup_deck(tmp_path):
    store = Store(tmp_path / "isolated")
    project = store.create(ProjectInput(engine="v2", count=2, use_source_images=False,
                                       use_manim_diagrams=True).model_dump())
    store.save_job({"id": "job", "status": "running", "events": []})
    worker = Worker(store, SimpleNamespace())
    return store, project["id"], worker


class PageClient:
    def __init__(self):
        self.pages = 0

    async def json(self, prompt, schema=None, **kwargs):
        if "on_text" not in kwargs:
            return {"slides": [{"title": "Prima", "purpose": "Uno"},
                               {"title": "Seconda", "purpose": "Due"}]}
        self.pages += 1
        data = {"nodes": [
            {"id": "title", "parent": "root", "kind": "heading", "text": f"Pagina {self.pages}"},
            {"id": "diagram", "parent": "root", "kind": "diagram",
             "text": "bad" if self.pages == 1 else "second", "asset_id": OLD_ASSET},
        ]}
        if self.pages == 1:
            data["nodes"].append({"id": "next_diagram", "kind": "diagram", "text": "next"})
        await kwargs["on_text"](json.dumps(data))
        return data


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, TimeoutError, OSError])
async def test_diagram_failure_keeps_other_diagrams_and_next_slide_running(tmp_path, monkeypatch, error_type):
    store, pid, worker = setup_deck(tmp_path)
    calls = []
    async def design(*args):
        instructions = args[6]
        calls.append(instructions)
        if instructions == "bad":
            raise error_type("PRIVATE MODEL RESPONSE")
        return {"kind": "manim"}, {"asset": NEW_ASSET}
    monkeypatch.setattr("h3_slides.worker_v2.design_diagram", design)
    await run_pages(worker, PageClient(), "job", pid,
                    Generation(provider=Provider(), prompt="Spiega", count=2), "", [])

    project = store.project(pid)
    first, second = project["slides"]
    assert calls == ["bad", "next", "second"]
    assert [slide["status"] for slide in project["slides"]] == ["ready", "ready"]
    assert first["content"]["page"]["nodes"][1]["asset_id"] == ""
    assert first["page_diagrams"]["diagram"] == {"status": "failed", "error": DIAGRAM_UNAVAILABLE}
    assert "render" not in first["page_diagrams"]["diagram"]
    assert first["content"]["page"]["nodes"][2]["asset_id"] == NEW_ASSET
    assert second["content"]["page"]["nodes"][1]["asset_id"] == NEW_ASSET
    assert first["page_diagrams"]["next_diagram"]["render"]["asset"] == NEW_ASSET
    assert second["page_diagrams"]["diagram"]["render"]["asset"] == NEW_ASSET
    job = store.job("job")
    assert job["status"] == "completed" and job["diagram_warnings"] == 1
    assert "PRIVATE" not in json.dumps([project, job])
    assert any("presentazione continua" in event["message"] for event in job["events"])
    assert any("elemento diagram" in event["message"] for event in job["events"])


@pytest.mark.asyncio
async def test_disabled_diagrams_leave_empty_slots_and_complete_the_deck(tmp_path, monkeypatch):
    store, pid, worker = setup_deck(tmp_path)
    project = store.project(pid)
    project["use_manim_diagrams"] = False
    store.save_project(project)
    async def forbidden(*args):
        raise AssertionError("Diagram generation must remain disabled")
    monkeypatch.setattr("h3_slides.worker_v2.design_diagram", forbidden)
    await run_pages(worker, PageClient(), "job", pid,
                    Generation(provider=Provider(), prompt="Spiega", count=2), "", [])
    project = store.project(pid)
    assert all(slide["status"] == "ready" for slide in project["slides"])
    assert all(record["status"] == "disabled" for slide in project["slides"]
               for record in slide["page_diagrams"].values())
    assert all(node["asset_id"] == "" for slide in project["slides"]
               for node in slide["content"]["page"]["nodes"] if node["kind"] == "diagram")
    assert store.job("job")["status"] == "completed"
    assert store.job("job")["diagram_warnings"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "cancel_after_failure", "checkpoint_error", "revision"])
async def test_diagram_recovery_does_not_swallow_control_or_revision_errors(tmp_path, monkeypatch, mode):
    store, pid, worker = setup_deck(tmp_path)
    calls = []
    inside_design = [False]
    original_checkpoint = worker.checkpoint
    async def checkpoint(jid):
        if inside_design[0] and mode == "checkpoint_error":
            raise RuntimeError("checkpoint stopped")
        await original_checkpoint(jid)
    monkeypatch.setattr(worker, "checkpoint", checkpoint)
    async def design(*args):
        calls.append(args[6])
        inside_design[0] = True
        if mode == "cancel":
            raise asyncio.CancelledError()
        if mode == "checkpoint_error":
            await args[8]()
        if mode == "cancel_after_failure":
            job = store.job("job")
            job["status"] = "cancelled"
            store.save_job(job)
        if mode == "revision":
            current = store.project(pid)
            current["slides"][0]["revision"] += 1
            current["slides"][0]["content"]["title"] = "Modifica utente"
            store.save_project(current)
        raise ValueError("Diagram failed")
    monkeypatch.setattr("h3_slides.worker_v2.design_diagram", design)
    expected = asyncio.CancelledError if mode.startswith("cancel") else RuntimeError if mode == "checkpoint_error" else ValueError
    with pytest.raises(expected):
        await run_pages(worker, PageClient(), "job", pid,
                        Generation(provider=Provider(), prompt="Spiega", count=2), "", [])
    project = store.project(pid)
    assert calls == (["bad", "next"] if mode == "revision" else ["bad"])
    assert project["slides"][1]["status"] == "pending"
    assert store.job("job")["status"] != "completed"
    if mode == "revision":
        assert project["slides"][0]["content"]["title"] == "Modifica utente"
    if mode == "cancel_after_failure":
        assert store.job("job")["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("retained", [False, True])
async def test_failed_single_redesign_preserves_existing_content_and_reports_failure(tmp_path, monkeypatch, retained):
    store, pid, worker = setup_deck(tmp_path)
    project = store.project(pid)
    page = {"nodes": [{"id": "title", "kind": "heading", "text": "Titolo"},
                       {"id": "diagram", "kind": "diagram", "text": "Richiesta precedente",
                        "asset_id": OLD_ASSET if retained else ""}]}
    original_content = SlideContent(title="Titolo", page=page).model_dump()
    project["slides"] = [{"id": "slide", "revision": 5, "status": "ready", "content": original_content,
                          "page_diagrams": {"diagram": {"diagram": {"kind": "manim"}, "render": {"asset": OLD_ASSET}}}}]
    store.save_project(project)
    async def fail(*args):
        raise RuntimeError("PRIVATE MODEL RESPONSE")
    monkeypatch.setattr("h3_slides.worker_v2.design_diagram", fail)
    request = Generation(provider=Provider(), prompt="Richiesta nuova", slide_id="slide",
                         diagram_only=True, page_node_id="diagram")
    with pytest.raises(ValueError, match="Diagramma non disponibile"):
        await run_pages(worker, SimpleNamespace(), "job", pid, request, "", [])
    slide = store.project(pid)["slides"][0]
    assert slide["content"] == original_content and slide["revision"] == 5
    assert slide["status"] == "ready"
    result = slide["page_diagrams"]["diagram"]
    assert result["status"] == "failed" and result["retained_asset"] is retained
    assert result["error"] == DIAGRAM_UNAVAILABLE
    if retained:
        assert result["render"]["asset"] == OLD_ASSET
    else:
        assert "render" not in result and "diagram" not in result
    assert "PRIVATE" not in json.dumps([slide, store.job("job")])


@pytest.mark.asyncio
async def test_failed_single_redesign_does_not_overwrite_concurrent_edit(tmp_path, monkeypatch):
    store, pid, worker = setup_deck(tmp_path)
    project = store.project(pid)
    content = SlideContent(title="Titolo", page={"nodes": [
        {"id": "diagram", "kind": "diagram", "text": "Prima", "asset_id": OLD_ASSET}]}).model_dump()
    project["slides"] = [{"id": "slide", "revision": 1, "status": "ready", "content": content}]
    store.save_project(project)
    async def fail(*args):
        current = store.project(pid)
        current["slides"][0]["content"]["title"] = "Modifica utente"
        current["slides"][0]["revision"] += 1
        store.save_project(current)
        raise ValueError("Diagram failed")
    monkeypatch.setattr("h3_slides.worker_v2.design_diagram", fail)
    with pytest.raises(ValueError, match="Pagina modificata"):
        await run_pages(worker, SimpleNamespace(), "job", pid,
                        Generation(provider=Provider(), prompt="Nuovo", slide_id="slide",
                                   diagram_only=True, page_node_id="diagram"), "", [])
    slide = store.project(pid)["slides"][0]
    assert slide["content"]["title"] == "Modifica utente" and slide["revision"] == 2
    assert "page_diagrams" not in slide
