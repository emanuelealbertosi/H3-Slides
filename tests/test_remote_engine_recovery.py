"""Remote engine recovery over an isolated HTTP server; never contacts LM Studio."""
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from h3_slides.llm import LLM, _remote_engine_problem, _remote_http_problem
from h3_slides.models import ProjectInput, Provider
from h3_slides.runtime_settings import InferenceSettings, RemoteInferenceSettings
from h3_slides.storage import Store
from h3_slides.worker import Worker


def completed(content=None):
    return web.json_response({"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(content or {"ok": True})}}]})


def provider(server):
    return Provider(mode="remote", model="test-engine", remote_consent=True,
                    base_url=str(server.make_url("/")), api_key="PRIVATE_KEY",
                    inference=RemoteInferenceSettings(max_tokens=10000))


@pytest.fixture
def no_retry_delay(monkeypatch):
    waits = []
    original = asyncio.sleep

    async def sleep(seconds):
        waits.append(seconds)
        await original(0)

    monkeypatch.setattr("h3_slides.llm._retry_sleep", sleep)
    return waits


@pytest.mark.parametrize("status", [400, 500, 502, 503, 504])
@pytest.mark.parametrize("payload", [
    b'{"error":"Channel Error"}',
    b'{"error":{"message":"Error: Channel Error"}}',
    b'{"message":"Engine protocol predict request failed: fetch failed"}',
    b'Error: Channel Error',
])
def test_explicit_engine_error_has_a_specific_safe_category(status, payload):
    assert _remote_engine_problem(status, payload)[0] == "connection"
    message, is_context = _remote_http_problem(status, payload)
    assert "comunicazione interna" in message and not is_context


@pytest.mark.parametrize("status,payload", [
    (401, b'{"error":"Channel Error"}'),
    (403, b'{"error":"Channel Error"}'),
    (429, b'{"error":"Channel Error"}'),
    (400, b'{"error":"Invalid request", "document":"Channel Error"}'),
    (400, b'{"error":{"message":"Bad input", "request":{"message":"Channel Error"}}}'),
    (400, b'{"error":"The document says Channel Error"}'),
    (400, b'{"error":"fetch failed"}'),
    (400, b'{"error":"terminated"}'),
    (500, b'{"error":"Internal Server Error"}'),
    (400, b'[]'),
])
def test_ambiguous_or_echoed_errors_do_not_enable_engine_retry(status, payload):
    assert _remote_engine_problem(status, payload) is None


@pytest.mark.parametrize("code,kind", [("ExplicitModelUnloadError", "stopped"),
                                     ("out_of_memory", "resources"), ("context_length_exceeded", "resources")])
def test_structured_diagnostic_codes_prevent_retry(code, kind):
    payload = json.dumps({"error": {"message": "Channel Error", "code": code}}).encode()
    assert _remote_engine_problem(400, payload)[0] == kind


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 500, 503])
async def test_retry_is_once_with_identical_request_and_safe_job_events(tmp_path, caplog, no_retry_delay, status):
    caplog.set_level(logging.INFO)
    bodies, headers = [], []

    async def complete(request):
        bodies.append(await request.json())
        headers.append(request.headers.get("Authorization"))
        if len(bodies) == 1:
            return web.json_response({"error": {"message": "Channel Error PRIVATE_PROVIDER_BODY",
                                               "request": bodies[-1]}}, status=status)
        return completed()

    app = web.Application(); app.router.add_post("/v1/chat/completions", complete)
    store = Store(tmp_path / "data")
    store.save_job({"id": "job", "project_id": "project", "status": "running", "events": [], "progress": .1})
    manager = SimpleNamespace(last_used=0)  # No start/stop/model-management API exists in this fixture.
    worker = Worker(store, manager)
    try:
        async with TestServer(app) as server:
            client = worker.make_client(provider(server), "job")
            await client.prepare()
            settings = client.sampling.copy()
            assert await client.json("PRIVATE_DOCUMENT", schema={"type": "object"}) == {"ok": True}
            assert len(bodies) == 2 and bodies[0] == bodies[1]
            assert bodies[1]["max_tokens"] == 10000 and client.sampling == settings
            assert headers == ["Bearer PRIVATE_KEY"] * 2
            assert client.last_metrics["attempts"] == 2
            assert client.last_metrics["http_status"] == 200
            assert client.last_metrics["outcome"] == "response_received"
        events = [e["message"] for e in store.job("job")["events"]]
        assert len(events) == 2 and "Unico tentativo" in events[0] and "ripreso a rispondere" in events[1]
        assert no_retry_delay == [2]
        for secret in ("PRIVATE_KEY", "PRIVATE_DOCUMENT", "PRIVATE_PROVIDER_BODY"):
            assert secret not in caplog.text + json.dumps(events)
        assert store.job("job")["progress"] == .1
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_persistent_error_stops_after_second_request(no_retry_delay):
    bodies, events = [], []

    async def complete(request):
        bodies.append(await request.json())
        return web.json_response({"error": "Channel Error PRIVATE"}, status=400)

    app = web.Application(); app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        client = LLM(provider(server), SimpleNamespace(last_used=0)); await client.prepare()
        client.event_callback = events.append
        with pytest.raises(RuntimeError, match="unico tentativo automatico") as error:
            await client.json("Private input")
        assert "PRIVATE" not in str(error.value)
        assert client.last_metrics["attempts"] == 2 and client.last_metrics["outcome"] == "engine_error"
    assert len(bodies) == 2 and bodies[0] == bodies[1] and no_retry_delay == [2]
    assert len(events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["ExplicitModelUnloadError: Model unloaded by user or API request.",
                                  "Cancelled by user", "CUDA error: out of memory", "ErrorDeviceLost",
                                  "context length exceeded"])
async def test_known_stop_or_resource_cause_is_not_retried(cause, no_retry_delay):
    calls = []

    async def complete(request):
        calls.append(await request.json())
        return web.json_response({"error": {"message": "Channel Error", "cause": cause}}, status=400)

    app = web.Application(); app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        client = LLM(provider(server), SimpleNamespace(last_used=0)); await client.prepare()
        with pytest.raises(RuntimeError):
            await client.json("Synthetic input")
    assert len(calls) == 1 and not no_retry_delay


@pytest.mark.asyncio
async def test_local_provider_gets_diagnostic_but_not_remote_retry(no_retry_delay):
    calls = []

    async def complete(request):
        calls.append(await request.json())
        return web.json_response({"error": "Channel Error"}, status=400)

    app = web.Application(); app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        client = LLM(Provider(mode="local"), SimpleNamespace(last_used=0))
        client.url, client.model = str(server.make_url("/v1")), "test"
        client.sampling = InferenceSettings().model_dump()
        with pytest.raises(RuntimeError, match="comunicazione interna"):
            await client.json("Synthetic input")
    assert len(calls) == 1 and not no_retry_delay


@pytest.mark.asyncio
async def test_cancellation_during_delay_never_sends_retry(monkeypatch):
    calls = []
    entered = asyncio.Event()

    async def sleep(seconds):
        assert seconds == 2
        entered.set()
        await asyncio.Event().wait()

    async def complete(request):
        calls.append(await request.json())
        return web.json_response({"error": "Channel Error"}, status=400)

    monkeypatch.setattr("h3_slides.llm._retry_sleep", sleep)
    app = web.Application(); app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        client = LLM(provider(server), SimpleNamespace(last_used=0)); await client.prepare()
        task = asyncio.create_task(client.json("Synthetic input"))
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.last_metrics["outcome"] == "cancelled"
        assert client.last_metrics["attempts"] == 1
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("errors", [
    ["response_format unsupported", "Channel Error", None],
    ["Channel Error", "response_format unsupported", None],
    ["maximum context length exceeded", "response_format unsupported", "Channel Error", None],
    ["Channel Error", "response_format unsupported", "Channel Error"],
])
async def test_engine_retry_does_not_loop_with_existing_compatibility_retries(errors, no_retry_delay):
    bodies = []

    async def complete(request):
        bodies.append(await request.json())
        problem = errors[len(bodies)-1]
        return web.json_response({"error": problem}, status=400) if problem else completed()

    app = web.Application(); app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        client = LLM(provider(server), SimpleNamespace(last_used=0)); await client.prepare()
        if errors[-1] is None:
            assert await client.json("Synthetic input") == {"ok": True}
        else:
            with pytest.raises(RuntimeError, match="unico tentativo"):
                await client.json("Synthetic input")
    assert len(bodies) == len(errors) and no_retry_delay == [2]
    for i, problem in enumerate(errors[:-1]):
        if problem == "Channel Error":
            assert bodies[i] == bodies[i+1]


@pytest.mark.asyncio
async def test_log_callback_failure_cannot_break_recovery(no_retry_delay, caplog):
    calls = []

    def broken(_):
        raise ValueError("PRIVATE_CALLBACK_ERROR")

    async def complete(request):
        calls.append(await request.json())
        return web.json_response({"error": "Channel Error"}, status=400) if len(calls) == 1 else completed()

    app = web.Application(); app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        client = LLM(provider(server), SimpleNamespace(last_used=0)); await client.prepare()
        client.event_callback = broken
        assert await client.json("Synthetic input") == {"ok": True}
    assert len(calls) == 2 and "PRIVATE_CALLBACK_ERROR" not in caplog.text


@pytest.mark.asyncio
async def test_four_completed_document_chunks_survive_fifth_chunk_engine_failure(tmp_path, no_retry_delay):
    letters, fail = [], True

    async def complete(request):
        body = await request.json()
        chunk = body["messages"][1]["content"][0]["text"].split("DOCUMENTO:\n", 1)[1]
        letters.append(chunk[0])
        if fail and chunk[0] == "E":
            return web.json_response({"error": "Channel Error"}, status=400)
        return completed({"summary": "Sintesi " + chunk[0]})

    app = web.Application(); app.router.add_post("/v1/chat/completions", complete)
    store = Store(tmp_path / "data")
    project = store.create(ProjectInput(prompt="Spiega il documento").model_dump())
    project["sources"] = [{"id": "source", "name": "test.txt", "text": "".join(c*5000 for c in "ABCDE"),
                           "kind": "txt", "images": [], "warnings": []}]
    store.save_project(project)
    worker = Worker(store, SimpleNamespace(last_used=0))
    try:
        async with TestServer(app) as server:
            store.save_job({"id": "failed", "project_id": project["id"], "status": "running", "events": []})
            client = worker.make_client(provider(server), "failed"); await client.prepare()
            with pytest.raises(RuntimeError, match="unico tentativo"):
                await worker.sources_context(client, project, "failed")
            assert letters == list("ABCDEE")
            assert len(list((store.root / "assets" / project["id"]).glob("rag-chunk-*.json"))) == 4
            fail = False
            store.save_job({"id": "resumed", "project_id": project["id"], "status": "running", "events": []})
            resumed = worker.make_client(provider(server), "resumed"); await resumed.prepare()
            context, assets = await worker.sources_context(resumed, project, "resumed")
            assert letters == list("ABCDEEE") and assets == []
            assert context == "\n".join("test.txt: Sintesi " + c for c in "ABCDE")
            events = [e["message"] for e in store.job("resumed")["events"]]
            assert sum("riuso della cache locale" in e for e in events) == 4
    finally:
        store.db.close()
