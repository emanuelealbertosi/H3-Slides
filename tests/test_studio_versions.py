import copy
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from h3_slides.app import create_app
from h3_slides.models import ProjectInput, SlideContent
from h3_slides.ingest import ingest
from h3_slides.content_rules import validate_content, fit_complete_sentences, content_contract
from h3_slides.composition import split_content
from h3_slides.document_summary import summarize_chunk
from h3_slides.image_search import ImageSearch
from h3_slides.openverse_images import ImageHTTPError

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


@pytest.mark.asyncio
async def test_new_version_is_independent_and_credentials_not_saved(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    store = app["store"]
    p = store.create(ProjectInput(title="Lezione", prompt="Python", count=1).model_dump())
    p["slides"] = [{"id": "s", "revision": 1, "status": "ready", "content": SlideContent(title="Originale").model_dump()}]
    p["sources"] = [ingest(store, p["id"], "example.py", b"def f():\n    return 1\n")]
    store.save_project(p)
    store.asset_path(p["id"], "retained.txt").write_text("unchanged")
    before = store.project(p["id"])
    calls = []
    def submit(pid, request):
        calls.append(pid)
        return {"id": "test-job", "project_id": pid, "status": "queued"}
    monkeypatch.setattr(app["worker"], "submit", submit)
    async with TestClient(TestServer(app)) as client:
        settings = ProjectInput(title="Lezione", prompt="Nuova spiegazione", canvas_mode="adaptive",
                                graphic_style="vivid", theme_preset="Oceano").model_dump()
        payload = {"provider": {"mode": "remote", "base_url": "https://provider.example/v1", "model": "test",
                   "api_key": "DO-NOT-PERSIST", "remote_consent": True}, "prompt": "Nuova spiegazione", "count": 1,
                   "regenerate_all": True, "rebuild_outline": True, "new_version": True, "project_settings": settings}
        response = await client.post(f"/api/projects/{p['id']}/generate", json=payload, headers=HEADERS)
        assert response.status == 202, await response.text()
        child = store.project((await response.json())["project_id"])
        assert store.project(p["id"]) == before
        assert child["title"] == "Lezione (v2)" and child["parent_project_id"] == p["id"]
        assert child["canvas_mode"] == "adaptive" and child["graphic_style"] == "vivid"
        assert child["sources"] == p["sources"]
        assert store.asset_path(child["id"], "retained.txt").read_text() == "unchanged"
        assert "DO-NOT-PERSIST" not in json.dumps(child)
        assert child["generation_settings"]["provider"]["model"] == "test"
        again = await client.post(f"/api/projects/{p['id']}/generate", json=payload, headers=HEADERS)
        third = store.project((await again.json())["project_id"])
        assert third["version_number"] == 3
        monkeypatch.setattr(app["worker"], "active", lambda: True)
        refused = await client.post(f"/api/projects/{p['id']}/generate", json=payload, headers=HEADERS)
        assert refused.status == 400 and len(store.projects()) == 3


@pytest.mark.parametrize("language,code", [
    ("python", "def saluta(nome):\n    return f'Ciao {nome}'\n"),
    ("c", '#include <stdio.h>\nint main(void) {\n    printf("Ciao\\n");\n    return 0;\n}'),
    ("cpp", '#include <iostream>\nint main() {\n    std::cout << "Ciao";\n    return 0;\n}'),
])
def test_code_preserves_indentation_and_is_not_prose(language, code):
    c = SlideContent(title="Esempio", blocks=[{"kind": "code", "language": language, "text": code}])
    p = ProjectInput(text_density="complete").model_dump()
    validate_content(c, p, "")
    assert not fit_complete_sentences(c, p)
    assert c.blocks[0].text == code
    fenced = SlideContent(title="Esempio", blocks=[{"text": "```"+language+"\n"+code.rstrip("\n")+"\n```"}])
    assert fenced.blocks[0].kind == "code" and fenced.blocks[0].language == language
    schema, _ = content_contract(p)
    assert schema["$defs"]["CodeBlock"]["properties"]["text"]["maxLength"] == 1600


def test_brief_allows_code_and_adaptive_increases_prose_space():
    from h3_slides.content_rules import paragraph_budget
    c = SlideContent(title="Python", blocks=[{"kind": "code", "language": "python", "text": "print(1)"}])
    validate_content(c, {"text_density": "brief"}, "")
    schema, _ = content_contract({"text_density": "brief"})
    assert schema["properties"]["blocks"]["maxItems"] == 1
    assert paragraph_budget({"canvas_mode": "adaptive"}) > paragraph_budget({})


def test_code_splits_only_at_line_boundaries():
    code = "".join(f"    print({i})\n" for i in range(35))
    c = SlideContent(title="Esempio lungo", blocks=[{"kind": "code", "language": "python", "text": code}])
    pieces = split_content(c.model_dump())
    assert len(pieces) == 2
    assert "".join(p["blocks"][0]["text"] for p in pieces) == code


@pytest.mark.asyncio
async def test_truncated_summary_splits_without_dropping_source_text():
    text = "A"*1600+"B"*1600
    successful, events = [], []
    class Client:
        async def json(self, prompt, **kwargs):
            chunk = prompt.split("DOCUMENTO:\n", 1)[1]
            if len(chunk) > 1700:
                raise ValueError("Risposta LLM troncata")
            successful.append(chunk)
            return {"summary": chunk[:50]}
    async def checkpoint(): pass
    result = await summarize_chunk(Client(), text, events.append, checkpoint)
    assert "".join(successful) == text and events and "\n" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status,fallback", [(424, True), (404, True), (403, False), (429, False)])
async def test_openverse_thumbnail_failure_does_not_bypass_refusals(monkeypatch, status, fallback):
    import io
    from PIL import Image
    out = io.BytesIO();Image.new("RGB", (400, 300)).save(out, format="JPEG")
    finder, calls = ImageSearch(), []
    async def fetch(session, url, limit):
        calls.append(url)
        if url.endswith("thumb"):
            raise ImageHTTPError(status)
        return out.getvalue(), url, "image/jpeg"
    monkeypatch.setattr(finder.web.openverse, "fetch", fetch)
    row = {"image_provider": "Openverse", "preview": "https://api.openverse.org/thumb",
           "download_url": "https://museum.example.org/original"}
    if fallback:
        assert await finder.preview(row)
        assert len(calls) == 2
    else:
        with pytest.raises(ImageHTTPError): await finder.preview(row)
        assert len(calls) == 1
