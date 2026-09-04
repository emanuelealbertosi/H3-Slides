import json
from types import SimpleNamespace
from PIL import Image
import pytest
from h3_slides.diagram_layout import route_connection
from h3_slides.diagram_spec import Element, ManimSceneSpec
from h3_slides.diagrams import ManimRenderer, normalize_scene_geometry
from h3_slides.models import Generation, ProjectInput, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker, normalize_slide_candidate


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


def test_small_canvas_drift_is_repaired_without_changing_scene_meaning():
    value = sample_scene()
    value["elements"][0].update(x=.4, width=2.6)
    value["elements"][2].update(x=11.6, width=2.6)
    repaired, changed = normalize_scene_geometry(value)
    scene = ManimSceneSpec.model_validate(repaired)
    assert changed is True
    assert scene.elements[0].text == "Dati grezzi"
    assert scene.elements[2].text == "Risultato"
    assert scene.elements[0].x-scene.elements[0].width/2 >= .15
    assert scene.elements[2].x+scene.elements[2].width/2 <= 11.85


def test_overlapping_model_elements_are_repositioned_deterministically():
    value = sample_scene()
    value["elements"][1].update(x=value["elements"][0]["x"], y=value["elements"][0]["y"])
    repaired, changed = normalize_scene_geometry(value)
    scene = ManimSceneSpec.model_validate(repaired)
    assert changed is True
    assert scene.elements[0].text == "Dati grezzi"
    assert scene.elements[1].text == "Elaborazione"
    assert (scene.elements[1].x, scene.elements[1].y) != (scene.elements[0].x, scene.elements[0].y)


def test_first_stage_cannot_inject_or_duplicate_a_manim_scene():
    candidate = normalize_slide_candidate({"title":"Test","layout_variant":9,
        "diagram":{"kind":"manim","labels":["duplicato"],"brief":"Processo",
                   "scene":{"unexpected":"secondo compilatore"}}})
    assert candidate["layout_variant"] == 0
    assert candidate["diagram"]["labels"] == []
    assert candidate["diagram"]["scene"] is None
    wrapped = normalize_slide_candidate({"id":"slide","revision":2,"status":"ready",
                                         "content":{"title":"Contenuto corretto"}})
    assert wrapped == {"title":"Contenuto corretto","layout_variant":0}


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


@pytest.mark.asyncio
async def test_batch_creates_only_missing_diagrams_and_skips_cover(tmp_path):
    store = Store(tmp_path / "batch")
    project = store.create(ProjectInput(prompt="Algoritmi", count=3,
                                        use_manim_diagrams=True).model_dump())
    project["slides"] = [
        {"id":f"slide-{index}","revision":1,"status":"ready","purpose":title,
         "content":SlideContent(title=title, layout="cover" if index == 0 else "content").model_dump()}
        for index, title in enumerate(("Copertina", "Ricerca lineare", "Bubble sort"))
    ]
    store.save_project(project)
    calls = []
    class SceneLLM:
        def __init__(self, *_):
            pass
        async def prepare(self):
            pass
        async def json(self, prompt, **kwargs):
            calls.append(prompt)
            return sample_scene()
    class Renderer:
        async def render(self, pid, diagram, current):
            return {"engine":"manim","asset":"manim-"+str(len(calls))+".png",
                    "fingerprint":str(len(calls)),"width":1800,"height":1200,"report":{"ok":True}}
    worker = Worker(store, SimpleNamespace())
    worker.clients, worker.renderer = SceneLLM, Renderer()
    job = worker.submit(project["id"], Generation(provider={"mode":"local","model":"fake"},
                        prompt="Inserisci diagrammi", count=3, diagram_only=True))
    await worker.tasks[job["id"]]
    result = store.project(project["id"])
    assert store.job(job["id"])["status"] == "completed"
    assert "diagram_render" not in result["slides"][0]
    assert all(slide["diagram_render"]["engine"] == "manim" for slide in result["slides"][1:])
    assert len(calls) == 2
    store.db.close()


@pytest.mark.asyncio
async def test_invalid_optional_diagram_does_not_abort_slide_generation(tmp_path):
    store = Store(tmp_path / "fallback")
    project = store.create(ProjectInput(prompt="Spiega una ricerca", count=1,
                                        use_manim_diagrams=True).model_dump())
    project["slides"] = [{"id":"slide-1","revision":1,"status":"ready","purpose":"Ricerca",
                          "content":SlideContent(title="Ricerca").model_dump()}]
    store.save_project(project)

    class InvalidDiagramLLM:
        def __init__(self, *_):
            pass
        async def prepare(self):
            pass
        async def json(self, prompt, **kwargs):
            if "PROGETTA UNA SCENA MANIM" in prompt:
                broken = sample_scene()
                broken["elements"][1]["id"] = broken["elements"][0]["id"]
                return broken
            return SlideContent(title="Ricerca aggiornata", blocks=[
                {"heading":"Metodo","text":"La ricerca controlla ogni elemento in ordine e termina quando trova il valore desiderato oppure raggiunge la fine della collezione."}
            ], diagram={"kind":"manim","brief":"Mostra la ricerca"}).model_dump()

    worker = Worker(store, SimpleNamespace())
    worker.clients = InvalidDiagramLLM
    request = Generation(provider={"mode":"local","model":"fake"}, prompt="Rigenera",
                         count=1, slide_id="slide-1")
    job = worker.submit(project["id"], request)
    await worker.tasks[job["id"]]
    result = store.project(project["id"])
    assert store.job(job["id"])["status"] == "completed"
    assert result["slides"][0]["content"]["title"] == "Ricerca aggiornata"
    assert result["slides"][0]["content"]["diagram"]["kind"] == "none"
    assert "diagram_render" not in result["slides"][0]
    assert any("slide viene salvata senza diagramma" in event["message"]
               for event in store.job(job["id"])["events"])
    store.db.close()
