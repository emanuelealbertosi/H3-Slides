import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer
from pydantic import ValidationError

from h3_slides.app import create_app
from h3_slides.models import ProjectInput, SlideContent
from h3_slides.page_v2 import PageSpec, PageStream
from h3_slides.theme_designer import ThemeDesignRequest, page_theme_brief
from h3_slides.themes import ThemeDesign, ThemeLibrary, ThemePreset
from h3_slides.models import Generation, Provider
from h3_slides.storage import Store
from h3_slides.worker import Worker
from h3_slides.worker_v2 import run_pages

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}
IDENTITY = {
    "visual_family": "editorial", "background_style": "gradient",
    "secondary_color": "#f4ede1", "heading_font": "Georgia",
    "shadow_style": "lifted", "decoration": "stripe",
    "design_note": "Poche superfici, citazioni e titoli editoriali.",
    "title_size": 48, "body_size": 26, "example_color": "#eef2ff",
}
PRESET = {"name": "Carta e luce", "values": {"background_color": "#faf7f1", "theme_design": IDENTITY}}


def test_rich_theme_roundtrip_and_legacy_defaults(tmp_path):
    ThemeLibrary(tmp_path).save(PRESET)
    saved = ThemeLibrary(tmp_path).list()[0]
    project = ProjectInput(title="Tema", **saved["values"])
    assert project.theme_design.model_dump() == ThemePreset.model_validate(PRESET).values.theme_design.model_dump()
    assert ProjectInput.model_validate(project.model_dump()).theme_design.heading_font == "Georgia"
    assert ThemeDesign().visual_family == "classic"
    assert ThemeDesign().background_style == "flat"


@pytest.mark.parametrize("field,value", [
    ("visual_family", "unregistered"), ("background_style", "image"),
    ("secondary_color", "blue"), ("heading_font", "Unknown Font"),
    ("shadow_style", "custom"), ("decoration", "custom"), ("design_note", "a"*401),
])
def test_theme_tokens_remain_bounded(field, value):
    with pytest.raises(ValidationError):
        ThemeDesign.model_validate({field: value})


def test_planner_receives_actual_tokens_not_provider_or_sources():
    brief = page_theme_brief({**PRESET["values"], "api_key": "private", "sources": ["private source"]})
    value = json.loads(brief)
    assert value["family"] == "editorial"
    assert value["heading_font"] == "Georgia"
    assert value["tokens"]["example_color"] == "#eef2ff"
    assert value["tokens"]["design_note"] == IDENTITY["design_note"]
    assert "private" not in brief and len(brief) < 1800


def test_planner_matches_automatic_family_font_and_base_palette():
    value = json.loads(page_theme_brief({"theme": "ink", "background_color": "", "accent_color": "",
                                       "font": "Arial", "theme_design": {"visual_family": "editorial"}}))
    assert value["heading_font"] == "Georgia"
    assert value["background"] == "#141b2c"
    assert value["accent"] == "#b1f1ce"


def test_stream_and_saved_pages_keep_semantic_roles():
    raw = {"nodes": [{"id": "title", "kind": "heading", "role": "title", "text": "Titolo"},
                     {"id": "example", "kind": "text", "role": "example", "text": "Un esempio",
                      "style": {"surface": "example"}}]}
    page = PageSpec.model_validate(raw)
    stream = PageStream()
    for char in json.dumps(raw):
        stream.feed(char)
    assert stream.nodes == page.nodes
    saved = SlideContent(title="Test", page=page).model_dump()
    assert SlideContent.model_validate(saved).page.nodes[1].role == "example"
    assert PageSpec.model_validate({"nodes": [{"id": "old", "kind": "text"}]}).nodes[0].role == "auto"
    raw["nodes"][1]["style"]["surface"] = "plain"
    assert PageSpec.model_validate(raw).nodes[1].style.surface == "plain"


@pytest.mark.asyncio
async def test_actual_page_generation_receives_identity_and_keeps_dynamic_roles(tmp_path):
    store = Store(tmp_path/"data")
    project = store.create(ProjectInput(engine="v2", count=1, **PRESET["values"]).model_dump())
    store.save_job({"id": "job", "status": "running", "events": []})
    worker = Worker(store, SimpleNamespace())
    captured = []
    class Client:
        async def json(self, prompt, **kwargs):
            if "on_text" not in kwargs:
                return {"slides": [{"title": "Il tema", "purpose": "Spiegazione"}]}
            captured.append(prompt)
            raw = {"nodes": [{"id": "title", "kind": "heading", "role": "title", "text": "Il tema"},
                             {"id": "body", "kind": "text", "role": "lead", "text": "Una introduzione."}]}
            await kwargs["on_text"](json.dumps(raw))
            return raw
    await run_pages(worker, Client(), "job", project["id"],
                    Generation(provider=Provider(), prompt="Spiega un tema", count=1), "", [])
    assert len(captured) == 1
    assert '"heading_font":"Georgia"' in captured[0]
    assert '"example_color":"#eef2ff"' in captured[0]
    assert IDENTITY["design_note"] in captured[0]
    saved = store.project(project["id"])
    assert saved["slides"][0]["content"]["page"]["nodes"][1]["role"] == "lead"
    assert saved["theme_design"]["visual_family"] == "editorial"


@pytest.mark.parametrize("prompt", [" ", "", "x"*2001])
def test_description_limits(prompt):
    with pytest.raises(ValidationError):
        ThemeDesignRequest(prompt=prompt, provider={"mode": "local"})


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_theme_ai_preview_only_uses_configured_provider_and_preserves_settings(tmp_path, mode):
    app = create_app(ROOT, tmp_path/"data")
    requests = []
    original_sampling = {"max_tokens": 10000, "timeout_seconds": 360, "temperature": .35, "top_p": .95}
    class FakeLLM:
        def __init__(self, provider, manager):
            self.provider = provider
            self.sampling = original_sampling
        async def prepare(self):
            requests.append(self.provider.model_dump())
        async def json(self, prompt, **kwargs):
            assert self.sampling["max_tokens"] == 4096
            assert self.sampling["timeout_seconds"] == 180
            assert "theme_design" in kwargs["schema"]["$defs"]["ThemeValues"]["properties"]
            assert "HTML" in kwargs["system"]
            return PRESET
    app["worker"].clients = FakeLLM
    async with TestClient(TestServer(app)) as client:
        payload = {"prompt": "Tema editoriale caldo", "provider": {
            "mode": mode, "model": "chosen-model", "base_url": "http://127.0.0.1:8081/v1",
            "api_key": "test-not-a-real-key", "remote_consent": True}}
        response = await client.post("/api/themes/design", json=payload, headers=HEADERS)
        assert response.status == 200, await response.text()
        theme = await response.json()
        assert theme["values"]["theme_design"]["heading_font"] == "Georgia"
        assert requests[0]["model"] == "chosen-model" and requests[0]["mode"] == mode
        assert "api_key" not in str(theme)
        assert await (await client.get("/api/themes")).json() == []
        assert app["store"].projects() == [] and app["store"].jobs() == []
        assert original_sampling["max_tokens"] == 10000
        assert original_sampling["timeout_seconds"] == 360
        response = await client.post("/api/themes", json=theme, headers=HEADERS)
        assert response.status == 200


@pytest.mark.asyncio
async def test_theme_endpoint_requires_consent_and_does_not_interrupt_busy_model(tmp_path):
    app = create_app(ROOT, tmp_path/"data")
    def never_called(*args):
        pytest.fail("Must not instantiate an LLM")
    app["worker"].clients = never_called
    async with TestClient(TestServer(app)) as client:
        payload = {"prompt": "Tema luminoso", "provider": {"mode": "remote", "remote_consent": False}}
        assert (await client.post("/api/themes/design", json=payload)).status == 403
        assert (await client.post("/api/themes/design", json=payload, headers=HEADERS)).status == 400
        payload["provider"]["remote_consent"] = True
        active = asyncio.create_task(asyncio.Event().wait())
        app["worker"].tasks["test-active"] = active
        try:
            response = await client.post("/api/themes/design", json=payload, headers=HEADERS)
            assert response.status == 409 and not active.done()
        finally:
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)


@pytest.mark.asyncio
async def test_theme_request_serializes_runtime_and_release_after_invalid_response(tmp_path):
    app = create_app(ROOT, tmp_path/"data")
    started, finish = asyncio.Event(), asyncio.Event()
    class FakeLLM:
        def __init__(self, *_):
            self.sampling = {"max_tokens": 3500}
        async def prepare(self):
            pass
        async def json(self, *args, **kwargs):
            started.set()
            await finish.wait()
            return {"name": "Bad", "values": {"theme_design": {"unknown": True}}}
    app["worker"].clients = FakeLLM
    async with TestClient(TestServer(app)) as client:
        payload = {"prompt": "Tema editoriale", "provider": {"mode": "local"}}
        first = asyncio.create_task(client.post("/api/themes/design", json=payload, headers=HEADERS))
        try:
            await asyncio.wait_for(started.wait(), 3)
            assert (await client.post("/api/themes/design", json=payload, headers=HEADERS)).status == 409
            assert (await client.post("/api/projects/not-created/generate", json={}, headers=HEADERS)).status == 409
            assert (await client.post("/api/llm/stop", json={}, headers=HEADERS)).status == 400
            assert (await client.post("/api/admin/llm", json={}, headers=HEADERS)).status == 400
        finally:
            finish.set()
            response = await first
        assert response.status == 400
        assert not app["theme_design_lock"].locked()
        assert await (await client.get("/api/themes")).json() == []


@pytest.mark.asyncio
async def test_theme_waits_for_runtime_stop_to_finish(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path/"data")
    started, finish = asyncio.Event(), asyncio.Event()
    async def stop():
        started.set()
        await finish.wait()
    monkeypatch.setattr(app["manager"], "stop", stop)
    async with TestClient(TestServer(app)) as client:
        stopping = asyncio.create_task(client.post("/api/llm/stop", json={}, headers=HEADERS))
        try:
            await asyncio.wait_for(started.wait(), 3)
            response = await client.post("/api/themes/design", json={"prompt": "Tema chiaro", "provider": {"mode": "local"}}, headers=HEADERS)
            assert response.status == 409
        finally:
            finish.set()
            assert (await stopping).status == 200
        assert not app["theme_design_lock"].locked()
