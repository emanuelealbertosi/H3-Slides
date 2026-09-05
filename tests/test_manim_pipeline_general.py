import copy
import json

import pytest

from h3_slides.diagrams import design_diagram, normalize_scene_geometry, scene_validation_feedback
from h3_slides.diagram_spec import ManimSceneSpec
from h3_slides.models import SlideContent


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
@pytest.mark.parametrize(("brief", "element", "kind"), [
    ("Istogramma dei campioni", {"id": "chart", "type": "histogram",
                                "samples": [0, 1, 1, 2, 3], "bin_edges": [0, 1, 2, 3]}, "histogram"),
    ("Grafo orientato", {"id": "chart", "type": "directed_graph",
                         "nodes": ["A", "B", "C"], "edges": [["A", "B"], ["C", "A"]]}, "network"),
    ("Grafico della funzione y=1/x", {"id": "chart", "type": "function",
                                     "formula": "1/x", "domain": [-3, 3], "range": [-5, 5]}, "function_plot"),
    ("Grafico a dispersione", {"id": "chart", "type": "scatter_plot",
                               "points": [{"x": 1, "y": 4}, {"x": 10, "y": 3}]}, "scatter"),
    ("Grafico a linee", {"id": "chart", "type": "line_chart",
                         "points": [[1, 4], [10, 3]]}, "plot"),
])
async def test_local_and_remote_scene_pipeline_repairs_only_format_and_geometry(mode, brief, element, kind):
    calls = []
    original = copy.deepcopy(element)
    class Client:
        provider_mode = mode
        async def json(self, prompt, schema):
            calls.append((prompt, schema))
            return {"title": brief, "elements": [copy.deepcopy(element)]}
    class Renderer:
        async def render(self, _pid, diagram, _project):
            parsed = ManimSceneSpec.model_validate(diagram["scene"])
            assert parsed.elements[0].type == kind
            return {"engine": "manim", "asset": "fixture.png", "report": {"ok": True}}
    async def checkpoint(): pass
    diagram, _ = await design_diagram(Client(), Renderer(), "p", {},
        SlideContent(title=brief, diagram={"kind": "manim", "brief": brief}),
        "Campioni e relazioni forniti dall'utente.", brief, lambda _: None, checkpoint)
    assert len(calls) == 1 and element == original
    assert diagram["scene"]["elements"][0]["width"] >= 5
    assert len(json.dumps(calls[0][1])) < 6000


@pytest.mark.asyncio
async def test_misplaced_arrow_is_recovered_without_another_llm_call():
    events, calls = [], []
    class Client:
        async def json(self, prompt, schema):
            calls.append(prompt)
            return {"title": "Procedura", "elements": [
                {"id": "a", "type": "circle", "text": "Inizio"},
                {"id": "b", "type": "document", "text": "Documento"},
                {"type": "arrow", "source": "a", "target": "b", "label": "produce"}]}
    class Renderer:
        async def render(self, _pid, diagram, _project):
            assert len(ManimSceneSpec.model_validate(diagram["scene"]).connections) == 1
            return {"engine": "manim", "asset": "fixture.png"}
    async def checkpoint(): pass
    await design_diagram(Client(), Renderer(), "p", {}, SlideContent(title="Procedura"), "",
                         "Diagramma di flusso", events.append, checkpoint)
    assert len(calls) == 1
    assert any("collegamenti normalizzati" in message for message in events)


@pytest.mark.asyncio
async def test_global_deck_mentions_do_not_force_every_chart_on_each_slide():
    class Client:
        async def json(self, prompt, schema):
            branches = schema["properties"]["elements"]["items"]["anyOf"]
            assert any(item["properties"]["type"].get("const") == "network" for item in branches)
            assert not any(item["properties"]["type"].get("const") == "histogram" for item in branches)
            return {"title": "Grafo", "elements": [{"id": "g", "type": "network",
                                                    "labels": ["A", "B"], "values": [0, 1]}]}
    class Renderer:
        async def render(self, *_): return {"engine": "manim", "asset": "fixture.png"}
    async def checkpoint(): pass
    await design_diagram(Client(), Renderer(), "p", {}, SlideContent(title="Grafo"),
                         "", "Grafo\nRichiesta generale del progetto: istogrammi e funzioni y=x",
                         lambda _: None, checkpoint)


@pytest.mark.asyncio
async def test_unchanged_invalid_element_does_not_get_retries_by_rewording_valid_neighbours():
    calls = []
    class Client:
        async def json(self, prompt, schema):
            calls.append(prompt)
            return {"title": "Schema", "elements": [
                {"id": "valid", "type": "circle", "text": "Testo " + str(len(calls))},
                {"id": "bad", "type": "unknown_shape", "text": "Altro " + str(len(calls))}]}
    class Renderer:
        async def render(self, *_): pytest.fail("An invalid type cannot be rendered")
    async def checkpoint(): pass
    with pytest.raises(ValueError, match="candidato invalido ripetuto"):
        await design_diagram(Client(), Renderer(), "p", {}, SlideContent(title="Schema"),
                             "", "", lambda _: None, checkpoint)
    assert len(calls) == 2


def test_explicit_line_coordinates_keep_chart_readable_size():
    candidate = {"title": "Tempi", "elements": [{"id": "plot", "type": "plot", "values": [2, 3],
                                                "x_values": [10, 100]}]}
    result, _ = normalize_scene_geometry(candidate)
    element = ManimSceneSpec.model_validate(result).elements[0]
    assert element.x_values == [10, 100] and element.width >= 5 and element.height >= 3.5


@pytest.mark.asyncio
async def test_redesign_can_replace_a_family_named_in_the_old_title():
    calls = []
    class Client:
        async def json(self, prompt, schema):
            calls.append(prompt)
            branches = schema["properties"]["elements"]["items"]["anyOf"]
            kinds = [item["properties"]["type"].get("const") for item in branches]
            assert "histogram" in kinds and "bars" not in kinds
            return {"title": "Distribuzione", "elements": [{"id": "h", "type": "histogram",
                    "samples": [0, 1, 1, 2, 3], "bin_edges": [0, 1, 2, 3]}]}
    class Renderer:
        async def render(self, *_): return {"engine": "manim", "asset": "fixture.png"}
    async def checkpoint(): pass
    diagram, _ = await design_diagram(Client(), Renderer(), "p", {},
        SlideContent(title="Grafico a barre", diagram={"kind": "manim", "brief": "Grafico a barre"}),
        "", "Non usare grafico a barre, mostra un istogramma", lambda _: None, checkpoint)
    assert len(calls) == 1 and diagram["scene"]["elements"][0]["type"] == "histogram"


@pytest.mark.parametrize("message", [
    "Istogramma: bin_edges richiede estremi strettamente crescenti",
    "Istogramma: ampiezze non rappresentabili",
    "Asse numerico: intervallo non rappresentabile, cambia unità",
    "Tacche numeriche: passo non rappresentabile",
])
def test_numerical_range_errors_are_data_feedback_not_geometry(message):
    assert scene_validation_feedback(ValueError(message), phase="render")["category"] == "DATI"
