"""Free research fallback orchestration; no network or real application data."""
import asyncio
import time

import pytest

from h3_slides.models import ProjectInput
from h3_slides.storage import Store
from h3_slides import web_research as wr


@pytest.fixture
def research(tmp_path, monkeypatch):
    store = Store(tmp_path)
    project = store.create(ProjectInput().model_dump())
    researcher = wr.WebResearch(store)
    calls, events = [], []
    effects = {}

    async def single(*args, **kwargs):
        provider = kwargs.get("provider", args[6] if len(args) > 6 else "wikipedia")
        query = kwargs.get("query", args[1] if len(args) > 1 else "")
        calls.append(provider)
        outcome = effects.get(provider)
        if isinstance(outcome, BaseException):
            raise outcome
        labels = {"searxng": "SearXNG locale", "wikipedia": "Wikipedia diretta",
                  "duckduckgo": "DuckDuckGo gratuito"}
        return {"provider": labels[provider], "query": query,
                "created_at": time.time(), "cache_used": False, "warnings": [],
                "sources": [{"id": "W1", "title": "Rivoluzione francese",
                             "url": "https://example.org/history",
                             "text": "Fonte di prova. " * 30,
                             "retrieved_at": time.time()}]}

    monkeypatch.setattr(researcher, "_collect_single", single)

    async def checkpoint():
        pass

    async def collect(**changes):
        options = {"pid": project["id"], "query": "Rivoluzione francese", "limit": 3,
                   "refresh": False, "event": events.append, "checkpoint": checkpoint,
                   "provider": "searxng", "endpoint": "http://127.0.0.1:8080",
                   "fallback": True}
        options.update(changes)
        return await researcher.collect(**options)

    yield collect, effects, calls, events
    store.db.close()


def attempt_statuses(data):
    return [(item["provider"], item["status"]) for item in data["fallback_attempts"]]


@pytest.mark.asyncio
async def test_available_selected_provider_never_calls_fallback(research):
    collect, _, calls, _ = research
    data = await collect()
    assert calls == ["searxng"]
    assert data["provider"] == "SearXNG locale"
    assert data["provider_id"] == data["requested_provider"] == "searxng"
    assert data["fallback_used"] is False
    assert attempt_statuses(data) == [("searxng", "completed")]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type,status", [("SearchUnavailable", "unavailable"),
                                               ("NoSearchResults", "no_results")])
async def test_selected_provider_availability_failure_uses_wikipedia(research, error_type, status):
    collect, effects, calls, events = research
    effects["searxng"] = getattr(wr, error_type)("SearXNG non disponibile")
    data = await collect()
    assert calls == ["searxng", "wikipedia"]
    assert data["provider"] == "Wikipedia diretta"
    assert data["provider_id"] == "wikipedia"
    assert data["requested_provider"] == "searxng"
    assert data["fallback_used"] is True
    assert attempt_statuses(data) == [("searxng", status), ("wikipedia", "completed")]
    assert events, "A provider switch must be visible in the generation log"


@pytest.mark.asyncio
@pytest.mark.parametrize("wiki_error", ["SearchUnavailable", "NoSearchResults"])
async def test_duckduckgo_is_used_only_after_wikipedia_availability_failure(research, wiki_error):
    collect, effects, calls, _ = research
    effects["searxng"] = wr.SearchUnavailable("Server offline")
    effects["wikipedia"] = getattr(wr, wiki_error)("Wikipedia senza fonti")
    data = await collect()
    assert calls == ["searxng", "wikipedia", "duckduckgo"]
    assert data["provider"] == "DuckDuckGo gratuito"
    assert data["provider_id"] == "duckduckgo"
    assert data["requested_provider"] == "searxng"
    assert data["fallback_used"] is True
    assert [item["provider"] for item in data["fallback_attempts"]] == calls
    assert data["fallback_attempts"][-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_explicit_opt_out_never_calls_other_providers(research):
    collect, effects, calls, _ = research
    effects["searxng"] = wr.SearchUnavailable("Server offline")
    with pytest.raises(wr.SearchUnavailable, match="offline"):
        await collect(fallback=False)
    assert calls == ["searxng"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["wikipedia", "duckduckgo"])
async def test_direct_provider_failure_does_not_start_searxng_fallback_chain(research, provider):
    collect, effects, calls, _ = research
    effects[provider] = wr.SearchUnavailable("Servizio offline")
    with pytest.raises(wr.SearchUnavailable):
        await collect(provider=provider)
    assert calls == [provider]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["searxng", "wikipedia"])
@pytest.mark.parametrize("message", ["CAPTCHA richiesto", "HTTP 403: accesso negato",
                                    "HTTP 429: limite del servizio", "Configurazione non valida"])
async def test_denials_and_other_value_errors_are_terminal(research, provider, message):
    collect, effects, calls, _ = research
    if provider == "wikipedia":
        effects["searxng"] = wr.SearchUnavailable("Server offline")
    effects[provider] = ValueError(message)
    with pytest.raises(ValueError, match=message):
        await collect()
    assert calls == (["searxng"] if provider == "searxng" else ["searxng", "wikipedia"])


@pytest.mark.asyncio
async def test_cancelled_request_never_starts_fallback(research):
    collect, effects, calls, _ = research
    effects["searxng"] = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await collect()
    assert calls == ["searxng"]


@pytest.mark.asyncio
async def test_checkpoint_cancellation_between_attempts_stops_chain(research):
    collect, effects, calls, _ = research
    effects["searxng"] = wr.SearchUnavailable("Server offline")

    async def stop_after_first():
        if calls:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await collect(checkpoint=stop_after_first)
    assert calls == ["searxng"]


@pytest.mark.asyncio
async def test_chain_cache_reuses_actual_provider_and_refresh_retries_selected(research):
    collect, effects, calls, _ = research
    effects["searxng"] = wr.SearchUnavailable("Server offline")
    first = await collect()
    cached = await collect()
    assert calls == ["searxng", "wikipedia"]
    assert cached["cache_used"] is True
    assert cached["provider_id"] == first["provider_id"] == "wikipedia"
    assert cached["fallback_used"] is True
    assert attempt_statuses(cached) == attempt_statuses(first)
    del effects["searxng"]
    fresh = await collect(refresh=True)
    assert calls == ["searxng", "wikipedia", "searxng"]
    assert fresh["provider_id"] == "searxng"
    assert fresh["fallback_used"] is False
    assert fresh["cache_used"] is False


@pytest.mark.asyncio
async def test_cached_fallback_is_not_used_after_opt_out(research):
    collect, effects, calls, _ = research
    effects["searxng"] = wr.SearchUnavailable("Server offline")
    await collect()
    with pytest.raises(wr.SearchUnavailable):
        await collect(fallback=False)
    assert calls == ["searxng", "wikipedia", "searxng"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"endpoint": "http://127.0.0.1:9090"},
                                    {"query": "Rivoluzione industriale"}, {"limit": 5}])
async def test_chain_cache_does_not_cross_endpoint_query_or_limit(research, change):
    collect, effects, calls, _ = research
    effects["searxng"] = wr.SearchUnavailable("Server offline")
    await collect()
    result = await collect(**change)
    assert calls == ["searxng", "wikipedia", "searxng", "wikipedia"]
    assert result["cache_used"] is False


@pytest.mark.asyncio
async def test_all_empty_searches_keep_no_results_exception_with_attempts(research):
    collect, effects, calls, _ = research
    for provider in ("searxng", "wikipedia", "duckduckgo"):
        effects[provider] = wr.NoSearchResults("Nessun risultato")
    with pytest.raises(wr.NoSearchResults) as error:
        await collect()
    assert calls == ["searxng", "wikipedia", "duckduckgo"]
    assert [item["provider"] for item in error.value.fallback_attempts] == calls
    assert all(item["status"] == "no_results" for item in error.value.fallback_attempts)


@pytest.mark.asyncio
async def test_empty_last_provider_does_not_hide_an_earlier_outage(research):
    collect, effects, calls, _ = research
    effects["searxng"] = wr.SearchUnavailable("Server offline")
    effects["wikipedia"] = wr.NoSearchResults("Nessun risultato")
    effects["duckduckgo"] = wr.NoSearchResults("Nessun risultato")
    with pytest.raises(wr.SearchUnavailable) as error:
        await collect()
    assert calls == ["searxng", "wikipedia", "duckduckgo"]
    assert error.value.fallback_attempts[0]["status"] == "unavailable"
