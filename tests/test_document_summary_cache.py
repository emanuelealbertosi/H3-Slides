import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import h3_slides.document_summary as summaries
from h3_slides.models import ProjectInput
from h3_slides.storage import Store
from h3_slides.worker import Worker


class Client:
    def __init__(self):
        self.provider = SimpleNamespace(mode="remote", model="model-a", base_url="https://provider.example/v1",
                                        api_key="SECRET-KEY", remote_consent=True)
        self.sampling = {"max_tokens": 3500, "temperature": .35, "top_p": .95, "timeout_seconds": 360}
        self.calls = []
        self.fail_on = None

    async def json(self, prompt, schema=None):
        text = prompt.split("DOCUMENTO:\n", 1)[1]
        self.calls.append(text)
        if text[0] == self.fail_on:
            raise RuntimeError("LLM HTTP 400")
        return {"summary": "Sintesi della parte " + text[0]}


async def checkpoint():
    pass


@pytest.mark.asyncio
async def test_successful_chunk_survives_a_new_client_and_transport_changes(tmp_path):
    events = []
    first = Client()
    expected = await summaries.summarize_chunk(first, "Testo del documento", events.append, checkpoint, cache_dir=tmp_path)
    other = Client()
    other.sampling.update(timeout_seconds=900, api_key="DO-NOT-HASH")
    other.provider.api_key = "DIFFERENT-SECRET"
    result = await summaries.summarize_chunk(other, "Testo del documento", events.append, checkpoint, cache_dir=tmp_path)
    assert result == expected and not other.calls
    assert any("riuso della cache" in event for event in events)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1 and files[0].stem.startswith("rag-chunk-") and len(files[0].stem) == 74
    saved = files[0].read_text(encoding="utf-8")
    assert set(json.loads(saved)) == {"version", "fingerprint", "summary"}
    for private in ("SECRET", "provider.example", "Testo del documento", "timeout_seconds", "max_tokens"):
        assert private not in saved


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["text", "model", "request_model", "mode", "endpoint", "temperature", "tokens",
                                     "thinking", "system", "instructions", "schema", "version"])
async def test_content_and_inference_contract_changes_invalidate_chunk_cache(tmp_path, monkeypatch, changed):
    client = Client()
    await summaries.summarize_chunk(client, "Testo", lambda _: None, checkpoint, cache_dir=tmp_path)
    text = "Testo"
    if changed == "text": text = "Testo aggiornato"
    if changed == "model": client.provider.model = "model-b"
    if changed == "request_model": client.model = "resolved-model-b"
    if changed == "mode": client.provider.mode = "local"
    if changed == "endpoint": client.provider.base_url = "https://different.example/v1"
    if changed == "temperature": client.sampling["temperature"] = .1
    if changed == "tokens": client.sampling["max_tokens"] = 5000
    if changed == "thinking": client.sampling["thinking"] = True
    if changed == "system": monkeypatch.setattr("h3_slides.models.SYSTEM", "Istruzioni di sistema aggiornate")
    if changed == "instructions": monkeypatch.setattr(summaries, "SUMMARY_INSTRUCTIONS", "Altre istruzioni.\nDOCUMENTO:\n")
    if changed == "schema":
        schema = copy.deepcopy(summaries.SUMMARY_SCHEMA)
        schema["properties"]["summary"]["maxLength"] = 2400
        monkeypatch.setattr(summaries, "SUMMARY_SCHEMA", schema)
    if changed == "version": monkeypatch.setattr(summaries, "SUMMARY_CACHE_VERSION", 2)
    await summaries.summarize_chunk(client, text, lambda _: None, checkpoint, cache_dir=tmp_path)
    assert len(client.calls) == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_identity_uses_effective_endpoint_without_credentials_query_or_fragment():
    client = Client()
    client.url = "https://username:password@server.example/api/v1/?api_key=SECRET#private"
    identity = summaries.summary_cache_identity(client)
    assert identity["endpoint"] == "https://server.example/api/v1"
    dumped = json.dumps(identity)
    for private in ("username", "password", "SECRET", "api_key", "private", "timeout_seconds"):
        assert private not in dumped


@pytest.mark.asyncio
async def test_failed_chunk_is_not_cached(tmp_path):
    client = Client()
    client.fail_on = "A"
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await summaries.summarize_chunk(client, "Allegato", lambda _: None, checkpoint, cache_dir=tmp_path)
    assert not list(tmp_path.iterdir())
    client.fail_on = None
    await summaries.summarize_chunk(client, "Allegato", lambda _: None, checkpoint, cache_dir=tmp_path)
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_successful_split_half_is_reused_after_other_half_failed(tmp_path):
    class SplitClient(Client):
        async def json(self, prompt, schema=None):
            text = prompt.split("DOCUMENTO:\n", 1)[1]
            if len(text) > 1700:
                self.calls.append(text)
                raise ValueError("Risposta LLM troncata")
            return await super().json(prompt, schema)
    client = SplitClient()
    source = "A"*1600 + "B"*1600
    client.fail_on = "B"
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await summaries.summarize_chunk(client, source, lambda _: None, checkpoint, cache_dir=tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 1
    client.fail_on = None
    result = await summaries.summarize_chunk(client, source, lambda _: None, checkpoint, cache_dir=tmp_path)
    assert result == "Sintesi della parte A\nSintesi della parte B"
    assert client.calls.count("A"*1600) == 1 and client.calls.count("B"*1600) == 2
    before = len(client.calls)
    assert await summaries.summarize_chunk(client, source, lambda _: None, checkpoint, cache_dir=tmp_path) == result
    assert len(client.calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["{", '{"summary": ""}', "[]"])
async def test_corrupt_chunk_is_recomputed_not_used(tmp_path, corruption):
    client = Client()
    await summaries.summarize_chunk(client, "Allegato", lambda _: None, checkpoint, cache_dir=tmp_path)
    path = next(tmp_path.glob("*.json"))
    path.write_text(corruption, encoding="utf-8")
    result = await summaries.summarize_chunk(client, "Allegato", lambda _: None, checkpoint, cache_dir=tmp_path)
    assert result == "Sintesi della parte A" and len(client.calls) == 2
    assert json.loads(path.read_text(encoding="utf-8"))["summary"] == result


@pytest.mark.asyncio
async def test_cache_write_failure_does_not_fail_extraction_or_leave_temp(tmp_path, monkeypatch, caplog):
    def fail_replace(*args): raise OSError("PRIVATE-PATH")
    monkeypatch.setattr(Path, "replace", fail_replace)
    result = await summaries.summarize_chunk(Client(), "Allegato", lambda _: None, checkpoint, cache_dir=tmp_path)
    assert result == "Sintesi della parte A" and not list(tmp_path.iterdir())
    assert "Cache di lettura documento non salvata" in caplog.text and "PRIVATE-PATH" not in caplog.text


@pytest.mark.asyncio
async def test_checkpoint_is_respected_even_when_chunk_is_cached(tmp_path):
    import asyncio
    client = Client()
    await summaries.summarize_chunk(client, "Allegato", lambda _: None, checkpoint, cache_dir=tmp_path)
    async def cancelled(): raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await summaries.summarize_chunk(client, "Allegato", lambda _: None, cancelled, cache_dir=tmp_path)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_worker_resume_keeps_successful_blocks_across_store_reopen(tmp_path):
    root = tmp_path / "isolated-data"
    store = Store(root)
    project = store.create(ProjectInput(prompt="Spiega il documento").model_dump())
    project["sources"] = [{"id": "source", "name": "documento.txt", "text": "A"*5000+"B"*5000+"C"*5000,
                           "kind": "txt", "images": [], "warnings": []}]
    store.save_project(project)
    store.save_job({"id": "failed", "project_id": project["id"], "status": "running", "events": []})
    client = Client()
    client.fail_on = "C"
    worker = Worker(store, SimpleNamespace())
    try:
        with pytest.raises(RuntimeError, match="HTTP 400"):
            await worker.sources_context(client, project, "failed")
        assert len(client.calls) == 3
        assets = store.root / "assets" / project["id"]
        assert len(list(assets.glob("rag-chunk-*.json"))) == 2
        assert not [path for path in assets.glob("rag-*.json") if not path.name.startswith("rag-chunk-")]
    finally:
        store.db.close()
    # All state belongs to this pytest directory, never the application's real Store.
    store = Store(root)
    try:
        worker = Worker(store, SimpleNamespace())
        store.save_job({"id": "resumed", "project_id": project["id"], "status": "running", "events": []})
        resumed = Client()
        context, assets = await worker.sources_context(resumed, store.project(project["id"]), "resumed")
        assert resumed.calls == ["C"*5000] and assets == []
        assert context == "\n".join("documento.txt: Sintesi della parte "+letter for letter in "ABC")
        assert store.project(project["id"])["sources"] == project["sources"]
        messages = [e["message"] for e in store.job("resumed")["events"]]
        assert sum("riuso della cache locale" in message for message in messages) == 2
        # Final RAG cache shares the same endpoint/sampling identity as chunk cache.
        resumed.calls.clear()
        resumed.sampling["timeout_seconds"] = 900
        resumed.provider.api_key = "NEW-SECRET"
        assert await worker.sources_context(resumed, project, "resumed") == (context, assets)
        assert not resumed.calls
        resumed.provider.base_url = "https://other-provider.example/v1"
        assert await worker.sources_context(resumed, project, "resumed") == (context, assets)
        assert len(resumed.calls) == 3
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_removing_source_clears_derived_chunk_cache(tmp_path):
    import aiohttp
    from aiohttp.test_utils import TestClient, TestServer
    from h3_slides.app import create_app
    app = create_app(Path(__file__).resolve().parents[1], tmp_path / "isolated-app")
    headers = {"X-H3-Slides": "1"}
    async with TestClient(TestServer(app)) as http:
        response = await http.post("/api/projects", json={"title": "Cache isolata", "prompt": "Test"}, headers=headers)
        project = await response.json()
        form = aiohttp.FormData()
        form.add_field("file", b"Test document", filename="source.md")
        response = await http.post(f"/api/projects/{project['id']}/sources", data=form, headers=headers)
        assert response.status == 200
        project = await response.json()
        assets = app["store"].root / "assets" / project["id"]
        await summaries.summarize_chunk(Client(), "Test document", lambda _: None, checkpoint, cache_dir=assets)
        assert list(assets.glob("rag-chunk-*.json"))
        response = await http.delete(f"/api/projects/{project['id']}/sources/{project['sources'][0]['id']}", headers=headers)
        assert response.status == 200
        assert not list(assets.glob("rag-chunk-*.json"))
