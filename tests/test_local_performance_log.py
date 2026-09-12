"""Real LLM/worker telemetry integration over a synthetic local HTTP server."""
import asyncio
import json
import logging
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from h3_slides.llm import LLM
from h3_slides.models import Generation, ProjectInput, Provider, SlideContent
from h3_slides.runtime_settings import InferenceSettings
from h3_slides.storage import Store
from h3_slides.worker import Worker


def native_response(content=None):
    return {
        "choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(content if content is not None else {"ok": True}),
            "reasoning_content": "PRIVATE_REASONING_TEXT",
        }}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 101,
                  "prompt_tokens_details": {"cached_tokens": 900, "private": "PRIVATE_CACHE_DETAIL"}},
        "timings": {"prompt_n": 100, "prompt_ms": 250, "prompt_per_second": 400,
                    "predicted_n": 101, "predicted_ms": 2000, "predicted_per_second": 50,
                    "cache_n": 890, "private": "PRIVATE_TIMING_DETAIL"},
        "model": "PRIVATE_PROVIDER_MODEL", "api_key": "PRIVATE_RESPONSE_KEY",
        "stats": {"private": "PRIVATE_STATS_DETAIL"},
    }


def configure_without_loading(client, server, timeout=2):
    client.url = str(server.make_url("/v1")).rstrip("/")
    client.model = "PRIVATE_REQUEST_MODEL"
    client.sampling = {**InferenceSettings().model_dump(), "timeout_seconds": timeout}
    return client


def create_sink(tmp_path):
    store = Store(tmp_path / "data")
    worker = Worker(store, SimpleNamespace(last_used=0))
    store.save_job({"id": "performance-job", "project_id": "fixture-project", "status": "completed",
                    "events": [], "progress": 1})
    return store, worker


def performance_events(store, jid="performance-job"):
    return [event["message"] for event in store.job(jid)["events"] if event["message"].startswith("LLM interno #")]


@pytest.mark.asyncio
async def test_local_worker_metrics_persist_across_clients_and_store_reload(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    received = []

    async def complete(request):
        received.append(await request.json())
        return web.json_response(native_response())

    app = web.Application()
    app.router.add_post("/v1/chat/completions", complete)
    store, worker = create_sink(tmp_path)
    provider = Provider(mode="local", model="PRIVATE_PROVIDER_SETTING", api_key="PRIVATE_REQUEST_KEY")
    try:
        async with TestServer(app) as server:
            first = configure_without_loading(worker.make_client(provider, "performance-job"), server)
            assert callable(first.metrics_callback)
            assert await first.json("PRIVATE_FIRST_DOCUMENT") == {"ok": True}
            second = configure_without_loading(worker.make_client(provider, "performance-job"), server)
            assert second is not first
            assert await second.json("PRIVATE_SECOND_DOCUMENT") == {"ok": True}
            job = store.job("performance-job")
            assert job["llm_performance"]["request_count"] == 2
            latest = job["llm_performance"]["latest"]
            assert latest["server_prefill_tokens"] == 100
            assert latest["server_prefill_seconds"] == 0.25
            assert latest["server_prefill_tokens_per_second"] == 400
            assert latest["server_decode_tokens"] == 101
            assert latest["server_generation_seconds"] == 2
            assert latest["server_decode_tokens_per_second"] == 50
            assert latest["input_cached_tokens"] == 900
            assert latest["attempts"] == 1 and latest["outcome"] == "response_received"
            assert "Prefill: 100 token · 0.250s · 400.00 token/s" in performance_events(store)[0]
            assert "Generazione: 101 token · 2.000s · 50.00 token/s" in performance_events(store)[1]
            assert "Cache input: 900 token" in performance_events(store)[1]
            assert "LLM interno #1" in caplog.text and "LLM interno #2" in caplog.text
            # A reload uses the stored counter, not an LLM-instance counter.
            store.db.close()
            store = Store(tmp_path / "data")
            worker = Worker(store, SimpleNamespace(last_used=0))
            third = configure_without_loading(worker.make_client(provider, "performance-job"), server)
            assert await third.json("PRIVATE_THIRD_DOCUMENT") == {"ok": True}
            assert store.job("performance-job")["llm_performance"]["request_count"] == 3
            assert performance_events(store)[-1].startswith("LLM interno #3")
            assert len(received) == 3
            assert received[0]["messages"][1]["content"][0]["text"] == "PRIVATE_FIRST_DOCUMENT"
            assert "PRIVATE" not in json.dumps(store.jobs())
            assert "PRIVATE" not in caplog.text
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_remote_requests_do_not_invoke_local_metrics_callback(tmp_path):
    async def complete(request):
        return web.json_response(native_response())

    app = web.Application()
    app.router.add_post("/v1/chat/completions", complete)
    store, worker = create_sink(tmp_path)
    try:
        async with TestServer(app) as server:
            provider = Provider(mode="remote", model="fake", remote_consent=True,
                                base_url=str(server.make_url("/")))
            client = configure_without_loading(worker.make_client(provider, "performance-job"), server)
            assert client.metrics_callback is None
            callbacks = []
            client.metrics_callback = callbacks.append
            assert await client.json("PRIVATE_REMOTE_DOCUMENT") == {"ok": True}
            assert callbacks == []
            assert performance_events(store) == []
            assert "llm_performance" not in store.job("performance-job")
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_callback_exception_and_mutation_cannot_change_valid_response_or_metrics(caplog):
    caplog.set_level(logging.INFO)

    async def complete(request):
        return web.json_response(native_response())

    app = web.Application()
    app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        client = configure_without_loading(LLM(Provider(mode="local"), SimpleNamespace(last_used=0)), server)
        calls = []

        def broken_callback(metrics):
            calls.append(metrics.copy())
            metrics["output_tokens"] = 999999
            metrics["outcome"] = "PRIVATE_CALLBACK_MUTATION"
            raise RuntimeError("PRIVATE_CALLBACK_EXCEPTION")

        client.metrics_callback = broken_callback
        assert await client.json("PRIVATE_DOCUMENT") == {"ok": True}
        assert len(calls) == 1
        assert client.last_metrics["output_tokens"] == 101
        assert client.last_metrics["outcome"] == "response_received"
        assert client.last_metrics["http_status"] == 200
        assert "Impossibile aggiornare il contatore prestazioni LLM nel job" in caplog.text
        assert "PRIVATE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "cancelled", "http-error"])
@pytest.mark.parametrize("broken_callback", [False, True])
async def test_error_outcome_is_recorded_without_masking_request_failure(tmp_path, caplog, kind, broken_callback):
    caplog.set_level(logging.INFO)
    entered, release = asyncio.Event(), asyncio.Event()

    async def complete(request):
        entered.set()
        if kind == "http-error":
            return web.json_response({"error": "PRIVATE_HTTP_RESPONSE"}, status=500)
        await release.wait()
        return web.json_response(native_response())

    app = web.Application()
    app.router.add_post("/v1/chat/completions", complete)
    store, worker = create_sink(tmp_path)
    try:
        async with TestServer(app) as server:
            client = configure_without_loading(worker.make_client(Provider(mode="local"), "performance-job"),
                                                server, timeout=0.05 if kind == "timeout" else 2)
            if broken_callback:
                original = client.metrics_callback

                def fail_after_recording(metrics):
                    original(metrics)
                    raise RuntimeError("PRIVATE_CALLBACK_FAILURE")

                client.metrics_callback = fail_after_recording
            request = asyncio.create_task(client.json("PRIVATE_ERROR_DOCUMENT"))
            try:
                await asyncio.wait_for(entered.wait(), timeout=2)
                if kind == "cancelled":
                    request.cancel()
                expected = asyncio.CancelledError if kind == "cancelled" else ValueError if kind == "timeout" else RuntimeError
                with pytest.raises(expected) as exc:
                    await request
                assert "PRIVATE" not in str(exc.value)
            finally:
                release.set()
                if not request.done():
                    request.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await request
            outcome = "error" if kind == "http-error" else kind
            saved = store.job("performance-job")["llm_performance"]
            assert saved["request_count"] == 1
            assert saved["latest"]["outcome"] == outcome
            assert saved["latest"]["attempts"] == 1
            assert saved["latest"]["server_decode_tokens_per_second"] is None
            assert saved["latest"]["server_prefill_tokens"] is None
            line = performance_events(store)[0]
            assert "Prefill: n.d. · n.d. · n.d." in line
            assert "Generazione: n.d. · n.d. · n.d." in line
            assert "Esito: " + {"error": "errore", "timeout": "timeout", "cancelled": "annullata"}[outcome] in line
            assert "PRIVATE" not in json.dumps(store.jobs())
            assert "PRIVATE" not in caplog.text
    finally:
        release.set()
        store.db.close()


@pytest.mark.asyncio
async def test_worker_normal_generation_logs_outline_and_each_slide(tmp_path):
    calls, instances = [], []

    async def complete(request):
        payload = await request.json()
        prompt = payload["messages"][1]["content"][0]["text"]
        if "Proponi esattamente" in prompt:
            calls.append("outline")
            content = {"slides": [{"title": "Variabili", "purpose": "Definizione", "layout": "cover", "block_count": 1},
                                  {"title": "Valori", "purpose": "Esempio", "layout": "content", "block_count": 1}]}
        else:
            assert "Crea UNA slide" in prompt
            calls.append("slide")
            content = SlideContent(title="Un concetto chiaro", bullets=["Una variabile conserva un valore."]).model_dump()
        return web.json_response(native_response(content))

    app = web.Application()
    app.router.add_post("/v1/chat/completions", complete)
    store = Store(tmp_path / "data")
    worker = Worker(store, SimpleNamespace(last_used=0))
    try:
        async with TestServer(app) as server:
            class PreparedFixtureLLM(LLM):
                async def prepare(self):
                    instances.append(self)
                    configure_without_loading(self, server)

            worker.clients = PreparedFixtureLLM
            project = store.create(ProjectInput(title="Variabili", prompt="Spiega le variabili", count=2,
                text_density="brief", use_source_images=False, use_manim_diagrams=False,
                use_web_images=False, web_enabled=False).model_dump())
            job = worker.submit(project["id"], Generation(provider={"mode": "local", "model": "PRIVATE_MODEL"},
                                prompt="Spiega le variabili", count=2))
            await asyncio.wait_for(worker.tasks[job["id"]], timeout=10)
            saved = store.job(job["id"])
            assert saved["status"] == "completed", saved
            assert calls == ["outline", "slide", "slide"]
            assert len(instances) == 1 and callable(instances[0].metrics_callback)
            assert saved["llm_performance"]["request_count"] == 3
            assert len(performance_events(store, job["id"])) == 3
            assert [event.split(" · ", 1)[0] for event in performance_events(store, job["id"])] == [
                "LLM interno #1", "LLM interno #2", "LLM interno #3"]
            assert all(slide["status"] == "ready" for slide in store.project(project["id"])["slides"])
            assert "PRIVATE" not in json.dumps(store.jobs())
    finally:
        await worker.close()
        store.db.close()


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_factory_accepts_simple_clients_without_optional_callback_attribute(tmp_path, mode):
    store, worker = create_sink(tmp_path)

    class MinimalClient:
        __slots__ = ()

        def __init__(self, provider, manager):
            pass

    try:
        worker.clients = MinimalClient
        client = worker.make_client(Provider(mode=mode), "performance-job")
        assert isinstance(client, MinimalClient)
        assert not hasattr(client, "metrics_callback")
        assert performance_events(store) == []
    finally:
        store.db.close()
