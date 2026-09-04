import asyncio
import io
import json
import os
import struct
from pathlib import Path
import zipfile
import aiohttp
from aiohttp.test_utils import TestClient, TestServer
from pypdf import PdfReader
from PIL import Image
import pytest
from h3_slides.app import create_app, run_child
from h3_slides.models import SlideContent

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


class SingleSlideLLM:
    def __init__(self, *args):
        pass
    async def prepare(self):
        pass
    async def json(self, prompt, **kwargs):
        await asyncio.sleep(.03)
        if "Estrai fatti" in prompt:
            return {"summary": "Le fonti sono salvate sul computer."}
        if "Proponi esattamente" in prompt:
            return {"slides": [{"title": "Il tuo studio locale", "purpose": "Spiegare il flusso"}]}
        return SlideContent(title="Le fonti diventano slide",
                            subtitle="Un progetto locale, pronto da modificare",
                            blocks=[
                              {"heading":"Dal documento alla slide", "text":"Il documento viene analizzato per selezionare i passaggi pertinenti alla richiesta. I contenuti diventano paragrafi visibili dentro riquadri, che puoi correggere direttamente prima di esportare la presentazione."},
                              {"heading":"Il controllo resta tuo", "kind":"example", "text":"Per esempio, puoi precisare una spiegazione aggiungendo un caso concreto e la sua conseguenza. La modifica viene salvata nel progetto e si ritrova anche nell’esportazione, senza dover riscrivere la presentazione."}],
                            sources=["fonte.md"], animation="reveal").model_dump()


@pytest.mark.asyncio
async def test_api_generate_without_upload(tmp_path):
    app = create_app(ROOT, tmp_path / "data")
    app["worker"].clients = SingleSlideLLM
    class NoSearch:
        async def collect(self, *args, **kwargs):
            pytest.fail("La ricerca disattivata non deve effettuare richieste")
    app["worker"].researcher = NoSearch()
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/projects", headers=HEADERS,
                                     json={"title":"La rivoluzione francese", "prompt":"La rivoluzione francese", "count":1})
        p = await response.json()
        response = await client.post(f"/api/projects/{p['id']}/generate", headers=HEADERS,
                                     json={"prompt":"La rivoluzione francese", "count":1,
                                           "provider":{"mode":"local", "model":"test"}})
        assert response.status == 202
        job = await response.json()
        await app["worker"].tasks[job["id"]]
        assert app["store"].job(job["id"])["status"] == "completed"
        generated = app["store"].project(p["id"])
        assert generated["sources"] == []
        assert generated["slides"][0]["content"]["sources"] == []
        assert generated["slides"][0]["content"]["notes"].startswith("Origine: conoscenza del modello")


@pytest.mark.asyncio
async def test_remove_source_deletes_local_derivatives_and_unlinks_slide_image(tmp_path):
    app = create_app(ROOT, tmp_path / "data")
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/projects", headers=HEADERS,
                                     json={"title":"Fonti eliminabili", "prompt":"Test"})
        project = await response.json()
        pid = project["id"]
        raw = io.BytesIO()
        Image.new("RGB", (40, 30), "navy").save(raw, format="PNG")
        form = aiohttp.FormData()
        form.add_field("file", raw.getvalue(), filename="schema.png")
        response = await client.post(f"/api/projects/{pid}/sources", headers=HEADERS, data=form)
        assert response.status == 200
        uploaded = await response.json()
        source = uploaded["sources"][0]
        image_id = source["images"][0]["id"]
        image_path = app["store"].asset_path(pid, image_id)
        assert image_path.is_file()
        cache = app["store"].asset_path(pid, "rag-obsoleto.json")
        cache.write_text('{"context":"documento rimosso"}', encoding="utf-8")
        preview_copy = app["store"].root / "slidev" / pid / "assets" / image_id
        preview_copy.parent.mkdir(parents=True)
        preview_copy.write_bytes(image_path.read_bytes())
        stored = app["store"].project(pid)
        stored["slides"] = [{"id":"s1", "revision":1, "status":"ready", "purpose":"",
                             "content":SlideContent(title="Slide", image_id=image_id,
                                                    sources=["schema.png"]).model_dump()}]
        app["store"].save_project(stored)

        response = await client.delete(
            f"/api/projects/{pid}/sources/{source['id']}", headers=HEADERS)
        assert response.status == 200
        updated = await response.json()
        assert updated["sources"] == []
        assert updated["slides"][0]["content"]["image_id"] == ""
        assert updated["slides"][0]["content"]["sources"] == ["schema.png"]
        assert updated["slides"][0]["revision"] == 2
        assert not image_path.exists()
        assert not cache.exists()
        assert not preview_copy.exists()
        again = await client.delete(
            f"/api/projects/{pid}/sources/{source['id']}", headers=HEADERS)
        assert again.status == 404


@pytest.mark.asyncio
async def test_api_and_real_exports(tmp_path):
    app = create_app(ROOT, tmp_path / "data")
    app["worker"].clients = SingleSlideLLM
    # Browser/admin checks must work in a clean checkout with no personal GGUFs.
    model_dir = tmp_path / "test-models"
    model_dir.mkdir()
    (model_dir / "test.gguf").write_bytes(struct.pack("<4sIQQ", b"GGUF", 3, 1, 1))
    app["manager"].config = {**app["manager"].config, "model_roots":[str(model_dir)]}
    async with TestClient(TestServer(app)) as client:
        denied = await client.post("/api/projects", json={"title": "Denied"})
        assert denied.status == 403
        response = await client.post("/api/projects", headers=HEADERS, json={"title": "Verifica H3-slides", "prompt":"Spiega il flusso", "count":1})
        assert response.status == 201
        p = await response.json()
        pid = p["id"]
        response = await client.patch(f"/api/projects/{pid}", headers=HEADERS,
                                      json={"use_manim_diagrams": True, "font": "Segoe UI",
                                            "background_color": "#f7f4ee", "accent_color": "#2c6a59"})
        assert response.status == 200
        assert (await response.json())["title"] == "Verifica H3-slides"
        night = next(p["values"] for p in json.loads((ROOT / "static/theme-presets.json").read_text(encoding="utf-8"))
                     if p["name"].startswith("Notte"))
        themed = await client.patch(f"/api/projects/{pid}", headers=HEADERS, json=night)
        assert themed.status == 200
        admin = await client.get("/api/admin/llm")
        assert admin.status == 200
        assert "context_size" in (await admin.json())["loading_schema"]["properties"]
        form = aiohttp.FormData()
        form.add_field("file", b"# Il flusso\nLe fonti sono salvate sul computer.", filename="fonte.md")
        response = await client.post(f"/api/projects/{pid}/sources", headers=HEADERS, data=form)
        assert response.status == 200
        response = await client.post(f"/api/projects/{pid}/generate", headers=HEADERS,
                                     json={"prompt":"Spiega il flusso", "count":1,
                                           "provider":{"mode":"local","model":"test"}})
        job = await response.json()
        assert response.status == 202
        await app["worker"].tasks[job["id"]]
        assert app["store"].job(job["id"])["status"] == "completed"
        project = app["store"].project(pid)
        slide = project["slides"][0]
        slide["content"]["diagram"] = {"kind": "flow", "labels": ["Fonti", "Slide", "Presentazione"]}
        changed = await client.patch(f"/api/projects/{pid}/slides/{slide['id']}", headers=HEADERS,
                                      json={"revision": slide["revision"], "content": slide["content"]})
        assert changed.status == 200
        stale = await client.patch(f"/api/projects/{pid}/slides/{slide['id']}", headers=HEADERS,
                                   json={"revision":0,"content":slide["content"]})
        assert stale.status == 409
        preview = await client.post(f"/api/projects/{pid}/slidev", headers=HEADERS, json={})
        assert preview.status == 200, await preview.json()
        preview_url = (await preview.json())["url"]
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(ROOT / "runtime/browsers"))
        await run_child(app, [ROOT / "runtime/node/node.exe", ROOT / "tests/slidev-smoke.mjs",
                             preview_url], ROOT, tmp_path / "slidev-browser.log", env, timeout=90)
        for fmt in ("pptx", "pdf", "slidev", "manim"):
            response = await client.post(f"/api/projects/{pid}/export/{fmt}", headers=HEADERS, json={})
            payload = await response.json()
            assert response.status == 200, payload
            download = await client.get(payload["url"])
            assert download.status == 200
            raw = await download.read()
            assert len(raw) > (100 if fmt == "slidev" else 500)
            if fmt == "pdf":
                assert len(PdfReader(io.BytesIO(raw)).pages) == 1
            else:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    if fmt == "pptx":
                        xml = z.read("ppt/slides/slide1.xml")
                        assert b"Le fonti diventano slide" in xml
                        assert b"Il documento viene analizzato" in xml
                        assert b"Per esempio, puoi precisare" in xml
                        assert b'b="1"' in xml
                        assert b'val="213659"' in xml
                        assert b'val="ffffff"' in xml.lower()
                    if fmt == "slidev":
                        assert b"Le fonti diventano slide" in z.read("slides.md")
                        assert b"prose-box" in z.read("slides.md")
                        assert b".slide-frame" in z.read("style.css")
                    if fmt == "manim":
                        assert "presentazione.mp4" in z.namelist()
                        assert "presentazione.html" in z.namelist()
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(ROOT / "runtime/browsers"))
        await run_child(app, [ROOT / "runtime/node/node.exe", ROOT / "tests/ui-smoke.mjs",
                             str(client.make_url("/")), pid], ROOT, tmp_path / "browser.log", env, timeout=90)
