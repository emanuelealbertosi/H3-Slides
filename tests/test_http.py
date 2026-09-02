import asyncio
import io
import os
from pathlib import Path
import zipfile
import aiohttp
from aiohttp.test_utils import TestClient, TestServer
from pypdf import PdfReader
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
                            bullets=["Importa il documento.", "Rivedi ogni slide.", "Esporta nel formato che ti serve."],
                            sources=["fonte.md"], animation="reveal").model_dump()


@pytest.mark.asyncio
async def test_api_and_real_exports(tmp_path):
    app = create_app(ROOT, tmp_path / "data")
    app["worker"].clients = SingleSlideLLM
    async with TestClient(TestServer(app)) as client:
        denied = await client.post("/api/projects", json={"title": "Denied"})
        assert denied.status == 403
        response = await client.post("/api/projects", headers=HEADERS, json={"title": "Verifica H3-slides", "prompt":"Spiega il flusso", "count":1})
        assert response.status == 201
        p = await response.json()
        pid = p["id"]
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
        stale = await client.patch(f"/api/projects/{pid}/slides/{slide['id']}", headers=HEADERS,
                                   json={"revision":0,"content":slide["content"]})
        assert stale.status == 409
        preview = await client.post(f"/api/projects/{pid}/slidev", headers=HEADERS, json={})
        assert preview.status == 200, await preview.json()
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
                        assert b"Le fonti diventano slide" in z.read("ppt/slides/slide1.xml")
                    if fmt == "slidev":
                        assert b"Le fonti diventano slide" in z.read("slides.md")
                    if fmt == "manim":
                        assert "presentazione.mp4" in z.namelist()
                        assert "presentazione.html" in z.namelist()
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(ROOT / "runtime/browsers"))
        await run_child(app, [ROOT / "runtime/node/node.exe", ROOT / "tests/ui-smoke.mjs",
                             str(client.make_url("/")), pid], ROOT, tmp_path / "browser.log", env, timeout=90)
