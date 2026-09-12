"""Project canvas switches commit all geometry together or change nothing."""
from copy import deepcopy
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from h3_slides.app import create_app
from h3_slides.models import ProjectInput
from h3_slides.project_layout import apply_layout_updates


def make_project(mode="adaptive"):
    return {
        "id": "project", "title": "Progetto originale", "canvas_mode": mode,
        "slides": [{
            "id": "slide-1", "revision": 3, "status": "ready",
            "diagram_render": {"engine": "manim", "asset": "existing.png"},
            "content": {
                "title": "Testo originale", "layout": "freeform", "layout_locked": True,
                "canvas_height": 936,
                "blocks": [{"text": "```python\nprint('originale')\n```", "kind": "code"}],
                "notes": "Non normalizzare il testo nel cambio formato.",
                "diagram": {"kind": "flow", "labels": ["A", "B"]},
                "image_id": "original-photo.jpg", "image_origin": "upload",
                "freeform": {"block-0": {"x": 40, "y": 700, "w": 500, "h": 196}},
            },
        }, {
            "id": "slide-2", "revision": 6, "status": "ready",
            "content": {
                "title": "Layout automatico", "layout": "content", "canvas_height": 936,
                "freeform": {"block-0": {"x": 40, "y": 900, "w": 500, "h": 60}},
            },
        }],
    }


def update(sid="slide-1", revision=3, height=720, y=500, h=180):
    return {"id": sid, "revision": revision, "canvas_height": height,
            "freeform": {"block-0": {"x": 40, "y": y, "w": 500, "h": h}}}


def test_canvas_switch_commits_geometry_and_format_together():
    project = make_project()
    original = deepcopy(project)
    assert apply_layout_updates(project, [update()], canvas_mode="fixed") is project
    assert project["canvas_mode"] == "fixed"
    first, second = project["slides"]
    assert first["content"]["canvas_height"] == second["content"]["canvas_height"] == 720
    assert first["content"]["freeform"]["block-0"]["y"] == 500
    assert first["revision"] == 4
    assert second["revision"] == 7
    # Inactive legacy placements are not moved or removed.
    assert second["content"]["freeform"] == original["slides"][1]["content"]["freeform"]
    for before, after in zip(original["slides"], project["slides"]):
        for key, value in before.items():
            if key not in ("content", "revision"):
                assert after[key] == value
        for key, value in before["content"].items():
            if key not in ("canvas_height", "freeform"):
                assert after["content"][key] == value


def test_failed_later_geometry_keeps_whole_project_unchanged():
    project = make_project()
    before = deepcopy(project)
    bad = update("slide-2", revision=6)
    bad["freeform"]["not-an-element"] = bad["freeform"].pop("block-0")
    with pytest.raises(ValueError):
        apply_layout_updates(project, [update(), bad], canvas_mode="fixed")
    assert project == before


@pytest.mark.parametrize("updates,mode,message", [
    ([update(), update()], "fixed", "più di una volta"),
    ([update(revision=2)], "fixed", "aggiornata altrove"),
    ([update(sid="other-project-slide")], "fixed", "non appartiene"),
    ([update(height=936)], "fixed", "720 px"),
    ([update(y=700)], "fixed", "canvas utile"),
    ([update()], "unknown", "Formato slide non valido"),
])
def test_invalid_update_is_atomic(updates, mode, message):
    project = make_project()
    before = deepcopy(project)
    with pytest.raises(ValueError, match=message):
        apply_layout_updates(project, updates, canvas_mode=mode)
    assert project == before


def test_fixed_switch_requires_repositioning_omitted_active_freeform():
    project = make_project()
    before = deepcopy(project)
    with pytest.raises(ValueError, match="slide-1: adatta il layout"):
        apply_layout_updates(project, [], canvas_mode="fixed")
    assert project == before


def test_fixed_switch_can_keep_omitted_freeform_already_inside_canvas():
    project = make_project()
    project["slides"][0]["content"]["freeform"]["block-0"]["y"] = 400
    positions = deepcopy(project["slides"][0]["content"]["freeform"])
    apply_layout_updates(project, [], canvas_mode="fixed")
    assert project["slides"][0]["content"]["canvas_height"] == 720
    assert project["slides"][0]["content"]["freeform"] == positions
    assert project["slides"][0]["revision"] == 4


def test_implicit_mode_leaves_project_metadata_and_omitted_slides_untouched():
    project = make_project()
    before = deepcopy(project)
    apply_layout_updates(project, [update(height=1008, y=750)])
    assert project["canvas_mode"] == "adaptive"
    assert project["slides"][0]["content"]["canvas_height"] == 1008
    assert project["slides"][1] == before["slides"][1]


def test_adaptive_switch_preserves_existing_heights():
    project = make_project()
    project["canvas_mode"] = "fixed"
    before = deepcopy(project)
    apply_layout_updates(project, [], canvas_mode="adaptive")
    assert project["canvas_mode"] == "adaptive"
    assert project["slides"] == before["slides"]


def test_unchanged_geometry_does_not_increment_revision():
    project = make_project()
    before = deepcopy(project)
    apply_layout_updates(project, [update(height=936, y=700, h=196)])
    assert project == before


@pytest.mark.parametrize("invalid", [None, {}, "[]", tuple(), [update()] * 31])
def test_rows_must_be_bounded_list(invalid):
    project = make_project()
    before = deepcopy(project)
    with pytest.raises(ValueError, match="massimo 30"):
        apply_layout_updates(project, invalid)
    assert project == before


@pytest.mark.parametrize("field,value", [
    ("revision", "3"), ("revision", True), ("canvas_height", 720.5),
    ("id", 1), ("title", "Testo non autorizzato"),
    ("content", {"title": "Non consentito"}),
])
def test_geometry_update_schema_rejects_extra_fields_and_ambiguous_types(field, value):
    project = make_project()
    before = deepcopy(project)
    row = update()
    row[field] = value
    with pytest.raises(ValueError):
        apply_layout_updates(project, [row], canvas_mode="fixed")
    assert project == before


HEADERS = {"X-H3-Slides": "1"}
ROOT = Path(__file__).resolve().parents[1]


def stored_app(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    store = app["store"]
    project = store.create(ProjectInput(title="Prima del cambio", canvas_mode="adaptive").model_dump())
    project["slides"] = make_project()["slides"]
    store.save_project(project)
    writes = []
    original_save = store.save_project

    def record_save(value):
        writes.append(deepcopy(value))
        return original_save(value)

    def no_generation(*args, **kwargs):
        pytest.fail("Un cambio formato non deve avviare la generazione")

    async def no_model_or_render(*args, **kwargs):
        pytest.fail("Un cambio formato non deve caricare il modello o renderizzare Manim")

    monkeypatch.setattr(store, "save_project", record_save)
    monkeypatch.setattr(app["worker"], "submit", no_generation)
    monkeypatch.setattr(app["worker"].renderer, "render", no_model_or_render)
    monkeypatch.setattr(app["manager"], "start", no_model_or_render)
    return app, store, store.project(project["id"]), writes


@pytest.mark.asyncio
async def test_api_format_and_geometries_are_persisted_in_one_save(tmp_path, monkeypatch):
    app, store, before, writes = stored_app(tmp_path, monkeypatch)
    async with TestClient(TestServer(app)) as client:
        response = await client.patch(f"/api/projects/{before['id']}", headers=HEADERS, json={
            "title": "Dopo il cambio", "canvas_mode": "fixed", "slide_layouts": [update()],
        })
        assert response.status == 200, await response.text()
        saved = store.project(before["id"])
        assert await response.json() == saved
        assert len(writes) == 1
        assert writes[0]["title"] == "Dopo il cambio"
        assert writes[0]["canvas_mode"] == "fixed"
        assert saved["revision"] == before["revision"] + 1
        assert [slide["revision"] for slide in saved["slides"]] == [4, 7]
        assert all(slide["content"]["canvas_height"] == 720 for slide in saved["slides"])
        assert saved["slides"][0]["content"]["freeform"]["block-0"]["y"] == 500
        assert "slide_layouts" not in saved
        for original, final in zip(before["slides"], saved["slides"]):
            for key, value in original["content"].items():
                if key not in ("canvas_height", "freeform"):
                    assert final["content"][key] == value
            assert final["status"] == original["status"]
            assert final.get("diagram_render") == original.get("diagram_render")


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,expected", [
    ([update(revision=2)], "aggiornata altrove"),
    ([update(y=700)], "canvas utile"),
    ([update(), update(revision=6, sid="slide-2", height=936)], "720 px"),
    ([update(), update()], "più di una volta"),
    ([update(), update(sid="missing")], "non appartiene"),
    ([], "adatta il layout"),
    (None, "massimo 30"),
    ([{**update(), "title": "Campo non consentito"}], "Extra inputs"),
])
async def test_api_rejected_layout_rolls_back_metadata_and_all_slides(tmp_path, monkeypatch, rows, expected):
    app, store, before, writes = stored_app(tmp_path, monkeypatch)
    async with TestClient(TestServer(app)) as client:
        response = await client.patch(f"/api/projects/{before['id']}", headers=HEADERS, json={
            "title": "NON DEVE ESSERE SALVATO", "canvas_mode": "fixed", "theme": "forest",
            "slide_layouts": rows,
        })
        assert response.status == 400, await response.text()
        assert expected in (await response.json())["error"]
        assert writes == []
        assert store.project(before["id"]) == before
        reread = await client.get(f"/api/projects/{before['id']}")
        assert await reread.json() == before


@pytest.mark.asyncio
async def test_api_layout_only_updates_do_not_change_project_content_settings(tmp_path, monkeypatch):
    app, store, before, writes = stored_app(tmp_path, monkeypatch)
    async with TestClient(TestServer(app)) as client:
        response = await client.patch(f"/api/projects/{before['id']}", headers=HEADERS, json={
            "slide_layouts": [update(height=1008, y=750)],
        })
        assert response.status == 200, await response.text()
        saved = store.project(before["id"])
        assert len(writes) == 1
        assert saved["canvas_mode"] == "adaptive"
        assert saved["slides"][1] == before["slides"][1]
        assert saved["slides"][0]["content"]["canvas_height"] == 1008
        for key, value in before.items():
            if key not in ("slides", "revision", "updated_at"):
                assert saved[key] == value
        for key, value in before["slides"][0]["content"].items():
            if key not in ("canvas_height", "freeform"):
                assert saved["slides"][0]["content"][key] == value


@pytest.mark.asyncio
async def test_api_fixed_format_without_rows_normalizes_legacy_automatic_height(tmp_path, monkeypatch):
    app, store, project, writes = stored_app(tmp_path, monkeypatch)
    project["slides"][0]["content"]["layout"] = "editorial"
    store.save_project(project)
    before = store.project(project["id"])
    writes.clear()
    async with TestClient(TestServer(app)) as client:
        response = await client.patch(f"/api/projects/{before['id']}", headers=HEADERS,
                                      json={"canvas_mode": "fixed"})
        assert response.status == 200, await response.text()
        saved = store.project(before["id"])
        assert len(writes) == 1
        assert saved["canvas_mode"] == "fixed"
        for original, final in zip(before["slides"], saved["slides"]):
            assert final["content"]["canvas_height"] == 720
            assert final["revision"] == original["revision"] + 1
            assert final["content"]["freeform"] == original["content"]["freeform"]


@pytest.mark.asyncio
async def test_api_invalid_project_metadata_does_not_save_valid_geometry(tmp_path, monkeypatch):
    app, store, before, writes = stored_app(tmp_path, monkeypatch)
    async with TestClient(TestServer(app)) as client:
        response = await client.patch(f"/api/projects/{before['id']}", headers=HEADERS, json={
            "title": "", "canvas_mode": "fixed", "slide_layouts": [update()],
        })
        assert response.status == 400, await response.text()
        assert writes == []
        assert store.project(before["id"]) == before
