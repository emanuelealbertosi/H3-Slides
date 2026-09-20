from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from h3_slides.models import Generation, ProjectInput, Provider, SlideContent
from h3_slides.page_v2 import PageSpec
from h3_slides.storage import Store
from h3_slides.worker import Worker
from h3_slides.worker_v2 import resolve_media


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_v2_diagram_uses_project_opt_in_without_a_prompt_keyword(monkeypatch, enabled):
    project = ProjectInput(engine="v2", prompt="Spiega il ciclo dell'acqua",
                           use_manim_diagrams=enabled).model_dump()
    page = PageSpec(nodes=[
        {"id": "title", "kind": "heading", "text": "Il ciclo dell'acqua"},
        {"id": "cycle", "kind": "diagram", "text": "Evaporazione, condensazione, precipitazione"},
    ])
    asset = "manim-" + "a" * 64 + ".png"
    design = AsyncMock(return_value=({"kind": "manim"}, {"asset": asset}))
    monkeypatch.setattr("h3_slides.worker_v2.design_diagram", design)
    client = SimpleNamespace(json=AsyncMock(side_effect=AssertionError("No real model call")))
    renderer = SimpleNamespace(render=AsyncMock(side_effect=AssertionError("No real render")))
    worker = SimpleNamespace(checkpoint=AsyncMock(), renderer=renderer,
                             store=SimpleNamespace(event=Mock()))
    diagrams = {}

    if enabled:
        await resolve_media(worker, client, "job", "project", page, project, "", {}, diagrams)
        design.assert_awaited_once()
        assert design.await_args.args[3]["prompt"] == "Spiega il ciclo dell'acqua"
        assert page.nodes[1].asset_id == asset
        assert diagrams["cycle"]["render"]["asset"] == asset
    else:
        await resolve_media(worker, client, "job", "project", page, project, "", {}, diagrams)
        design.assert_not_called()
        assert page.nodes[1].asset_id == ""
        assert diagrams["cycle"]["status"] == "disabled"
        assert "render" not in diagrams["cycle"]

    client.json.assert_not_called()
    renderer.render.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["classic", "v2"])
async def test_diagram_only_submission_requires_opt_in_before_creating_job_or_client(tmp_path, monkeypatch, engine):
    store = Store(tmp_path / "isolated")
    project = store.create(ProjectInput(engine=engine, use_manim_diagrams=False).model_dump())
    project["slides"] = [{"id": "slide", "revision": 1, "status": "ready",
                          "content": SlideContent(title="Il ciclo dell'acqua").model_dump()}]
    store.save_project(project)
    worker = Worker(store, SimpleNamespace())
    make_client = Mock(side_effect=AssertionError("Model client must not be created"))
    monkeypatch.setattr(worker, "make_client", make_client)
    request = Generation(provider=Provider(), prompt="Spiega il ciclo dell'acqua",
                         slide_id="slide", diagram_only=True)

    with pytest.raises(ValueError, match="Abilita Diagrammi Manim"):
        worker.submit(project["id"], request)

    make_client.assert_not_called()
    assert worker.tasks == {} and store.jobs() == []
    assert store.project(project["id"])["use_manim_diagrams"] is False
