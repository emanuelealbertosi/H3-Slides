import json
from types import SimpleNamespace
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest
from h3_slides.llm import LLM
from h3_slides.models import Provider


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
