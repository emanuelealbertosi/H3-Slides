"""A visible HTTP draft must exist before the upstream completion is finished."""
import asyncio
import json
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from h3_slides.app import create_app


@pytest.mark.asyncio
async def test_sse_reaches_project_api_while_node_and_response_are_still_open(tmp_path):
    prefix_sent, grow, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    prefix = ('{"style":{"gap":32},"nodes":['
              '{"id":"title","parent":"root","kind":"heading","text":"Una pagina live"},'
              '{"id":"paragraph","parent":"root","kind":"text","text":"Il testo cresce')
    async def completion(request):
        body = await request.json()
        if not body["stream"]:
            return web.json_response({"choices":[{"message":{"content":json.dumps({"slides":[
                {"title":"Una pagina live","purpose":"Spiegare lo streaming"}]} )},"finish_reason":"stop"}]})
        response = web.StreamResponse(headers={"Content-Type":"text/event-stream"})
        await response.prepare(request)
        async def chunk(text, reason=None):
            event = {"choices":[{"index":0,"delta":{"content":text},"finish_reason":reason}]}
            await response.write(('data: '+json.dumps(event)+'\n\n').encode())
        await chunk(prefix)
        prefix_sent.set()
        await asyncio.wait_for(grow.wait(), timeout=10)
        await chunk(' mentre la risposta è ancora aperta')
        await asyncio.wait_for(finish.wait(), timeout=10)
        await chunk('."}],"notes":"","sources":[]}', 'stop')
        await response.write(b'data: [DONE]\n\n')
        return response
    provider = web.Application()
    provider.router.add_post('/v1/chat/completions', completion)
    app = create_app(Path(__file__).resolve().parents[1], tmp_path/'app')
    headers = {'X-H3-Slides':'1'}
    async with TestServer(provider) as upstream, TestClient(TestServer(app)) as browser:
        response = await browser.post('/api/projects', headers=headers, json={
            'title':'Streaming isolato', 'prompt':'Spiega una pagina', 'engine':'v2',
            'count':1, 'use_web_images':False, 'use_manim_diagrams':False})
        assert response.status == 201, await response.text()
        project = await response.json()
        pid = project['id']
        response = await browser.post(f'/api/projects/{pid}/generate', headers=headers, json={
            'provider':{'mode':'remote','model':'fake','remote_consent':True,
                        'base_url':str(upstream.make_url('/v1'))},
            'prompt':'Spiega una pagina', 'count':1})
        assert response.status == 202, await response.text()
        job = await response.json()
        async def wait_for_text(expected):
            async with asyncio.timeout(5):
                while True:
                    snapshot = await (await browser.get(f'/api/projects/{pid}')).json()
                    if snapshot['slides']:
                        slide = snapshot['slides'][0]
                        nodes = slide.get('page_draft',{}).get('nodes',[])
                        paragraph = next((n for n in nodes if n['id']=='paragraph'),None)
                        if paragraph and paragraph['text']==expected:
                            return slide
                    await asyncio.sleep(.025)
        try:
            await asyncio.wait_for(prefix_sent.wait(), timeout=5)
            first = await wait_for_text('Il testo cresce')
            assert first['status']=='generating' and first['content'].get('page') is None
            assert first['page_stream']['phase']=='writing'
            assert first['page_draft']['style']['gap']==32
            assert not finish.is_set()
            await asyncio.sleep(.3)  # A genuine next draft tick, not a wall of DB writes.
            grow.set()
            second = await wait_for_text('Il testo cresce mentre la risposta è ancora aperta')
            assert second['page_stream']['characters'] > first['page_stream']['characters']
            assert second['status']=='generating'
            finish.set()
            await asyncio.wait_for(app['worker'].tasks[job['id']], timeout=5)
            saved = await (await browser.get(f'/api/projects/{pid}')).json()
            slide = saved['slides'][0]
            assert slide['status']=='ready' and 'page_draft' not in slide and 'page_stream' not in slide
            assert slide['content']['page']['nodes'][1]['text'].endswith('ancora aperta.')
        finally:
            grow.set()
            finish.set()
