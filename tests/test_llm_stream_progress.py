"""Transport progress before completion, without leaking hidden model reasoning."""
import asyncio
import json
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from h3_slides.llm import LLM, _read_completion_stream
from h3_slides.models import Provider


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_first_visible_chunk_arrives_while_server_response_is_still_open(mode):
    received = asyncio.Event()
    bodies, chunks, notices = [], [], []
    async def complete(request):
        bodies.append(await request.json())
        response = web.StreamResponse(headers={"Content-Type": "Text/Event-Stream; charset=utf-8"})
        await response.prepare(request)
        for reasoning in ["PRIVATE THOUGHT A", "PRIVATE THOUGHT B"]:
            await response.write(('data: '+json.dumps({"choices":[{"delta":{"reasoning_content":reasoning}}]})+'\n\n').encode())
        await response.write(b'data: {"choices":[{"delta":{"content":"{\\"text\\":\\"Pri"}}]}\n\n')
        # Completion cannot be reached unless the caller gets the partial text.
        await asyncio.wait_for(received.wait(), timeout=2)
        await response.write(b'data: {"choices":[{"delta":{"content":"ma pagina\\"}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        return response
    app = web.Application()
    app.router.add_post('/v1/chat/completions', complete)
    async with TestServer(app) as server:
        client = LLM(Provider(mode="remote", model="test", remote_consent=True,
                             base_url=str(server.make_url('/v1'))), SimpleNamespace(last_used=0))
        await client.prepare()
        client.provider.mode = mode
        if mode == "local":
            from h3_slides.runtime_settings import InferenceSettings
            client.sampling = InferenceSettings().model_dump()
        client.event_callback = notices.append
        async def text(chunk):
            chunks.append(chunk)
            received.set()
        result = await client.json("Test", on_text=text)
    assert result == {"text":"Prima pagina"}
    assert len(chunks) == 2 and chunks[0] == '{"text":"Pri'
    assert bodies[0]["stream"] is True
    assert sum("elaborazione in corso" in n for n in notices) == 1
    assert sum("ricezione del contenuto" in n for n in notices) == 1
    assert not any("PRIVATE" in n for n in notices + chunks)


@pytest.mark.asyncio
async def test_server_ignoring_stream_reports_single_response_instead_of_fake_stream():
    notices, chunks = [], []
    async def complete(request):
        assert (await request.json())["stream"] is True
        return web.json_response({"choices":[{"message":{"content":'{"ok":true}'},"finish_reason":"stop"}]})
    app = web.Application()
    app.router.add_post('/v1/chat/completions', complete)
    async with TestServer(app) as server:
        client = LLM(Provider(mode="remote", model="test", remote_consent=True,
                             base_url=str(server.make_url('/v1'))), SimpleNamespace(last_used=0))
        await client.prepare()
        client.event_callback = notices.append
        async def text(chunk):
            chunks.append(chunk)
        assert await client.json("Test", on_text=text) == {"ok": True}
    assert chunks == ['{"ok":true}']
    assert any("risposta unica" in n for n in notices)
    assert not any("ricezione del contenuto in streaming" in n for n in notices)


@pytest.mark.asyncio
async def test_disconnect_keeps_delivered_prefix_and_never_replays_it():
    async def lines():
        yield b'data: {"choices":[{"delta":{"content":"{\\"text\\":\\"inizio"}}]}\n'
    chunks = []
    async def text(chunk):
        chunks.append(chunk)
    with pytest.raises(ValueError, match="interrotto"):
        await _read_completion_stream(SimpleNamespace(content=lines()), text)
    assert chunks == ['{"text":"inizio']
