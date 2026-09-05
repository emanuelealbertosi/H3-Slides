import json
from types import SimpleNamespace
from PIL import Image
import pytest
from manim import tempconfig
from h3_slides.diagram_layout import route_connection
from h3_slides.diagram_spec import Element, ManimSceneSpec
from h3_slides.diagrams import (ManimRenderer, fallback_diagram, normalize_scene_geometry,
                                requested_family, simplify_connection_labels,
                                validate_designed_scene)
from h3_slides.manim_scene import build_scene
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
    boxes = {"title":"Flusso","elements":[
        {"id":f"n{i}","type":"box","x":2+i*4,"y":4,"width":2.5,"height":1.2,"text":str(i)}
        for i in range(3)], "connections":[
        {"source":"n0","target":"n1"},{"source":"n1","target":"n2"}]}
    # Historical/manual scenes remain loadable, while a newly AI-designed
    # all-box flow is rejected by the editorial pass.
    box_scene = ManimSceneSpec.model_validate(boxes)
    with pytest.raises(ValueError, match="solo da rettangoli"):
        validate_designed_scene(box_scene)


def test_router_avoids_every_unrelated_element():
    scene = ManimSceneSpec.model_validate(sample_scene())
    route = route_connection(scene.elements[0], scene.elements[2], scene.elements)
    assert len(route) >= 4  # The processing block forces a real detour.
    assert route[0] != route[-1]


def test_connection_label_rescue_keeps_shapes_arrows_and_decision_meaning():
    scene = ManimSceneSpec.model_validate({"title":"Scelta","elements":[
        {"id":"start","type":"circle","x":2,"y":4,"width":2.5,"height":1.4,"text":"Inizio"},
        {"id":"choice","type":"decision","x":6,"y":4,"width":2.5,"height":1.6,"text":"Valido?"},
        {"id":"end","type":"circle","x":10,"y":4,"width":2.5,"height":1.4,"text":"Fine"}],
        "connections":[
            {"source":"start","target":"choice","label":"verifica il dato"},
            {"source":"choice","target":"end","label":"Sì, continua"}]})
    rescued = simplify_connection_labels(scene)
    assert [element.type for element in rescued.elements] == ["circle","decision","circle"]
    assert [(edge.source, edge.target) for edge in rescued.connections] == [
        ("start","choice"),("choice","end")]
    assert rescued.connections[0].label == ""
    assert rescued.connections[1].label
    assert len(rescued.connections[1].label) <= 8


@pytest.mark.asyncio
async def test_label_placement_is_repaired_before_calling_the_model_again():
    from h3_slides.diagrams import design_diagram
    calls, renders, events = [], [], []

    class Client:
        async def json(self, prompt, schema=None):
            calls.append(prompt)
            return sample_scene()

    class Renderer:
        async def render(self, pid, diagram, project):
            renders.append(diagram)
            if len(renders) == 1:
                raise ValueError("Non c'è spazio per l'etichetta di una freccia")
            return {"engine": "manim", "report": {"ok": True}}

    async def checkpoint():
        pass

    _, rendered = await design_diagram(
        Client(), Renderer(), "test", {}, SlideContent(title="Processo"), "", "",
        events.append, checkpoint)
    assert rendered["report"]["ok"] and len(calls) == 1 and len(renders) == 2
    assert renders[0]["scene"]["elements"] == renders[1]["scene"]["elements"]
    assert any("verifica non superata" in event for event in events)


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


def test_dense_atomic_scene_is_relaid_out_and_unknown_model_fields_are_dropped():
    value = {"title":"Flusso","comment":"non appartiene alla DSL","elements":[
        {"id":f"n{i}","type":"decision" if i == 2 else "box","x":6,"y":4,
         "width":5,"height":2,"text":f"Passaggio molto lungo numero {i}",
         "python":"never executed"} for i in range(6)],
        "connections":[{"source":f"n{i}","target":f"n{i+1}","label":"continua",
                        "curve":"unsupported"} for i in range(5)]}
    repaired, changed = normalize_scene_geometry(value)
    scene = ManimSceneSpec.model_validate(repaired)
    assert changed is True
    assert len(scene.elements) == 6 and len(scene.connections) == 5
    assert all(element.width <= 2.8 for element in scene.elements)
    assert all("python" not in element for element in repaired["elements"])
    assert "comment" not in repaired


def test_overlapping_chart_and_annotation_get_separate_general_regions():
    value = {"title":"Crescita","elements":[
        {"id":"chart","type":"plot","x":6,"y":4.1,"width":10,"height":5.5,
         "text":"Andamento","values":[1,2,4,8,16]},
        {"id":"note","type":"text","x":9.5,"y":4.1,"width":3.5,"height":1.5,
         "text":"La dimensione dell'input cresce"}],
        "connections":[]}
    repaired, changed = normalize_scene_geometry(value)
    scene = ManimSceneSpec.model_validate(repaired)
    chart, note = scene.elements
    assert changed is True
    assert chart.type == "plot" and note.type == "text"
    assert chart.x+chart.width/2 < note.x-note.width/2


def test_common_remote_scene_type_and_length_errors_are_repaired():
    value = sample_scene()
    value["title"], value["takeaway"] = "Titolo " * 30, "Conclusione " * 30
    value["elements"][0].update(x="1,7", y="2.3", width="2.6", height="1.3",
                                text="Una etichetta inutilmente prolissa " * 5)
    value["elements"][3]["values"] = [str(number) for number in value["elements"][3]["values"]]
    repaired, changed = normalize_scene_geometry(value)
    scene = ManimSceneSpec.model_validate(repaired)
    assert changed is True
    assert len(scene.title) <= 75 and len(scene.takeaway) <= 130
    assert len(scene.elements[0].text) <= 48
    assert isinstance(scene.elements[0].x, float)
    assert all(isinstance(number, float) for number in scene.elements[3].values)


@pytest.mark.parametrize(("kind","labels","values","height"), [
    ("venn", ["Clienti", "Abbonati", "Attivi"], [], 4.0),
    ("gantt", ["Analisi", "Sviluppo", "Test"], [0, 3, 2, 7, 6, 9], 4.5),
    ("timeline", ["Idea", "Prototipo", "Rilascio"], [2024, 2025, 2026], 3.5),
    ("tree", ["Sistema", "Client", "Server", "Web", "API"], [0, 0, 1, 2], 4.5),
    ("network", ["A", "B", "C", "D"], [0, 1, 1, 2, 2, 3, 3, 0], 4.0),
])
def test_semantic_compound_diagrams_build_native_manim(kind, labels, values, height, tmp_path):
    value = {"title":"Diagramma semantico","takeaway":"La forma comunica il significato.",
             "elements":[{"id":"main","type":kind,"x":6,"y":4.1,"width":10,"height":height,
                          "text":kind.upper(),"labels":labels,"values":values,"tone":"blue","stage":1}],
             "connections":[]}
    with tempconfig({"media_dir":str(tmp_path / kind)}):
        root, _header, _footer, stages, report = build_scene(value, {"theme":"ink","font":"Arial"})
    assert kind in report["types"]
    assert report["min_font_size"] >= 20
    assert root.width <= 12 and root.height <= 8
    assert len(stages) == 1


def test_legacy_flow_fallback_uses_flowchart_shapes():
    content = SlideContent(title="Ricerca", diagram={
        "kind":"flow","labels":["Inizio","Confronto","Trovato?","Fine"]})
    scene = fallback_diagram(content, content.diagram.model_dump())["scene"]
    assert [element["type"] for element in scene["elements"]] == [
        "circle", "box", "decision", "circle"]
    assert requested_family("Prepara un diagramma di Gantt") == "gantt"
    assert requested_family("Mostra un diagramma di Venn") == "venn"
    assert requested_family("Fai il grafico della funzione y = 1/x") == "function_plot"
    with pytest.raises(ValueError, match="vero diagramma gantt"):
        fallback_diagram(content, content.diagram.model_dump(), "gantt")


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
    scaffold = SlideContent(title="Formule", layout="cards").model_dump()
    assert normalize_slide_candidate({"risposta": {"title":"Risposta corretta"}}, scaffold)["title"] == "Risposta corretta"
    assert normalize_slide_candidate([{"title":"Prima"}, {"title":"Seconda"}], scaffold)["title"] == "Prima"
    formulas = normalize_slide_candidate([r"\(f'(x)=2x\)", r"\[\int x\,dx=x^2/2+C\]"], scaffold)
    assert formulas["title"] == "Formule" and len(formulas["blocks"]) == 1
    assert r"\int" in formulas["blocks"][0]["text"]


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
         "content":SlideContent(title=title, layout="cover" if index == 1 else "content").model_dump()}
        for index, title in enumerate(("Introduzione", "Copertina", "Bubble sort"))
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
    assert "diagram_render" not in result["slides"][1]
    assert all(result["slides"][index]["diagram_render"]["engine"] == "manim" for index in (0, 2))
    assert len(calls) == 2
    replacement = worker.submit(project["id"], Generation(provider={"mode":"local","model":"fake"},
                                prompt="Riprogetta con forme semantiche", count=3,
                                diagram_only=True, replace_diagrams=True))
    await worker.tasks[replacement["id"]]
    assert store.job(replacement["id"])["status"] == "completed"
    assert len(calls) == 4
    store.db.close()


@pytest.mark.asyncio
async def test_batch_is_failed_when_no_diagram_can_be_inserted(tmp_path):
    store = Store(tmp_path / "batch-failed")
    project = store.create(ProjectInput(prompt="Algoritmi", count=1,
                                        use_manim_diagrams=True).model_dump())
    project["slides"] = [{"id":"slide-1","revision":1,"status":"ready","purpose":"Ricerca",
                          "content":SlideContent(title="Ricerca", layout="content").model_dump()}]
    store.save_project(project)
    class BrokenSceneLLM:
        def __init__(self, *_): pass
        async def prepare(self): pass
        async def json(self, *_args, **_kwargs):
            broken = sample_scene()
            broken["elements"][1]["id"] = broken["elements"][0]["id"]
            return broken
    class BrokenRenderer:
        async def render(self, *_args, **_kwargs):
            raise ValueError("render indisponibile")
    worker = Worker(store, SimpleNamespace())
    worker.clients, worker.renderer = BrokenSceneLLM, BrokenRenderer()
    job = worker.submit(project["id"], Generation(provider={"mode":"local","model":"fake"},
                        prompt="Inserisci diagrammi", count=1, diagram_only=True))
    await worker.tasks[job["id"]]
    assert store.job(job["id"])["status"] == "failed"
    assert "Nessun diagramma" in store.job(job["id"])["error"]
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
    assert result["slides"][0]["content"]["diagram"]["kind"] == "manim"
    assert result["slides"][0]["diagram_render"]["engine"] == "manim"
    assert any("verifico un fallback esplicito" in event["message"]
               for event in store.job(job["id"])["events"])
    assert any("Fallback Manim verificato" in event["message"]
               for event in store.job(job["id"])["events"])
    scene = result["slides"][0]["content"]["diagram"]["scene"]
    assert scene["title"].startswith("Riepilogo") and not scene["connections"]
    store.db.close()


@pytest.mark.asyncio
async def test_fallback_is_a_renderable_real_manim_scene(tmp_path):
    store = Store(tmp_path / "fallback-render")
    project = store.create(ProjectInput(prompt="Algoritmi", use_manim_diagrams=True).model_dump())
    content = SlideContent(title="Ricerca binaria", blocks=[
        {"heading":"Intervallo","text":"Si considera l'intervallo ancora possibile."},
        {"heading":"Confronto","text":"Si confronta il valore con l'elemento centrale."},
        {"heading":"Dimezzamento","text":"Si elimina metà dello spazio di ricerca."},
    ], diagram={"kind":"flow","labels":["Intervallo iniziale","Elemento centrale","Metà rimanente"]})
    diagram = fallback_diagram(content, content.diagram.model_dump())
    rendered = await ManimRenderer(store).render(project["id"], diagram, project)
    assert rendered["report"]["ok"] is True
    assert rendered["report"]["elements"] == 3
    store.db.close()
