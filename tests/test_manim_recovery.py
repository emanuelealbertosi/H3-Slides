"""Regression for real maps, branched flows and truthful geometric recovery."""
import copy
import json
import re
from types import SimpleNamespace

import pytest
from manim import Text, tempconfig
from h3_slides.diagram_errors import DiagramLayoutError
from h3_slides.diagram_intent import requested_scene_families, validate_designed_scene
from h3_slides.diagram_reflow import graph_layout_candidates
from h3_slides.diagram_spec import ManimSceneSpec, designed_scene_schema
from h3_slides.diagrams import ManimRenderer, design_diagram, fallback_diagram, scene_validation_feedback, normalize_scene_geometry
from h3_slides.manim_scene import build_scene
from h3_slides.models import Generation, ProjectInput, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker


def concept_map():
    labels = ["Informatica", "Hardware", "Software", "Dati", "Informazioni", "Ciclo di elaborazione",
              "Input", "Elaborazione", "Output", "Memorizzazione", "Distribuzione"]
    elements = [{"id": f"n{i}", "type": "box", "x": 1.65+(i % 4)*2.9,
                 "y": 1.9+(i//4)*2.2, "width": 2.4, "height": 1.1, "text": label,
                 "tone": "accent" if i == 0 else "blue" if i < 6 else "amber"}
                for i, label in enumerate(labels)]
    edges = [(0, i) for i in range(1, 6)] + [(5, 6)] + [(i, i+1) for i in range(6, 10)]
    return {"title": "Mappa concettuale: informatica e ciclo", "elements": elements,
            "connections": [{"source": f"n{a}", "target": f"n{b}"} for a, b in edges]}


def branched_flow():
    return {"title": "Dai dati alle informazioni", "elements": [
        {"id": "input", "type": "document", "text": "Dati", "x": 2, "y": 2.5, "width": 2.7, "height": 1.4},
        {"id": "process", "type": "box", "text": "Elaborazione automatica", "x": 6, "y": 2.5, "width": 3, "height": 1.4},
        {"id": "output", "type": "document", "text": "Informazioni", "x": 10, "y": 2.5, "width": 2.7, "height": 1.4},
        {"id": "it", "type": "box", "text": "IT", "caption": "Hardware e software", "x": 3, "y": 5.6, "width": 4, "height": 1.5},
        {"id": "ict", "type": "box", "text": "ICT", "caption": "Reti, Internet, telefonia e trasmissione dati", "x": 9, "y": 5.6, "width": 4, "height": 1.5}],
        "connections": [{"source": a, "target": b, "label": label} for a, b, label in (
            ("input", "process", "ingresso"), ("process", "output", "produce"),
            ("process", "it", "strumenti"), ("process", "ict", "comunicazione"))]}


@pytest.mark.parametrize("text,family", [
    ("Mappa concettuale con nodo centrale e rami", "concept_map"),
    ("Mappa mentale", "concept_map"), ("A concept map", "concept_map"),
    ("Flusso orizzontale: dati -> elaborazione -> informazioni", "flowchart"),
    ("Un flusso verticale", "flowchart")])
def test_local_map_and_flow_intent(text, family):
    assert requested_scene_families("", text, text) == [family]
    assert requested_scene_families("", "", "Non usare " + text.lower()) == []


def test_concept_map_contract_accepts_rectangular_concepts_but_rejects_headings():
    scene = ManimSceneSpec.model_validate(concept_map())
    validate_designed_scene(scene, "concept_map")
    scene.connections = []
    with pytest.raises(ValueError, match="concetti collegati"):
        validate_designed_scene(scene, "concept_map")
    schema = designed_scene_schema(["concept_map"])
    types = [v["properties"]["type"] for v in schema["properties"]["elements"]["items"]["anyOf"]]
    assert {v.get("const") for v in types if "const" in v} == {"network", "tree"}
    assert "concept_map" not in json.dumps(schema)


@pytest.mark.parametrize("scene,family", [(concept_map(), "concept_map"), (branched_flow(), "flowchart")])
def test_real_manim_map_and_branched_flow_keep_every_node_and_relationship(scene, family, tmp_path):
    validate_designed_scene(ManimSceneSpec.model_validate(scene), family)
    original = copy.deepcopy(scene)
    with tempconfig({"media_dir": str(tmp_path)}):
        root, _, _, _, report = build_scene(scene, {"theme": "paper", "font": "Arial"})
    text = {re.sub(r"\s+", "", obj.text) for obj in root.get_family() if isinstance(obj, Text)}
    for node in scene["elements"]:
        for field in ("text", "caption"):
            if node.get(field):
                assert re.sub(r"\s+", "", node[field]) in text
    for edge in scene["connections"]:
        if edge.get("label"):
            assert re.sub(r"\s+", "", edge["label"]) in text
    assert report["connections"] == len(scene["connections"])
    assert report["elements"] == len(scene["elements"]) and not report["shortened_texts"]
    assert root.width <= 12 and root.height <= 8
    assert scene == original
    if family == "flowchart":
        assert report["geometry_recovered"]


def test_graph_reflow_preserves_all_semantic_fields_and_input():
    scene = ManimSceneSpec.model_validate(branched_flow())
    before = scene.model_dump()
    alternatives = list(graph_layout_candidates(scene))
    assert len(alternatives) == 3
    for candidate in alternatives:
        assert candidate.connections == scene.connections
        assert candidate.title == scene.title
        for old, new in zip(scene.elements, candidate.elements):
            assert old.model_dump(exclude={"x", "y", "width", "height"}) == new.model_dump(exclude={"x", "y", "width", "height"})
    assert scene.model_dump() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_map_is_not_allowed_to_degrade_on_retry(mode):
    calls = []
    class Client:
        provider_mode = mode
        async def json(self, prompt, schema):
            calls.append(prompt)
            candidate = concept_map()
            if len(calls) == 1:
                candidate["connections"] = []
            return candidate
    class Renderer:
        async def render(self, _pid, diagram, _project):
            assert len(diagram["scene"]["connections"]) == 10
            return {"report": {"ok": True}}
    async def checkpoint(): pass
    await design_diagram(Client(), Renderer(), "fixture", {},
                         SlideContent(title="Mappa concettuale"), "", "", lambda _: None, checkpoint)
    assert len(calls) == 2 and "concetti collegati" in calls[1]


def test_layout_feedback_is_actionable_without_echoing_label_text():
    feedback = scene_validation_feedback(DiagramLayoutError("Testo completo non leggibile PRIVATE_BODY",
                                                           ("connections", 3, "label")), "render")
    assert feedback["category"] == "GEOMETRIA"
    assert feedback["issues"][0]["path"] == "connections.3.label"
    assert "spazio assegnato" in feedback["issues"][0]["explanation"]
    assert "PRIVATE_BODY" not in json.dumps(feedback["issues"])


@pytest.mark.asyncio
async def test_real_failed_render_retains_private_report_and_scene(tmp_path):
    store = Store(tmp_path / "private-diagnostics")
    try:
        project = store.create(ProjectInput(prompt="Fixture").model_dump())
        scene = branched_flow()
        scene["title"] = "W" * 160  # Unbreakable, valid schema, physically impossible.
        with pytest.raises(ValueError):
            await ManimRenderer(store).render(project["id"], {"kind": "manim", "scene": scene}, project)
        work = store.root / "manim-work"
        log = (work / "last-error.log").read_text(encoding="utf-8")
        assert '"text_space"' in log and '"title"' in log
        assert json.loads((work / "last-error-scene.json").read_text(encoding="utf-8"))["scene"]["title"] == scene["title"]
        assert not list(work.glob("render-*"))
    finally:
        store.db.close()


def test_dense_map_with_more_than_eight_nodes_is_recovered_without_losing_relations():
    value = concept_map()
    for element in value["elements"]:
        element.update(x=6, y=4, width=4, height=2)
    candidate, changed = normalize_scene_geometry(value)
    scene = ManimSceneSpec.model_validate(candidate)
    assert changed and len(scene.elements) == 11
    assert candidate["connections"] == value["connections"]
    assert [e.text for e in scene.elements] == [e["text"] for e in value["elements"]]


def test_old_automatic_summary_cannot_be_reused_as_successful_fallback():
    scene = {"title": "Riepilogo · Informatica", "takeaway": "Schema qualitativo dei concetti presenti nella slide.",
             "elements": [{"id": "summary0", "type": "box", "x": 6, "y": 4,
                           "width": 4, "height": 2, "text": "Informatica"}]}
    with pytest.raises(ValueError, match="nessuna scena valida"):
        fallback_diagram(SlideContent(title="Informatica"), {"kind": "manim", "scene": scene})


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [True, False])
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_failed_redesign_preserves_previous_slide_without_counting_cached_success(tmp_path, single, mode):
    store = Store(tmp_path / "redesign")
    try:
        project = store.create(ProjectInput(prompt="Diagramma", use_manim_diagrams=True, count=1).model_dump())
        content = SlideContent(title="Flusso orizzontale", diagram={"kind": "manim", "brief": "Flusso orizzontale",
                                                                 "scene": branched_flow()}).model_dump()
        project["slides"] = [{"id": "s1", "revision": 4, "status": "ready", "content": content,
                              "diagram_render": {"engine": "manim", "asset": "existing.png"}}]
        before = copy.deepcopy(project["slides"])
        store.save_project(project)
        class Client:
            def __init__(self, *_): pass
            async def prepare(self): pass
            async def json(self, *_args, **_kwargs):
                candidate = branched_flow()
                candidate["elements"][1]["id"] = "input"  # Invalid model output.
                return candidate
        class Renderer:
            async def render(self, *_):
                pytest.fail("No valid new scene: do not render the previous scene as a successful replacement")
        worker = Worker(store, SimpleNamespace())
        worker.clients, worker.renderer = Client, Renderer()
        provider = {"mode": mode, "model": "fixture"}
        if mode == "remote":
            provider.update(base_url="http://127.0.0.1:1234", remote_consent=True)
        job = worker.submit(project["id"], Generation(provider=provider, prompt="Flusso orizzontale",
                            count=1, diagram_only=True, replace_diagrams=True, slide_id="s1" if single else None))
        await worker.tasks[job["id"]]
        result = store.job(job["id"])
        assert result["status"] == "failed"
        assert any("versione precedente conservata" in event["message"] for event in result["events"])
        assert store.project(project["id"])["slides"] == before
    finally:
        store.db.close()
