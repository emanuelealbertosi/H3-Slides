import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from h3_slides.app import create_app
from h3_slides.diagram_spec import legacy_scene
from h3_slides.diagrams import fingerprint
from h3_slides.models import ProjectInput, SlideContent
from h3_slides.slidev import write_slidev


ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


def photo_bytes():
    raw = io.BytesIO()
    Image.new("RGB", (80, 60), "navy").save(raw, format="PNG")
    return raw.getvalue()


def seed_diagram(app):
    project = app["store"].create(ProjectInput(
        title="Foto e diagramma", use_source_images=False, use_manim_diagrams=True).model_dump())
    diagram = {"kind": "manim", "scene": legacy_scene({
        "kind": "flow", "labels": ["Ingresso", "Risultato"]}).model_dump()}
    content = SlideContent(title="Un meccanismo", diagram=diagram).model_dump()
    cached = {"engine": "manim", "asset": "manim-existing.png", "report": {"ok": True},
              "fingerprint": fingerprint(content["diagram"], project)}
    project["slides"] = [{"id": "s1", "revision": 1, "status": "ready",
                          "content": content, "diagram_render": cached}]
    app["store"].asset_path(project["id"], cached["asset"]).write_bytes(photo_bytes())
    app["store"].save_project(project)
    return project


@pytest.mark.asyncio
async def test_upload_and_photo_edit_preserve_manim_without_rerender(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    project = seed_diagram(app)
    original = copy.deepcopy(project["slides"][0])

    async def unexpected_render(*_):
        pytest.fail("Uploading or moving a photo must not render an unchanged diagram")

    monkeypatch.setattr(app["worker"].renderer, "render", unexpected_render)
    async with TestClient(TestServer(app)) as client:
        endpoint = f"/api/projects/{project['id']}/slides/s1"

        def upload_form():
            form = aiohttp.FormData()
            form.add_field("revision", "1")
            form.add_field("file", photo_bytes(), filename="photo.png")
            return form

        response = await client.post(endpoint + "/image", headers=HEADERS, data=upload_form())
        assert response.status == 200, await response.text()
        uploaded = (await response.json())["slide"]
        assert uploaded["content"]["image_id"]
        assert uploaded["content"]["image_origin"] == "upload"
        assert uploaded["content"]["diagram"] == original["content"]["diagram"]
        assert uploaded["diagram_render"] == original["diagram_render"]
        assert uploaded["revision"] == 2
        assert (await client.post(endpoint + "/image", headers=HEADERS, data=upload_form())).status == 409
        assert len(app["store"].project(project["id"])["visual_assets"]) == 1

        edited = uploaded["content"]
        edited["layout"] = "freeform"
        edited["freeform"] = {"visual": {"x": 40, "y": 200, "w": 570, "h": 360},
                              "image": {"x": 650, "y": 200, "w": 570, "h": 360}}
        response = await client.patch(endpoint, headers=HEADERS, json={"revision": 2, "content": edited})
        assert response.status == 200, await response.text()
        saved = await response.json()
        assert saved["revision"] == 3
        assert saved["content"]["freeform"] == edited["freeform"]
        assert saved["content"]["image_id"] == uploaded["content"]["image_id"]
        assert saved["content"]["diagram"] == original["content"]["diagram"]
        assert saved["diagram_render"] == original["diagram_render"]
        assert (await client.patch(endpoint, headers=HEADERS,
                                   json={"revision": 2, "content": edited})).status == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_cache", ["missing_asset", "changed_theme"])
async def test_unchanged_diagram_refreshes_missing_or_outdated_cache(tmp_path, monkeypatch, invalid_cache):
    app = create_app(ROOT, tmp_path / "data")
    project = seed_diagram(app)
    if invalid_cache == "missing_asset":
        app["store"].asset_path(project["id"], "manim-existing.png").unlink()
    else:
        project["background_color"] = "#ff00ff"
        app["store"].save_project(project)
    content = copy.deepcopy(project["slides"][0]["content"])
    content["title"] = "Solo testo modificato"
    calls = []

    async def refreshed_render(pid, diagram, current_project):
        calls.append((pid, diagram))
        return {"engine": "manim", "asset": "manim-refreshed.png",
                "fingerprint": fingerprint(diagram, current_project)}

    monkeypatch.setattr(app["worker"].renderer, "render", refreshed_render)
    async with TestClient(TestServer(app)) as client:
        response = await client.patch(f"/api/projects/{project['id']}/slides/s1", headers=HEADERS,
                                      json={"revision": 1, "content": content})
        assert response.status == 200, await response.text()
        saved = await response.json()
        assert len(calls) == 1
        assert saved["content"]["diagram"] == content["diagram"]
        assert saved["diagram_render"]["asset"] == "manim-refreshed.png"
        assert saved["diagram_render"]["fingerprint"] == fingerprint(content["diagram"], project)


@pytest.mark.asyncio
async def test_cached_diagram_patch_detects_edit_while_receiving_body(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    project = seed_diagram(app)
    content = copy.deepcopy(project["slides"][0]["content"])
    content["title"] = "Modifica da una versione precedente"
    original_request_json = web.Request.json

    async def request_json_after_concurrent_edit(request, *args, **kwargs):
        body = await original_request_json(request, *args, **kwargs)
        latest = app["store"].project(project["id"])
        latest["slides"][0]["revision"] += 1
        latest["slides"][0]["content"]["title"] = "Modifica concorrente"
        app["store"].save_project(latest)
        return body

    monkeypatch.setattr(web.Request, "json", request_json_after_concurrent_edit)
    async with TestClient(TestServer(app)) as client:
        response = await client.patch(f"/api/projects/{project['id']}/slides/s1", headers=HEADERS,
                                      json={"revision": 1, "content": content})
        assert response.status == 409, await response.text()
        saved = app["store"].project(project["id"])["slides"][0]
        assert saved["revision"] == 2
        assert saved["content"]["title"] == "Modifica concorrente"
        assert saved["diagram_render"]["asset"] == "manim-existing.png"


@pytest.mark.asyncio
async def test_changed_diagram_still_renders_and_detects_concurrent_edit(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    project = seed_diagram(app)
    content = copy.deepcopy(project["slides"][0]["content"])
    content["diagram"]["scene"]["title"] = "Diagramma aggiornato"
    calls = []

    async def concurrent_render(pid, diagram, _):
        calls.append(diagram)
        latest = app["store"].project(pid)
        latest["slides"][0]["revision"] += 1
        latest["slides"][0]["content"]["title"] = "Modifica concorrente"
        app["store"].save_project(latest)
        return {"engine": "manim", "asset": "manim-new.png"}

    monkeypatch.setattr(app["worker"].renderer, "render", concurrent_render)
    async with TestClient(TestServer(app)) as client:
        response = await client.patch(f"/api/projects/{project['id']}/slides/s1", headers=HEADERS,
                                      json={"revision": 1, "content": content})
        assert response.status == 409, await response.text()
        assert len(calls) == 1
        saved = app["store"].project(project["id"])["slides"][0]
        assert saved["content"]["title"] == "Modifica concorrente"
        assert saved["diagram_render"]["asset"] == "manim-existing.png"


def test_freeform_accepts_independent_image_with_all_existing_positions():
    keys = ["heading", "visual", "image"] + [f"block-{i}" for i in range(4)] + [f"bullet-{i}" for i in range(5)]
    positions = {key: {"x": 40, "y": 100, "w": 100, "h": 100} for key in keys}
    content = SlideContent(title="Due visuali", layout="freeform", freeform=positions)
    assert content.model_dump()["freeform"] == positions
    with pytest.raises(ValueError):
        SlideContent(title="Chiave non supportata", freeform={"image-2": positions["image"]})


@pytest.mark.parametrize("origin,source_enabled,manim_enabled,expected", [
    ("source", True, True, {"photo.jpg", "manim-existing.png"}),
    ("source", False, True, {"manim-existing.png"}),
    ("upload", False, True, {"photo.jpg", "manim-existing.png"}),
    ("web", False, True, {"photo.jpg", "manim-existing.png"}),
    ("source", True, False, {"photo.jpg"}),
    ("upload", False, False, {"photo.jpg"}),
    ("source", False, False, set()),
])
def test_slidev_copies_photo_and_diagram_independently(
        tmp_path, monkeypatch, origin, source_enabled, manim_enabled, expected):
    assets, output = tmp_path / "source-assets", tmp_path / "slidev"
    assets.mkdir()
    for name in ("photo.jpg", "manim-existing.png"):
        (assets / name).write_bytes(name.encode())
    project = {"title": "Due visuali", "use_source_images": source_enabled,
               "use_manim_diagrams": manim_enabled,
               "visual_assets": [{"id": "photo.jpg", "origin": origin}] if origin != "source" else [],
               "slides": [{"content": {"image_id": "photo.jpg", "image_origin": "source",
                                       "diagram": {"kind": "manim"}},
                           "diagram_render": {"engine": "manim", "asset": "manim-existing.png"}}]}
    # Exercise Python packaging in isolation; browser HTML has separate integration coverage.
    monkeypatch.setattr("h3_slides.slidev.subprocess.run", lambda *_, **__: SimpleNamespace(
        check_returncode=lambda: None, stdout=json.dumps({"markdown": "# Due visuali", "css": ""})))
    write_slidev(project, assets, output)
    copied = {path.name for path in (output / "assets").glob("*")}
    assert copied == expected
    for name in expected:
        assert (output / "assets" / name).read_bytes() == (assets / name).read_bytes()
