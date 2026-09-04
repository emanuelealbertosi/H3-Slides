import json
from types import SimpleNamespace
from PIL import Image
import pytest
from h3_slides.diagram_layout import route_connection
from h3_slides.diagram_spec import Element, ManimSceneSpec
from h3_slides.diagrams import ManimRenderer
from h3_slides.models import Generation, ProjectInput, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker


def sample_scene():
    return {"title": "Dal dato alla decisione", "takeaway": "La trasformazione rende il dato utilizzabile.",
            "elements": [
                {"id":"fonte","type":"database","x":1.7,"y":2.3,"width":2.6,"height":1.3,
                 "text":"Dati grezzi","caption":"input","tone":"blue","stage":1},
                {"id":"processo","type":"box","x":6,"y":2.3,"width":3.0,"height":1.3,
                 "text":"Elaborazione","caption":"regole","tone":"accent","stage":2},
                {"id":"esito","type":"document","x":10.3,"y":2.3,"width":2.6,"height":1.3,
                 "text":"Risultato","caption":"verifica","tone":"amber","stage":3},
                {"id":"pixel","type":"grid","x":3.0,"y":5.25,"width":4.7,"height":3.2,
                 "text":"Campione immagine","caption":"intensità normalizzata","tone":"violet","stage":1,
                 "values":[0,.25,.5,.75,.25,.5,.75,1,.5,.75,1,.25,.75,1,.25,.5],"columns":4},
                {"id":"misure","type":"bars","x":9.0,"y":5.25,"width":4.7,"height":3.2,
                 "text":"Confronto misure","caption":"valori osservati","tone":"red","stage":3,
                 "values":[12,21,16],"labels":["A","B","C"],"columns":3}],
            "connections":[
                {"source":"fonte","target":"processo","label":"alimenta","tone":"blue"},
                {"source":"processo","target":"esito","label":"produce","tone":"amber"}]}


def test_scene_rejects_overlap_and_executable_fields():
    scene = sample_scene()
    scene["elements"][1]["x"] = 1.8
    with pytest.raises(ValueError, match="sovrapposti"):
        ManimSceneSpec.model_validate(scene)
    scene = sample_scene()
    scene["elements"][0]["python"] = "open('private.txt').read()"
    with pytest.raises(ValueError):
        ManimSceneSpec.model_validate(scene)


def test_router_avoids_every_unrelated_element():
    scene = ManimSceneSpec.model_validate(sample_scene())
    route = route_connection(scene.elements[0], scene.elements[2], scene.elements)
    assert len(route) >= 4  # The processing block forces a real detour.
    assert route[0] != route[-1]


@pytest.mark.asyncio
async def test_real_manim_render_is_verified_and_cached(tmp_path):
    store = Store(tmp_path / "data")
    project = store.create(ProjectInput(prompt="Test", use_manim_diagrams=True,
                                        theme="paper", font="Segoe UI").model_dump())
    renderer = ManimRenderer(store)
    diagram = {"kind":"manim","labels":[],"brief":"Spiega il flusso e i dati","scene":sample_scene()}
    rendered = await renderer.render(project["id"], diagram, project)
    assert rendered["engine"] == "manim"
    assert rendered["report"]["ok"] and rendered["report"]["bounds_checked"]
    assert rendered["report"]["min_font_size"] >= 20
    assert {"database","document","grid","bars"} <= set(rendered["report"]["types"])
    path = store.asset_path(project["id"], rendered["asset"])
    with Image.open(path) as image:
        assert image.size == (1800, 1200)
    again = await renderer.render(project["id"], diagram, project)
    assert again["cached"] is True and again["fingerprint"] == rendered["fingerprint"]
    stored = json.loads(store.asset_path(project["id"],
                        rendered["asset"].removesuffix(".png")+".json").read_text(encoding="utf-8"))
    assert stored["engine"] == "manim"
    store.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_diagram_design_uses_the_selected_local_or_remote_client(tmp_path, mode):
    store = Store(tmp_path / mode)
    project = store.create(ProjectInput(prompt="Spiega il processo", count=1,
                                        use_manim_diagrams=True).model_dump())
    project["slides"] = [{"id":"slide-1","revision":1,"status":"ready","purpose":"Il processo",
                          "content":SlideContent(title="Il processo").model_dump()}]
    store.save_project(project)
    selected = []

    class SceneLLM:
        def __init__(self, provider, _manager):
            self.provider = provider
            selected.append((provider.mode, provider.model, provider.base_url))
        async def prepare(self):
            pass
        async def json(self, prompt, schema=None, images=None):
            assert "SCENA MANIM" in prompt
            assert schema["additionalProperties"] is False
            return sample_scene()

    class Renderer:
        async def render(self, pid, diagram, current):
            assert pid == project["id"] and diagram["kind"] == "manim"
            return {"engine":"manim","asset":"manim-test.png","fingerprint":"test",
                    "width":1800,"height":1200,"report":{"ok":True}}

    worker = Worker(store, SimpleNamespace())
    worker.clients, worker.renderer = SceneLLM, Renderer()
    provider = {"mode":mode,"model":"server/model" if mode == "remote" else "fake.gguf"}
    if mode == "remote":
        provider.update(base_url="http://127.0.0.1:1234", remote_consent=True)
    request = Generation(provider=provider, prompt="Mostra input, trasformazione e risultato",
                         count=1, slide_id="slide-1", diagram_only=True)
    job = worker.submit(project["id"], request)
    await worker.tasks[job["id"]]
    result = store.project(project["id"])
    assert store.job(job["id"])["status"] == "completed"
    assert selected[0][0] == mode
    assert result["slides"][0]["content"]["diagram"]["scene"]["title"] == "Dal dato alla decisione"
    assert result["slides"][0]["diagram_render"]["engine"] == "manim"
    store.db.close()
