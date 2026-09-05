import asyncio
import io
import os
import zipfile
import copy
from pathlib import Path
from types import SimpleNamespace

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from pypdf import PdfReader
import pytest

from h3_slides.app import create_app, run_child
from h3_slides.models import Generation, ProjectInput, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker
from h3_slides.web_images import WebImages, open_license, plain, store_image

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


def png():
    raw = io.BytesIO()
    Image.new("RGB", (640, 400), "navy").save(raw, format="PNG")
    return raw.getvalue()


def test_image_validation_and_licences(tmp_path):
    for license in ("Public domain", "CC0 1.0", "CC BY-SA 4.0", "CC-BY-3.0"):
        assert open_license(license)
    for license in ("", "CC BY-NC 4.0", "CC BY-ND 4.0", "all rights reserved"):
        assert not open_license(license)
    assert plain('<a href="javascript:x">An author</a>') == "An author"
    db = Store(tmp_path)
    try:
        p = db.create(ProjectInput().model_dump())
        asset = store_image(db, p["id"], png(), "../../untrusted.png")
        assert asset["id"].endswith(".jpg") and "/" not in asset["id"]
        assert Image.open(db.asset_path(p["id"], asset["id"])).format == "JPEG"
        with pytest.raises(ValueError, match="non valida"):
            store_image(db, p["id"], b"not a picture", "broken.jpg")
        with pytest.raises(ValueError, match="20 MB"):
            store_image(db, p["id"], b"x" * (20*1024*1024+1), "large.jpg")
    finally:
        db.db.close()


@pytest.mark.asyncio
async def test_licensed_download_and_public_destination_guards(tmp_path, monkeypatch):
    db = Store(tmp_path)
    try:
        p = db.create(ProjectInput().model_dump())
        search = WebImages()
        meta = {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<b>Author</b>"},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"}}
        info = {"mime": "image/png", "width": 640, "height": 400,
                "extmetadata": meta, "descriptionurl": "https://commons.wikimedia.org/wiki/File:Test.png",
                "thumburl": "https://upload.wikimedia.org/test.png"}
        async def candidates(*_):
            return [("Bad", {**info, "extmetadata": {}}), ("File:Test.png", info)]
        async def fetch(_, url, limit):
            assert url == info["thumburl"]
            return png()
        monkeypatch.setattr(search, "candidates", candidates)
        monkeypatch.setattr(search, "fetch", fetch)
        asset = await search.acquire(db, p["id"], "Rivoluzione francese")
        assert asset["origin"] == "web" and asset["author"] == "Author"
        assert asset["license"] == "CC BY-SA 4.0"
        for url in ("http://127.0.0.1/private", "https://example.com/image.jpg",
                    "https://user:pass@upload.wikimedia.org/test"):
            with pytest.raises(ValueError):
                await WebImages().fetch(None, url, 1024)
    finally:
        db.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["download", "missing", "offline", "source", "disabled", "manim", "existing"])
async def test_worker_images_are_optional_and_do_not_replace_source_or_manim(tmp_path, mode, monkeypatch):
    db = Store(tmp_path)
    try:
        p = db.create(ProjectInput(prompt="Spiega il soggetto", count=1, text_density="brief",
            use_web_images=mode != "disabled", use_source_images=True,
            use_manim_diagrams=mode == "manim").model_dump())
        source_image = store_image(db, p["id"], png(), "Figura dal libro")
        p["sources"] = [{"id": "doc", "name": "Libro", "text": "Un testo utile.", "images": [source_image]}]
        if mode == "existing":
            p["visual_assets"] = [store_image(db, p["id"], png(), "Immagine caricata")]
            p["use_source_images"] = False
        db.save_project(p)
        w = Worker(db, SimpleNamespace())
        class LLM:
            def __init__(self, *_): pass
            async def prepare(self): pass
            async def json(self, prompt, **kwargs):
                if "Proponi esattamente" in prompt:
                    return {"slides": [{"title": "Soggetto", "layout": "content"}]}
                return SlideContent(title="Soggetto", bullets=["Una spiegazione."], image_query="Soggetto illustrato",
                    image_id=(source_image["id"] if mode == "source" else
                              p["visual_assets"][0]["id"] if mode == "existing" else "")).model_dump()
        async def context(*_):
            return "Dati del documento", [{"image_id": source_image["id"], "source": "Libro"}]
        calls = []
        async def acquire(*_):
            calls.append(1)
            if mode == "offline":
                raise OSError("Offline")
            if mode == "download":
                return store_image(db, p["id"], png(), "Foto", origin="web", author="Author",
                    license="CC BY 4.0", source="https://commons.wikimedia.org/wiki/File:Foto",
                    license_url="https://creativecommons.org/licenses/by/4.0/")
            return None
        async def diagram(*_, **__):
            return {"kind": "manim", "labels": [], "brief": "Un processo", "scene": None}, {
                "engine": "manim", "asset": "manim-test.png"}
        w.clients, w.sources_context, w.web_images.acquire = LLM, context, acquire
        monkeypatch.setattr("h3_slides.worker.design_diagram", diagram)
        job = w.submit(p["id"], Generation(provider={"model": "fake"}, prompt="Spiega", count=1))
        await w.tasks[job["id"]]
        assert db.job(job["id"])["status"] == "completed", db.job(job["id"])["events"]
        result = db.project(p["id"])
        content = result["slides"][0]["content"]
        assert len(result["sources"]) == 1
        assert bool(calls) == (mode in ("download", "missing", "offline"))
        assert content["image_placeholder"] == (mode in ("missing", "offline"))
        if mode == "source":
            assert content["image_id"] == source_image["id"]
        if mode == "existing":
            assert content["image_id"] == p["visual_assets"][0]["id"]
            assert content["image_origin"] == "upload"
        if mode == "download":
            assert len(result["visual_assets"]) == 1 and content["image_origin"] == "web"
            assert "commons.wikimedia.org" in content["notes"]
        if mode == "manim":
            assert result["slides"][0]["diagram_render"]["engine"] == "manim"
    finally:
        db.db.close()


def seed_slide(store):
    p = store.create(ProjectInput(title="Immagini indipendenti", prompt="Test immagini",
        use_web_images=True, use_source_images=True, text_density="brief").model_dump())
    p["slides"] = [{"id": "slide-test", "revision": 1, "status": "ready", "content": SlideContent(
        title="Un'immagine da completare", bullets=["Testo che resta invariato."], image_origin="web",
        image_placeholder=True, image_query="Paesaggio italiano", layout="freeform",
        freeform={"heading": {"x": 48, "y": 60, "w": 1184, "h": 120},
                  "bullet-0": {"x": 48, "y": 200, "w": 500, "h": 400},
                  "visual": {"x": 650, "y": 200, "w": 580, "h": 400}}).model_dump()}]
    store.save_project(p)
    return p


@pytest.mark.asyncio
async def test_upload_persists_without_document_or_model_and_checks_revision(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    p = seed_slide(app["store"])
    monkeypatch.setattr(app["worker"], "active", lambda: True)  # Another slide may still be running.
    async with TestClient(TestServer(app)) as client:
        def form(revision=1, raw=None):
            data = aiohttp.FormData()
            data.add_field("revision", str(revision))
            data.add_field("file", png() if raw is None else raw, filename="uploaded.png")
            return data
        endpoint = f"/api/projects/{p['id']}/slides/slide-test/image"
        assert (await client.post(endpoint, data=form())).status == 403
        invalid = await client.post(endpoint, data=form(raw=b"bad"), headers=HEADERS)
        assert invalid.status == 400 and app["store"].project(p["id"])["slides"][0]["revision"] == 1
        response = await client.post(endpoint, data=form(), headers=HEADERS)
        assert response.status == 200, await response.text()
        result = await response.json()
        assert result["slide"]["revision"] == 2
        assert not result["slide"]["content"]["image_placeholder"]
        assert result["slide"]["content"]["freeform"] == p["slides"][0]["content"]["freeform"]
        saved = app["store"].project(p["id"])
        assert saved["sources"] == [] and len(saved["visual_assets"]) == 1
        assert (await client.get(f"/api/assets/{p['id']}/{result['visual_asset']['id']}")).status == 200
        assert (await client.post(endpoint, data=form(), headers=HEADERS)).status == 409
        assert len(app["store"].project(p["id"])["visual_assets"]) == 1
        edited = result["slide"]["content"]
        edited["image_origin"] = "source"  # Server trusts its own registry.
        response = await client.patch(endpoint.removesuffix("/image"), headers=HEADERS,
                                      json={"revision": 2, "content": edited})
        assert response.status == 200
        assert (await response.json())["content"]["image_origin"] == "upload"


@pytest.mark.asyncio
async def test_image_placeholder_browser(tmp_path):
    app = create_app(ROOT, tmp_path / "data")
    p = seed_slide(app["store"])
    async with TestClient(TestServer(app)) as client:
        await run_child(app, [ROOT / "runtime/node/node.exe", ROOT / "tests/images-ui.mjs",
                             str(client.make_url("/")), p["id"]], ROOT, tmp_path / "images-ui.log",
                        dict(os.environ), timeout=90)
        saved = app["store"].project(p["id"])
        assert len(saved["visual_assets"]) == 1 and saved["sources"] == []
        assert app["store"].jobs() == []


@pytest.mark.asyncio
async def test_images_and_placeholder_export_to_pdf_pptx_slidev(tmp_path):
    app = create_app(ROOT, tmp_path / "data")
    p = seed_slide(app["store"])
    p["use_source_images"] = False
    p["use_web_images"] = False  # Disabling new searches must not hide saved photos.
    web_asset = store_image(app["store"], p["id"], png(), "Fotografia", origin="web",
        author="Autore della fotografia", license="CC BY-SA 4.0",
        source="https://commons.wikimedia.org/wiki/File:Test.png",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/")
    upload = store_image(app["store"], p["id"], png(), "Caricata a mano")
    p["visual_assets"] = [web_asset, upload]
    for i, asset in enumerate(p["visual_assets"]):
        slide = copy.deepcopy(p["slides"][0])
        slide["id"] = f"photo-{i}"
        slide["content"].update(image_id=asset["id"], image_origin=asset["origin"], image_placeholder=False)
        p["slides"].append(slide)
    app["store"].save_project(p)
    async with TestClient(TestServer(app)) as client:
        for fmt in ("pdf", "pptx", "slidev"):
            response = await client.post(f"/api/projects/{p['id']}/export/{fmt}", headers=HEADERS, json={})
            payload = await response.json()
            assert response.status == 200, payload
            download = await client.get(payload["url"])
            raw = await download.read()
            if fmt == "pdf":
                pdf = PdfReader(io.BytesIO(raw))
                assert len(pdf.pages) == 3
                assert "Immagine da inserire" in pdf.pages[0].extract_text()
                assert "CC BY-SA 4.0" in pdf.pages[1].extract_text()
                assert len(pdf.pages[1].images) > 0 and len(pdf.pages[2].images) > 0
            else:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    if fmt == "pptx":
                        assert b"Immagine da inserire" in archive.read("ppt/slides/slide1.xml")
                        assert b"CC BY-SA 4.0" in archive.read("ppt/slides/slide2.xml")
                        assert b"commons.wikimedia.org" in archive.read("ppt/notesSlides/notesSlide2.xml")
                        assert len([n for n in archive.namelist() if n.startswith("ppt/media/") and n.endswith(".jpg")]) >= 2
                    else:
                        assert "assets/" + web_asset["id"] in archive.namelist()
                        assert "assets/" + upload["id"] in archive.namelist()
                        assert b"image-placeholder" in archive.read("slides.md")
                        assert b"CC BY-SA 4.0" in archive.read("slides.md")
