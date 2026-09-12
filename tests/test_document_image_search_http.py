"""Local-document image picker HTTP contract; synthetic assets and no model calls."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import pytest

from h3_slides.app import create_app
from h3_slides.llm import LLM
from h3_slides.models import ProjectInput, SlideContent


ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


def fixture_app(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    store = app["store"]
    project = store.create(ProjectInput(title="Scelta locale", count=2, use_source_images=False,
                                       use_manim_diagrams=True).model_dump())
    source = {
        "id": "document-source", "library_id": "original-library-document",
        "name": "Libro locale.pdf", "kind": "pdf", "text": "Testo privato sintetico.", "warnings": [],
        "page_index_file": "page-index.json", "selection": {"pdf_pages": [2], "scope_mode": "auto"},
        "images": [
            {"id": "stale-page-1.png", "label": "Figura vecchia · Libro locale.pdf · pagina PDF 1",
             "kind": "figure", "pdf_page": 1},
            {"id": "triangle-page-2.png", "label": "Figura triangolo · Libro locale.pdf · pagina PDF 2",
             "kind": "figure", "pdf_page": 2},
            {"id": "unicorn-page-2.png", "label": "Figura unicorno · Libro locale.pdf · pagina PDF 2",
             "kind": "figure", "pdf_page": 2},
            {"id": "full-page-2.png", "label": "Libro locale.pdf · pagina PDF 2",
             "kind": "page", "pdf_page": 2},
        ],
    }
    content = SlideContent(
        title="Titolo da conservare", subtitle="Sottotitolo da conservare", notes="Note originali.",
        blocks=[{"heading": "Spiegazione", "text": "Un contenuto originale indipendente dall'immagine."}],
        sources=["Attribuzione testuale precedente"], image_placeholder=True, image_query="Ricerca precedente",
        layout="freeform", freeform={"heading": {"x": 48, "y": 60, "w": 1184, "h": 100},
            "block-0": {"x": 48, "y": 200, "w": 380, "h": 400},
            "visual": {"x": 448, "y": 200, "w": 370, "h": 400},
            "image": {"x": 838, "y": 200, "w": 394, "h": 400}},
        diagram={"kind": "manim", "brief": "Diagramma da conservare"},
    ).model_dump()
    project["sources"] = [source]
    project["visual_assets"] = [{"id": "old-upload.png", "origin": "upload", "label": "Risorsa precedente"}]
    project["slides"] = [
        {"id": sid, "revision": 5, "status": "ready", "content": deepcopy(content),
         "diagram_render": {"engine": "manim", "asset": "existing-manim.png", "fingerprint": "untouched"}}
        for sid in ("slide", "other-slide")
    ]
    store.save_project(project)
    for index, name in enumerate([image["id"] for image in source["images"]] + ["existing-manim.png", "old-upload.png"]):
        Image.new("RGB", (640, 400), (20 + index * 20, 80, 140)).save(store.asset_path(project["id"], name))
    store.asset_path(project["id"], "page-index.json").write_text(json.dumps({"pages": [
        {"pdf_page": 1, "text": "Pagina esclusa dalla selezione corrente."},
        {"pdf_page": 2, "text": "Pagina pertinente con figure e illustrazioni."},
    ]}), encoding="utf-8")

    async def forbidden(*args, **kwargs):
        pytest.fail("La ricerca locale non deve invocare rete, LLM o rendering")

    for method in ("search", "download", "preview"):
        monkeypatch.setattr(app["image_search"], method, forbidden)
    monkeypatch.setattr(LLM, "prepare", forbidden)
    monkeypatch.setattr(app["manager"], "start", forbidden)
    monkeypatch.setattr(app["worker"].renderer, "render", forbidden)
    return app, store, store.project(project["id"])


def endpoint(project, sid="slide"):
    return f"/api/projects/{project['id']}/slides/{sid}/image-search"


def files_digest(store, pid):
    root = store.root / "assets" / pid
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


async def search(client, base, **values):
    response = await client.post(base, headers=HEADERS,
                                json={"source": "document", "query": "", "include_pages": False, **values})
    assert response.status == 200, await response.text()
    result = await response.json()
    assert result["search_id"].startswith("doc-")
    return result


def chosen(page, text="unicorno"):
    return next(row for row in page["results"] if text in row["label"])


def selection(page, row, revision=5):
    return {"search_id": page["search_id"], "result_id": row["id"], "revision": revision}


@pytest.mark.asyncio
async def test_document_search_scope_ranking_and_page_preview_opt_in(tmp_path, monkeypatch):
    app, store, before = fixture_app(tmp_path, monkeypatch)
    initial_files, changes = files_digest(store, before["id"]), store.db.total_changes
    async with TestClient(TestServer(app)) as client:
        base = endpoint(before)
        page = await search(client, base)
        assert len(page["results"]) == 2
        assert page["page"] == 0 and not page["has_more"]
        assert all(row["pdf_page"] == 2 and row["kind"] == "figure" for row in page["results"])
        for row in page["results"]:
            assert row["document"] == "Libro locale.pdf"
            assert row["image_provider"] == "Documento locale"
            assert not row["license"] and not row["author"]
            assert not ({"path", "download_url", "preview", "image_id"} & row.keys())
        ranked = await search(client, base, query="unicorno")
        assert "unicorno" in ranked["results"][0]["label"]
        assert len(ranked["results"]) == 2, "Document query ranks; it must not hide other usable figures"
        with_pages = await search(client, base, include_pages=True)
        assert len(with_pages["results"]) == 3
        assert {row["kind"] for row in with_pages["results"]} == {"figure", "page"}
        assert all(row["pdf_page"] == 2 for row in with_pages["results"])
        assert store.db.total_changes == changes
        assert store.project(before["id"]) == before
        assert files_digest(store, before["id"]) == initial_files


@pytest.mark.asyncio
async def test_document_thumbnail_is_local_jpeg_without_database_or_asset_writes(tmp_path, monkeypatch):
    app, store, before = fixture_app(tmp_path, monkeypatch)
    async with TestClient(TestServer(app)) as client:
        base = endpoint(before)
        page = await search(client, base)
        row = chosen(page)
        changes, initial_files = store.db.total_changes, files_digest(store, before["id"])
        response = await client.get(f"{base}/{page['search_id']}/{row['id']}/preview")
        assert response.status == 200, await response.text() if response.status != 200 else ""
        assert response.content_type == "image/jpeg"
        with Image.open(io.BytesIO(await response.read())) as image:
            assert image.format == "JPEG"
            assert 0 < image.width <= 400 and 0 < image.height <= 300
        assert store.db.total_changes == changes
        assert store.project(before["id"]) == before
        assert files_digest(store, before["id"]) == initial_files


@pytest.mark.asyncio
async def test_document_selection_persists_source_identity_without_copying_or_rerendering(tmp_path, monkeypatch):
    app, store, before = fixture_app(tmp_path, monkeypatch)
    initial_files = files_digest(store, before["id"])
    async with TestClient(TestServer(app)) as client:
        base = endpoint(before)
        page = await search(client, base)
        row = chosen(page)
        response = await client.post(base + "/select", headers=HEADERS, json=selection(page, row))
        assert response.status == 200, await response.text()
        result = await response.json()
        assert result["source_image"]["id"] == "unicorn-page-2.png"
        assert result["source_image"]["pdf_page"] == 2
        assert result["use_source_images"] is True
        saved = store.project(before["id"])
        reload = await client.get(f"/api/projects/{before['id']}")
        assert (await reload.json())["slides"] == saved["slides"]
        slide = saved["slides"][0]
        assert result["slide"] == slide
        assert saved["use_source_images"] is True
        assert saved["visual_assets"] == before["visual_assets"]
        assert saved["sources"] == before["sources"]
        assert saved["slides"][1] == before["slides"][1]
        assert slide["revision"] == 6
        assert slide["diagram_render"] == before["slides"][0]["diagram_render"]
        assert slide["content"]["image_id"] == "unicorn-page-2.png"
        assert slide["content"]["image_origin"] == "source"
        assert slide["content"]["image_placeholder"] is False
        for key, value in before["slides"][0]["content"].items():
            if key not in ("image_id", "image_origin", "image_placeholder", "image_query"):
                assert slide["content"][key] == value
        assert files_digest(store, before["id"]) == initial_files
        assert (await client.post(base + "/select", headers=HEADERS, json=selection(page, row))).status == 409
        assert store.project(before["id"])["slides"] == saved["slides"]

        # The shared export renderer consumes the source asset and original
        # document attribution directly; no browser/PDF/PPTX rendering is needed.
        bundled_node = ROOT / "runtime" / "node" / "node.exe"
        node = str(bundled_node) if bundled_node.is_file() else shutil.which("node")
        assert node, "Node is required by the app's existing export renderer"
        script = """import {slideHTML,visualFor} from './static/deck.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;
const p=JSON.parse(raw),s=p.slides[0],v=visualFor(p,s.content,s);
process.stdout.write(JSON.stringify({visual:v,html:slideHTML(p,s,0,{image:'assets/'+v.photo,diagram:'assets/'+v.diagramAsset})}));
"""
        rendered = subprocess.run([node, "--input-type=module", "-e", script], cwd=ROOT,
            input=json.dumps(saved), capture_output=True, text=True, encoding="utf-8", timeout=20, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        exported = json.loads(rendered.stdout)
        assert exported["visual"]["photo"] == "unicorn-page-2.png"
        assert exported["visual"]["diagramAsset"] == "existing-manim.png"
        assert 'src="assets/unicorn-page-2.png"' in exported["html"]
        assert 'alt="Figura unicorno · Libro locale.pdf · pagina PDF 2"' in exported["html"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted-source", "replaced-source", "changed-page-selection", "removed-image"])
async def test_document_results_are_rechecked_after_source_changes(tmp_path, monkeypatch, change):
    app, store, project = fixture_app(tmp_path, monkeypatch)
    async with TestClient(TestServer(app)) as client:
        base = endpoint(project)
        page = await search(client, base)
        row = chosen(page)
        updated = store.project(project["id"])
        if change == "deleted-source":
            updated["sources"] = []
        elif change == "replaced-source":
            updated["sources"][0]["id"] = "different-attached-source"
            updated["sources"][0]["library_id"] = "different-library-document"
        elif change == "changed-page-selection":
            updated["sources"][0]["selection"]["pdf_pages"] = [1]
        else:
            updated["sources"][0]["images"] = [image for image in updated["sources"][0]["images"]
                                               if image["id"] != "unicorn-page-2.png"]
        store.save_project(updated)
        before = store.project(project["id"])
        changes, initial_files = store.db.total_changes, files_digest(store, project["id"])
        preview = await client.get(f"{base}/{page['search_id']}/{row['id']}/preview")
        assert preview.status in (400, 404), await preview.text()
        selected = await client.post(base + "/select", headers=HEADERS, json=selection(page, row))
        assert selected.status in (400, 404), await selected.text()
        assert store.db.total_changes == changes
        assert store.project(project["id"]) == before
        assert files_digest(store, project["id"]) == initial_files


@pytest.mark.asyncio
async def test_document_result_ids_cannot_cross_project_or_slide_scope(tmp_path, monkeypatch):
    app, store, project = fixture_app(tmp_path, monkeypatch)
    other = store.create(ProjectInput(title="Altro progetto").model_dump())
    other["slides"] = [deepcopy(project["slides"][0])]
    store.save_project(other)
    async with TestClient(TestServer(app)) as client:
        page = await search(client, endpoint(project))
        row = chosen(page)
        changes = store.db.total_changes
        for base in (endpoint(project, "other-slide"), endpoint(other)):
            response = await client.get(f"{base}/{page['search_id']}/{row['id']}/preview")
            assert response.status in (400, 404), await response.text()
            response = await client.post(base + "/select", headers=HEADERS, json=selection(page, row))
            assert response.status in (400, 404), await response.text()
        assert store.db.total_changes == changes
        assert store.project(project["id"])["slides"] == project["slides"]
        assert store.project(other["id"])["slides"] == other["slides"]


@pytest.mark.asyncio
async def test_document_picker_rejects_missing_security_header_and_client_paths(tmp_path, monkeypatch):
    app, store, project = fixture_app(tmp_path, monkeypatch)
    async with TestClient(TestServer(app)) as client:
        base = endpoint(project)
        assert (await client.post(base, json={"source": "document"})).status == 403
        for forbidden in ("path", "url", "image_id"):
            response = await client.post(base, headers=HEADERS,
                json={"source": "document", forbidden: "../../outside.png"})
            assert response.status == 400
        page = await search(client, base)
        row = chosen(page)
        changes = store.db.total_changes
        for forbidden in ("path", "url", "image_id"):
            response = await client.post(base + "/select", headers=HEADERS,
                json={**selection(page, row), forbidden: "../../outside.png"})
            assert response.status == 400
        stale = await client.post(base + "/select", headers=HEADERS, json=selection(page, row, revision=4))
        assert stale.status == 409
        assert store.db.total_changes == changes
        assert store.project(project["id"])["slides"] == project["slides"]
