import asyncio
import copy
import json
from types import SimpleNamespace
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from h3_slides.llm import LLM
from h3_slides.models import Generation, Provider, ProjectInput, SlideContent
from h3_slides.page_v2 import PageSpec, PageStream, PAGE_SYSTEM
from h3_slides.storage import Store
from h3_slides.worker import Worker
from h3_slides.worker_v2 import run_pages
from h3_slides.content_rules import content_contract


def page_data():
    return {"style": {"gap": 30}, "nodes": [
        {"id": "title", "kind": "heading", "text": "Sette concetti", "style": {"font_size": 48}},
        {"id": "grid", "kind": "group", "style": {"flow": "columns", "columns": [2, 1, 1]}},
        *[{"id": f"p{i}", "parent": "grid", "kind": "text", "text": f"Concetto {i}: una spiegazione completa."}
          for i in range(7)]]}


def test_more_than_four_blocks_and_legacy_contract():
    page = PageSpec.model_validate(page_data())
    assert len(page.nodes) == 9
    assert SlideContent(title="Test", page=page).page == page
    schema, _ = content_contract({})
    assert "page" not in schema["properties"]
    assert not {"PageSpec", "PageNode", "PageStyle"} & schema["$defs"].keys()
    assert ProjectInput().engine == "classic"


@pytest.mark.parametrize("change", [
    lambda p: p["nodes"].append({"id": "title", "kind": "text"}),
    lambda p: p["nodes"].append({"id": "bad", "kind": "text", "parent": "p1"}),
    lambda p: p["nodes"].append({"id": "bad", "kind": "text", "parent": "bad"}),
    lambda p: p["nodes"].append({"id": "bad", "kind": "script"}),
    lambda p: p["nodes"][0].update(style={"position": "fixed"}),
    lambda p: p["nodes"][0].update(asset_id="../../secret.jpg"),
    lambda p: p["nodes"][1].update(style={"columns": [float("nan"), 1]}),
])
def test_invalid_tree_or_active_content_rejected(change):
    data = page_data(); change(data)
    with pytest.raises(ValueError):
        PageSpec.model_validate(data)


def test_incremental_parser_never_exposes_half_a_node():
    text = json.dumps(page_data())
    parser = PageStream(); counts = []
    for char in text:
        draft = parser.feed(char)
        if draft:
            counts.append(len(draft["nodes"]))
    assert counts == list(range(1, 10))
    assert parser.nodes == PageSpec.model_validate(page_data()).nodes


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_real_sse_transport_and_custom_system(mode):
    bodies, chunks = [], []
    async def complete(request):
        body = await request.json(); bodies.append(body)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        text = json.dumps(page_data(), ensure_ascii=False)
        for start in range(0, len(text), 31):
            packet = {"choices": [{"index": 0, "delta": {"content": text[start:start+31]}, "finish_reason": None}]}
            await response.write(('data: '+json.dumps(packet)+'\n\n').encode())
        await response.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":20}}\n\ndata: [DONE]\n\n')
        return response
    app = web.Application(); app.router.add_post('/v1/chat/completions', complete)
    async with TestServer(app) as server:
        client = LLM(Provider(mode="remote", remote_consent=True, model="fixture", base_url=str(server.make_url('/'))), SimpleNamespace(last_used=0))
        await client.prepare(); client.provider.mode = mode
        from h3_slides.runtime_settings import InferenceSettings
        if mode == "local": client.sampling = InferenceSettings().model_dump()
        async def collect(text): chunks.append(text)
        result = await client.json("Test", schema=PageSpec.model_json_schema(), system=PAGE_SYSTEM, on_text=collect)
        assert result == page_data() and len(chunks) > 5
        assert bodies[0]["stream"] is True and bodies[0]["messages"][0]["content"] == PAGE_SYSTEM
        assert client.last_metrics["output_tokens"] == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "disconnect", "concurrent", "invalid_asset"])
async def test_worker_drafts_commit_recovery_and_revision(tmp_path, failure):
    store = Store(tmp_path/'data')
    project = store.create(ProjectInput(engine="v2", prompt="Spiega sette concetti", count=1).model_dump())
    pid = project["id"]
    store.save_job({"id": "job", "status": "running", "events": []})
    worker = Worker(store, SimpleNamespace())
    drafts = []
    class Client:
        async def json(self, prompt, schema=None, **kwargs):
            if "on_text" not in kwargs:
                return {"slides": [{"title": "Sette concetti", "purpose": "Spiegazione"}]}
            data = page_data()
            if failure == "invalid_asset": data["nodes"].append({"id": "pic", "kind": "image", "asset_id": "abc.jpg"})
            text = json.dumps(data)
            for start in range(0, len(text), 50):
                await kwargs["on_text"](text[start:start+50])
                current = store.project(pid)
                draft = current["slides"][0].get("page_draft")
                if draft:
                    drafts.append(draft)
                    if failure == "disconnect": raise ValueError("disconnected")
                    if failure == "concurrent":
                        current["slides"][0]["revision"] += 1
                        current["slides"][0]["content"]["title"] = "Modifica utente"
                        store.save_project(current)
            return data
    request = Generation(provider=Provider(), prompt="Spiega sette concetti", count=1)
    if failure:
        with pytest.raises(ValueError): await run_pages(worker, Client(), "job", pid, request, "", [])
    else:
        await run_pages(worker, Client(), "job", pid, request, "", [])
    result = store.project(pid)["slides"][0]
    assert drafts
    if failure == "concurrent": assert result["content"]["title"] == "Modifica utente"
    elif failure:
        assert result["status"] == "failed" and result["page_draft"]
        assert result["content"].get("page") is None
    else:
        assert result["status"] == "ready" and len(result["content"]["page"]["nodes"]) == 9
        assert "page_draft" not in result and store.job("job")["status"] == "completed"


@pytest.mark.asyncio
async def test_page_upload_and_project_asset_validation(tmp_path):
    import io
    from pathlib import Path
    import aiohttp
    from PIL import Image
    from aiohttp.test_utils import TestClient
    from h3_slides.app import create_app
    app = create_app(Path(__file__).resolve().parents[1], tmp_path/'api')
    store = app['store']; project = store.create(ProjectInput(engine='v2').model_dump())
    page = page_data(); page['nodes'] += [{'id': 'pic', 'kind': 'image'}, {'id': 'other', 'kind': 'image'}]
    content = SlideContent(title='Test', page=page).model_dump()
    project['slides'] = [{'id': 's', 'revision': 1, 'status': 'ready', 'content': content}]
    store.save_project(project);headers={'X-H3-Slides':'1'}
    raw=io.BytesIO();Image.new('RGB',(60,80),'navy').save(raw,format='PNG')
    async with TestClient(TestServer(app)) as client:
        url=f"/api/projects/{project['id']}/slides/s"
        form=aiohttp.FormData();form.add_field('revision','1');form.add_field('node_id','pic')
        form.add_field('file',raw.getvalue(),filename='test.png',content_type='image/png')
        response=await client.post(url+'/image',headers=headers,data=form)
        assert response.status==200,await response.text()
        result=await response.json();content=result['slide']['content']
        assert content['page']['nodes'][-2]['asset_id']==result['visual_asset']['id']
        assert content['page']['nodes'][-1]['asset_id']=='' and not content['image_id']
        content['page']['nodes'][-1]['asset_id']='abc.jpg'
        response=await client.patch(url,headers=headers,json={'revision':2,'content':content})
        assert response.status==400
        assert store.project(project['id'])['slides'][0]['revision']==2


@pytest.mark.asyncio
async def test_single_manim_node_redesign_keeps_other_nodes(tmp_path, monkeypatch):
    store=Store(tmp_path/'data');project=store.create(ProjectInput(engine='v2',use_manim_diagrams=True).model_dump())
    page=page_data();page['nodes'].append({'id':'chart','parent':'grid','kind':'diagram','text':'Una funzione'})
    content=SlideContent(title='Test',page=page).model_dump()
    project['slides']=[{'id':'s','revision':1,'status':'ready','content':content}];store.save_project(project)
    store.save_job({'id':'job','status':'running','events':[]})
    async def design(*args):return {'kind':'manim'},{'asset':'manim-'+'a'*64+'.png','engine':'manim'}
    monkeypatch.setattr('h3_slides.worker_v2.design_diagram',design)
    request=Generation(provider=Provider(),prompt='Grafico y=1/x',slide_id='s',page_node_id='chart',diagram_only=True)
    await run_pages(Worker(store,SimpleNamespace()),SimpleNamespace(),'job',project['id'],request,'',[])
    result=store.project(project['id'])['slides'][0]
    assert result['revision']==2
    assert result['content']['page']['nodes'][:-1]==content['page']['nodes'][:-1]
    assert result['content']['page']['nodes'][-1]['asset_id'].startswith('manim-')
    assert 'chart' in result['page_diagrams']
