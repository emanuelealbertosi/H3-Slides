import json
from types import SimpleNamespace
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest
from h3_slides.llm import LLM, parse_json
from h3_slides.models import Provider
from h3_slides.runtime_settings import RemoteInferenceSettings


@pytest.mark.parametrize("raw", [
    'Risposta richiesta:\n{"ok":true}\nFine.',
    '~~~json\n{"ok":true}\n~~~',
    'Testo introduttivo\n[{"ok":true}]\nNota finale',
])
def test_json_parser_accepts_valid_wrapped_payload(raw):
    assert parse_json(raw) in ({"ok":True}, [{"ok":True}])


def test_json_parser_preserves_unescaped_latex_commands():
    parsed = parse_json(r'{"formula":"\(f(x)=\frac{1}{x}\)","integral":"\[\int x\,dx\]"}')
    assert parsed == {"formula": r"\(f(x)=\frac{1}{x}\)", "integral": r"\[\int x\,dx\]"}


@pytest.mark.asyncio
async def test_schema_is_both_visible_and_constrained():
    bodies = []
    async def complete(request):
        bodies.append(await request.json())
        return web.json_response({"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]})
    app = web.Application()
    app.router.add_post("/chat/completions", complete)
    async with TestServer(app) as server:
        client = LLM(Provider(model="test"), SimpleNamespace(last_used=0))
        client.url, client.model = str(server.make_url("")).rstrip("/"), "test"
        from h3_slides.runtime_settings import InferenceSettings
        client.sampling = InferenceSettings(temperature=.6, top_p=.8, top_k=20, min_p=.1,
                                           repeat_penalty=1.12, max_tokens=2048, seed=42).model_dump()
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        assert await client.json("Estrai i dati", schema=schema) == {"ok": True}
    body = bodies[0]
    assert json.dumps(schema, ensure_ascii=False) in body["messages"][1]["content"][0]["text"]
    assert body["response_format"]["schema"] == schema
    assert body["chat_template_kwargs"]["enable_thinking"] is False
    assert body["reasoning_effort"] == "none"
    for key, value in client.sampling.items():
        if key != "thinking":
            assert body[key] == value


@pytest.mark.asyncio
async def test_truncated_json_is_reported_without_exposing_response():
    async def complete(request):
        return web.json_response({"choices": [{"finish_reason": "length",
                                              "message": {"content": "PRIVATE DOCUMENT FRAGMENT"}}]})
    app = web.Application()
    app.router.add_post("/chat/completions", complete)
    async with TestServer(app) as server:
        client = LLM(Provider(model="test"), SimpleNamespace(last_used=0))
        client.url, client.model = str(server.make_url("")).rstrip("/"), "test"
        with pytest.raises(ValueError, match="troncata") as error:
            await client.json("Estrai i dati")
    assert "PRIVATE" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [12000, None])
async def test_api_inference_reaches_server(limit, monkeypatch):
    bodies, timeouts = [], []
    import aiohttp
    original = aiohttp.ClientSession
    def session(**kwargs):
        timeouts.append(kwargs["timeout"].total)
        return original(**kwargs)
    async def complete(request):
        bodies.append(await request.json())
        return web.json_response({"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]})
    app = web.Application()
    app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        provider = Provider(mode="remote", model="test-api", remote_consent=True,
                            base_url=str(server.make_url("/")),
                            inference=RemoteInferenceSettings(max_tokens=limit, temperature=.6, top_p=.8, timeout_seconds=900))
        client = LLM(provider, SimpleNamespace(last_used=0))
        monkeypatch.setattr(aiohttp, "ClientSession", session)
        await client.prepare()
        assert await client.json("Synthetic content") == {"ok": True}
    assert timeouts == [900]
    body = bodies[0]
    assert body["temperature"] == .6 and body["top_p"] == .8
    assert body["model"] == "test-api"
    if limit is None:
        assert "max_tokens" not in body
    else:
        assert body["max_tokens"] == limit
    assert not ({"timeout_seconds", "top_k", "min_p", "repeat_penalty", "chat_template_kwargs", "reasoning_effort"} & body.keys())


@pytest.mark.parametrize("setting", [
    {"max_tokens": 127}, {"max_tokens": 131073}, {"max_tokens": 200.5},
    {"temperature": -1}, {"temperature": 3}, {"top_p": 0}, {"top_p": 1.1},
    {"timeout_seconds": 29}, {"timeout_seconds": 3601}, {"unexpected": 1}
])
def test_invalid_api_inference_is_rejected(setting):
    with pytest.raises(ValueError):
        Provider(mode="remote", inference=setting)


def test_legacy_api_request_defaults_are_preserved():
    assert Provider(mode="remote").inference.model_dump() == {
        "max_tokens": 3500, "temperature": .35, "top_p": .95, "timeout_seconds": 360}


@pytest.mark.asyncio
async def test_remote_context_400_retries_with_smaller_output_without_leaking_body():
    requested = []
    async def complete(request):
        body = await request.json();requested.append(body["max_tokens"])
        if len(requested) == 1:
            return web.json_response({"error": {"message":
                "maximum context length exceeded PRIVATE DOCUMENT"}}, status=400)
        return web.json_response({"choices": [{"finish_reason": "stop",
            "message": {"content": '{"ok":true}'}}]})
    app = web.Application();app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        provider = Provider(mode="remote", model="test", remote_consent=True,
                            base_url=str(server.make_url("/")))
        client = LLM(provider, SimpleNamespace(last_used=0));await client.prepare()
        assert await client.json("Synthetic content") == {"ok": True}
    assert requested == [3500, 1600]


@pytest.mark.asyncio
async def test_remote_400_category_is_helpful_but_body_stays_private():
    async def complete(request):
        return web.json_response({"error": {"message":
            "json_schema unsupported PRIVATE DOCUMENT"}}, status=400)
    app = web.Application();app.router.add_post("/v1/chat/completions", complete)
    async with TestServer(app) as server:
        provider = Provider(mode="remote", model="test", remote_consent=True,
                            base_url=str(server.make_url("/")))
        client = LLM(provider, SimpleNamespace(last_used=0));await client.prepare()
        with pytest.raises(RuntimeError, match="formato JSON") as error:
            await client.json("Synthetic content")
    assert "PRIVATE" not in str(error.value)
