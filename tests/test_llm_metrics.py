import asyncio
import json
import logging
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from h3_slides.llm import LLM
from h3_slides.llm_metrics import completion_metrics, local_performance_message
from h3_slides.models import Provider


def test_wall_clock_is_not_reported_as_decode_speed():
    metrics = completion_metrics({"usage": {"prompt_tokens": 1000, "completion_tokens": 400}}, 20)
    assert metrics["end_to_end_output_tokens_per_second"] == 20
    assert metrics["server_decode_tokens_per_second"] is None
    assert metrics["server_ttft_seconds"] is None
    assert metrics["server_prefill_seconds"] is None
    assert metrics["server_prefill_tokens_per_second"] is None
    assert metrics["server_prefill_tokens"] is None
    assert metrics["server_decode_tokens"] is None
    assert metrics["input_cached_tokens"] is None


def test_lm_studio_and_llama_native_statistics_are_optional():
    metrics = completion_metrics({"usage": {"completion_tokens": 400,
        "completion_tokens_details": {"reasoning_tokens": 50}},
        "stats": {"tokens_per_second": 50, "time_to_first_token": 12, "generation_time": 8}}, 20)
    assert metrics["server_decode_tokens_per_second"] == 50
    assert metrics["end_to_end_output_tokens_per_second"] == 20
    assert metrics["server_ttft_seconds"] == 12
    assert metrics["server_generation_seconds"] == 8
    assert metrics["reasoning_tokens"] == 50
    metrics = completion_metrics({"timings": {"prompt_ms": 1250, "predicted_ms": 8000,
                                               "predicted_per_second": 50}}, 9.5)
    assert metrics["server_prefill_seconds"] == 1.25
    assert metrics["server_generation_seconds"] == 8
    assert metrics["server_decode_tokens_per_second"] == 50


@pytest.mark.parametrize("bad", [None, [], "PRIVATE", {}, -1, True, float("nan"), float("inf"), 10**400])
def test_untrusted_metrics_cannot_leak_content_or_break_serialization(bad):
    metrics = completion_metrics({"usage": {"prompt_tokens": bad, "completion_tokens": bad,
        "completion_tokens_details": {"reasoning_tokens": bad}, "prompt_tokens_details": {"cached_tokens": bad}},
        "stats": {"tokens_per_second": bad, "time_to_first_token": bad, "generation_time": bad},
        "timings": {"prompt_ms": bad, "predicted_per_second": bad, "predicted_ms": bad,
                    "prompt_n": bad, "predicted_n": bad, "prompt_per_second": bad, "cache_n": bad},
        "choices": [{"finish_reason": "PRIVATE PROVIDER OUTPUT"}], "api_key": "SECRET"}, bad)
    assert all(value is None for key, value in metrics.items() if key != "finish")
    assert metrics["finish"] == "other"
    assert "PRIVATE" not in json.dumps(metrics, allow_nan=False)
    assert "SECRET" not in json.dumps(metrics, allow_nan=False)


def test_native_counts_and_cached_input_are_kept_separate_from_total_usage():
    metrics = completion_metrics({
        "usage": {"prompt_tokens": 10000, "completion_tokens": 401,
                  "prompt_tokens_details": {"cached_tokens": 9800}},
        "timings": {"prompt_n": 200, "predicted_n": 400, "prompt_ms": 500,
                    "predicted_ms": 8000, "prompt_per_second": 405, "predicted_per_second": 51},
    }, 20)
    assert metrics["input_tokens"] == 10000
    assert metrics["input_cached_tokens"] == 9800
    assert metrics["output_tokens"] == 401
    assert metrics["server_prefill_tokens"] == 200
    assert metrics["server_decode_tokens"] == 400
    assert metrics["server_prefill_tokens_per_second"] == 405
    assert metrics["server_decode_tokens_per_second"] == 51
    assert metrics["end_to_end_output_tokens_per_second"] == 20.05


def test_only_prefill_rate_is_derived_from_native_counts_and_duration():
    metrics = completion_metrics({
        "usage": {"prompt_tokens": 5000, "completion_tokens": 900},
        "timings": {"prompt_n": 100, "predicted_n": 400, "prompt_ms": 250, "predicted_ms": 8000},
    }, 100)
    assert metrics["server_prefill_tokens_per_second"] == 400
    assert metrics["server_decode_tokens_per_second"] is None
    assert metrics["end_to_end_output_tokens_per_second"] == 9
    without_native_counts = completion_metrics({
        "usage": {"prompt_tokens": 5000, "completion_tokens": 900,
                  "prompt_tokens_details": {"cached_tokens": 4900}},
        "timings": {"prompt_ms": 250, "predicted_ms": 8000},
    }, 100)
    assert without_native_counts["server_prefill_tokens_per_second"] is None
    assert without_native_counts["server_decode_tokens_per_second"] is None


def test_native_count_without_usage_does_not_masquerade_as_total_input():
    metrics = completion_metrics({"timings": {"prompt_n": 20, "predicted_n": 60,
                                               "prompt_ms": 40, "predicted_ms": 1500}}, 2)
    assert metrics["input_tokens"] is None
    assert metrics["output_tokens"] is None
    assert metrics["server_prefill_tokens"] == 20
    assert metrics["server_decode_tokens"] == 60
    assert metrics["server_prefill_tokens_per_second"] == 500
    assert metrics["server_decode_tokens_per_second"] is None


def test_decode_rate_comes_from_server_not_a_guessed_first_token_convention():
    metrics = completion_metrics({"timings": {"predicted_n": 101, "predicted_ms": 2000,
                                               "predicted_per_second": 50}}, 5)
    assert metrics["server_decode_tokens"] == 101
    assert metrics["server_generation_seconds"] == 2
    assert metrics["server_decode_tokens_per_second"] == 50
    missing = completion_metrics({"timings": {"predicted_n": 101, "predicted_ms": 2000}}, 5)
    assert missing["server_decode_tokens_per_second"] is None


@pytest.mark.parametrize("usage_cache,native_cache,expected", [
    (None, 100, 100), (None, 0, 0), (200, 100, 200), (0, 100, 0),
    ("bad", 100, 100), (None, None, None),
])
def test_input_cache_prefers_usage_and_falls_back_to_native_cache_count(usage_cache, native_cache, expected):
    metrics = completion_metrics({"usage": {"prompt_tokens_details": {"cached_tokens": usage_cache}},
                                  "timings": {"cache_n": native_cache}}, 2)
    assert metrics["input_cached_tokens"] == expected


@pytest.mark.parametrize("bad", ["100", "0", -1, True, [], {}, float("nan"), float("inf"), 10**400])
def test_native_cache_count_cannot_supply_untrusted_values(bad):
    metrics = completion_metrics({"timings": {"cache_n": bad}}, 2)
    assert metrics["input_cached_tokens"] is None
    assert "PRIVATE" not in json.dumps(metrics, allow_nan=False)


def test_zero_counts_and_times_do_not_divide_or_turn_missing_data_into_zero():
    metrics = completion_metrics({"usage": {"prompt_tokens_details": {"cached_tokens": 0}},
        "timings": {"prompt_n": 0, "predicted_n": 0, "prompt_ms": 0, "predicted_ms": 0}}, 0)
    assert metrics["input_cached_tokens"] == 0
    assert metrics["server_prefill_tokens"] == metrics["server_decode_tokens"] == 0
    assert metrics["server_prefill_seconds"] == metrics["server_generation_seconds"] == 0
    assert metrics["server_prefill_tokens_per_second"] is None
    assert metrics["server_decode_tokens_per_second"] is None
    line = local_performance_message(metrics, 1)
    assert "Prefill: 0 token · 0.000s · n.d." in line
    assert "Generazione: 0 token · 0.000s · n.d." in line
    assert "Cache input: 0 token" in line


@pytest.mark.parametrize("bad", ["100", "0", -1, True, [], {}, float("nan"), float("inf"), 10**400])
def test_invalid_native_counters_and_cache_details_are_not_coerced(bad):
    metrics = completion_metrics({
        "usage": {"prompt_tokens_details": {"cached_tokens": bad}},
        "timings": {"prompt_n": bad, "predicted_n": bad, "prompt_ms": 1000, "predicted_ms": 1000},
    }, 3)
    assert metrics["input_cached_tokens"] is None
    assert metrics["server_prefill_tokens"] is None
    assert metrics["server_decode_tokens"] is None
    assert metrics["server_prefill_tokens_per_second"] is None
    assert metrics["server_decode_tokens_per_second"] is None


def test_overflowing_native_rate_is_ignored():
    metrics = completion_metrics({"timings": {"prompt_n": 1e308, "predicted_n": 1e308,
        "prompt_ms": 0.001, "predicted_ms": 0.001}}, 1e-20)
    assert metrics["server_prefill_tokens_per_second"] is None
    assert metrics["server_decode_tokens_per_second"] is None
    json.dumps(metrics, allow_nan=False)


def test_local_log_has_separate_phases_cache_and_wall_time():
    metrics = completion_metrics({"usage": {"prompt_tokens": 1000, "completion_tokens": 401,
        "prompt_tokens_details": {"cached_tokens": 900}},
        "timings": {"prompt_n": 100, "prompt_ms": 1250, "predicted_n": 400, "predicted_ms": 8000,
                    "predicted_per_second": 50}}, 10.12345)
    metrics.update(outcome="response_received", attempts=1)
    assert local_performance_message(metrics, 2) == (
        "LLM interno #2 · Prefill: 100 token · 1.250s · 80.00 token/s | "
        "Generazione: 400 token · 8.000s · 50.00 token/s | Cache input: 900 token | "
        "Totale richiesta: 10.123s")


def test_local_log_falls_back_to_output_usage_count_not_wall_clock_speed():
    metrics = completion_metrics({"usage": {"prompt_tokens": 9999, "completion_tokens": 20}}, 2)
    line = local_performance_message(metrics, 3)
    assert "Prefill: n.d. · n.d. · n.d." in line
    assert "Generazione: 20 token · n.d. · n.d." in line
    assert "10.00 token/s" not in line and "9999" not in line
    assert "Cache input: n.d." in line
    assert "Totale richiesta: 2.000s" in line


@pytest.mark.parametrize("outcome,label", [("error", "errore"), ("timeout", "timeout"),
    ("connection_error", "errore di connessione"), ("cancelled", "annullata")])
def test_local_log_uses_only_fixed_error_labels_and_numeric_attempts(outcome, label):
    metrics = completion_metrics(None, 12)
    metrics.update(outcome=outcome, attempts=3)
    line = local_performance_message(metrics, 4)
    assert line.endswith(f" | Esito: {label} | Tentativi: 3")
    assert "Totale richiesta: 12.000s" in line


@pytest.mark.parametrize("bad", [None, [], {}, "PRIVATE\nTOKEN", -1, True, float("nan"), float("inf"), 10**400])
def test_local_log_does_not_interpolate_unknown_or_untrusted_values(bad):
    keys = ["server_prefill_tokens", "server_decode_tokens", "server_prefill_seconds", "server_generation_seconds",
            "server_prefill_tokens_per_second", "server_decode_tokens_per_second", "input_cached_tokens",
            "output_tokens", "request_seconds", "outcome", "attempts"]
    metrics = dict.fromkeys(keys, bad)
    metrics.update(model="PRIVATE_MODEL", prompt="PRIVATE_PROMPT", reasoning="PRIVATE_THOUGHTS",
                   url="http://private", api_key="PRIVATE_KEY")
    line = local_performance_message(metrics, bad)
    assert line == ("LLM interno #n.d. · Prefill: n.d. · n.d. · n.d. | Generazione: n.d. · n.d. · n.d. | "
                    "Cache input: n.d. | Totale richiesta: n.d.")
    assert "PRIVATE" not in line and "\n" not in line and "http" not in line


@pytest.mark.parametrize("attempts", [None, 0, 1, "2", True, 2.5])
def test_local_log_omits_single_or_invalid_attempt_counts(attempts):
    assert "Tentativi" not in local_performance_message({"attempts": attempts}, 1)


@pytest.mark.parametrize("value", [None, [], "PRIVATE", {"usage": [], "stats": "PRIVATE", "timings": False, "choices": {}}])
def test_malformed_optional_objects_are_ignored(value):
    metrics = completion_metrics(value, 0)
    assert metrics["request_seconds"] == 0
    assert metrics["end_to_end_output_tokens_per_second"] is None
    assert metrics["server_decode_tokens_per_second"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", [False, True])
async def test_metrics_do_not_change_requests_or_expose_documents(retry, caplog):
    bodies = []
    async def complete(request):
        body = await request.json()
        bodies.append(body)
        if retry and len(bodies) == 1:
            return web.json_response({"error": "response_format unsupported PRIVATE"}, status=400)
        return web.json_response({"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            "stats": {"tokens_per_second": 45, "time_to_first_token": 1, "private": "SECRET"}})
    app = web.Application()
    app.router.add_post("/v1/chat/completions", complete)
    caplog.set_level(logging.INFO)
    async with TestServer(app) as server:
        client = LLM(Provider(mode="remote", model="model-private-name", remote_consent=True,
                             api_key="PRIVATE-KEY", base_url=str(server.make_url("/"))), SimpleNamespace(last_used=0))
        await client.prepare()
        assert await client.json("PRIVATE DOCUMENT") == {"ok": True}
    assert len(bodies) == 1 + int(retry)
    assert client.last_metrics["attempts"] == len(bodies)
    assert client.last_metrics["http_status"] == 200
    assert client.last_metrics["outcome"] == "response_received"
    assert client.last_metrics["server_decode_tokens_per_second"] == 45
    assert client.last_metrics["input_tokens"] == 100
    assert client.last_metrics["output_tokens"] == 20
    assert bodies[0]["messages"][1]["content"][0]["text"] == "PRIVATE DOCUMENT"
    assert bodies[0]["stream"] is False
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert "LLM prestazioni:" in caplog.text
    assert "PRIVATE" not in caplog.text
    assert "SECRET" not in caplog.text
    assert "model-private-name" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("error,outcome", [(TimeoutError(), "timeout"),
    (aiohttp.ClientConnectionError("SECRET"), "connection_error"), (asyncio.CancelledError(), "cancelled")])
async def test_failed_and_cancelled_requests_record_timings(monkeypatch, caplog, error, outcome):
    class FailingSession:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            raise error
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(aiohttp, "ClientSession", FailingSession)
    caplog.set_level(logging.INFO)
    client = LLM(Provider(mode="remote", model="test", remote_consent=True,
                         base_url="http://localhost:1234"), SimpleNamespace(last_used=0))
    await client.prepare()
    with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else ValueError):
        await client.json("PRIVATE DOCUMENT")
    assert client.last_metrics["outcome"] == outcome
    assert client.last_metrics["attempts"] == 0
    assert client.last_metrics["http_status"] is None
    assert client.last_metrics["request_seconds"] >= 0
    assert client.last_metrics["server_decode_tokens_per_second"] is None
    assert "PRIVATE" not in caplog.text and "SECRET" not in caplog.text
