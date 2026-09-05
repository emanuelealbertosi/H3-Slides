"""Generation regressions: shape data, truthful fallback and bounded retries."""
import copy
import json

import pytest

from h3_slides.diagram_spec import ManimSceneSpec, SCENE_PROMPT, designed_scene_schema
from h3_slides.diagrams import (ManimRenderer, design_diagram, fallback_diagram,
                                normalize_scene_geometry, requested_family,
                                scene_validation_feedback, validate_designed_scene)
from h3_slides.models import ProjectInput, SlideContent
from h3_slides.storage import Store


def scene(kind="network", **fields):
    return {"title": "Schema", "elements": [{"id": "main", "type": kind,
            "x": 6, "y": 4.15, "width": 10, "height": 5,
            **({"labels": ["A", "B", "C"], "values": [0, 1, 1, 2]} if kind == "network" else {}),
            **fields}], "connections": []}


def test_generation_schema_requires_each_shapes_data_and_leaves_saved_scene_contract_intact():
    schema = designed_scene_schema()
    variants = schema["properties"]["elements"]["items"]["anyOf"]
    by_kind = {variant["properties"]["type"]["const"]: variant for variant in variants
               if "const" in variant["properties"]["type"]}
    network = by_kind["network"]
    assert {"labels", "values"} <= set(network["required"])
    assert network["properties"]["values"]["items"]["type"] == "integer"
    for kind, minimum in (("grid", 1), ("bars", 1), ("plot", 2)):
        assert "values" in by_kind[kind]["required"]
        assert by_kind[kind]["properties"]["values"]["minItems"] == minimum
    assert "columns" in by_kind["grid"]["required"]
    assert "values" not in variants[0]["properties"]
    assert "values" not in by_kind["function_plot"]["properties"]
    assert all(variant["additionalProperties"] is False for variant in variants)
    assert "Element" in ManimSceneSpec.model_json_schema()["$defs"]
    # Old scenes may carry harmless default fields even on qualitative shapes.
    assert ManimSceneSpec.model_validate(scene("box", text="Forma", values=[])).elements[0].type == "box"


def test_compact_generation_schema_preserves_expanded_contract_and_stays_within_budget(monkeypatch):
    import h3_slides.diagram_spec as module

    before = []
    compact = module._compact_generation_schema

    def capture(schema):
        before.append(copy.deepcopy(schema))
        return compact(schema)

    monkeypatch.setattr(module, "_compact_generation_schema", capture)
    actual = module.designed_scene_schema()

    def expand(value, definitions, names=False):
        if isinstance(value, list):
            return [expand(item, definitions) for item in value]
        if not isinstance(value, dict):
            return value
        if names:
            return {key: expand(item, definitions) for key, item in value.items()}
        if "$ref" in value:
            assert len(value) == 1 and value["$ref"].startswith("#/$defs/")
            return expand(definitions[value["$ref"][len("#/$defs/"):]], definitions)
        return {key: expand(item, definitions, key == "properties") for key, item in value.items()
                if key not in ("$defs", "title", "default")}

    assert expand(actual, actual["$defs"]) == expand(before[0], before[0]["$defs"])
    assert len(json.dumps(actual, ensure_ascii=False)) < 9200
    assert "title" in actual["properties"] and "title" in actual["required"]
    assert {"id", "x", "y", "width", "height", "text", "caption", "tone", "stage"} <= actual["$defs"].keys()


def test_prompt_examples_are_valid_native_scenes():
    examples = [json.loads(line) for line in SCENE_PROMPT.splitlines() if line.startswith('{"id":')]
    assert {example["type"] for example in examples} == {"network", "grid"}
    for example in examples:
        assert ManimSceneSpec.model_validate({"title": "Sintassi", "elements": [example]})


@pytest.mark.parametrize(("kind", "labels", "pairs", "flat"), [
    ("network", ["A", "B", "C"], [["0", "1"], ["1", "2"]], [0, 1, 1, 2]),
    ("gantt", ["A", "B"], [["0", "2"], ["2", "4"]], [0, 2, 2, 4]),
])
def test_normalization_only_flattens_unambiguous_pairs(kind, labels, pairs, flat):
    candidate = scene(kind, labels=labels, values=pairs)
    original = copy.deepcopy(candidate)
    normalized, changed = normalize_scene_geometry(candidate)
    parsed = ManimSceneSpec.model_validate(normalized)
    assert candidate == original
    assert changed and parsed.elements[0].values == flat
    assert parsed.elements[0].labels == labels


@pytest.mark.parametrize("values", [[[0, 1, 2]], [[0, 1], 2], ["A", "B"],
                                     [0, 3], [1, 1], [0, 1.5], ["2 px", "1"], ["NaN", 1], [True, 0]])
def test_invalid_network_data_is_never_guessed(values):
    candidate = scene(values=values)
    normalized, _ = normalize_scene_geometry(candidate)
    with pytest.raises(ValueError):
        ManimSceneSpec.model_validate(normalized)


@pytest.mark.parametrize("kind", ["grid", "bars", "plot"])
def test_missing_chart_samples_are_not_fabricated(kind):
    normalized, _ = normalize_scene_geometry(scene(kind, values=[], text="Area qualitativa"))
    assert normalized["elements"][0]["values"] == []
    assert normalized["elements"][0]["type"] == kind
    with pytest.raises(ValueError):
        ManimSceneSpec.model_validate(normalized)


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), "NaN", "Infinity", "1e999", True])
def test_nonfinite_geometry_cannot_be_hidden_by_normalization(coordinate):
    normalized, _ = normalize_scene_geometry(scene(x=coordinate))
    with pytest.raises(ValueError):
        ManimSceneSpec.model_validate(normalized)


def test_fallback_preserves_valid_previous_scene_without_reinterpreting_it():
    previous = {"kind": "manim", "brief": "Rete approvata", "labels": [], "scene": scene()}
    content = SlideContent(title="Titolo aggiornato", blocks=[{"heading": "Altro", "text": "Descrizione."}])
    actual = fallback_diagram(content, previous, "network")
    assert actual["scene"] == ManimSceneSpec.model_validate(previous["scene"]).model_dump()
    assert actual["brief"] == previous["brief"]
    actual["scene"]["elements"][0]["labels"].append("Nuovo")
    assert len(previous["scene"]["elements"][0]["labels"]) == 3


def test_fallback_from_headings_is_a_disclosed_summary_without_invented_relations():
    content = SlideContent(title="Componenti", blocks=[
        {"heading": "Superficie", "text": "Una superficie visibile."},
        {"heading": "Area", "text": "La regione descritta."}], diagram={"kind": "manim"})
    summary = fallback_diagram(content, {"kind": "flow", "labels": []})["scene"]
    assert summary["title"].startswith("Riepilogo")
    assert not summary["connections"]
    assert {element["text"] for element in summary["elements"]} == {"Superficie", "Area"}
    assert all(element["type"] == "box" and not element["values"] for element in summary["elements"])
    with pytest.raises(ValueError, match="vero diagramma flowchart"):
        fallback_diagram(content, required_family="flowchart")


def test_comparison_fallback_cannot_turn_into_a_flow():
    content = SlideContent(title="Confronto tra metodi", blocks=[
        {"heading": "Metodo A", "text": "Ricerca ordinata."},
        {"heading": "Metodo B", "text": "Ricerca per gruppi."}])
    assert requested_family(content.title) == "comparison"
    actual = ManimSceneSpec.model_validate(fallback_diagram(content, required_family="comparison")["scene"])
    validate_designed_scene(actual, "comparison")
    assert actual.title.startswith("Confronto qualitativo")
    assert not actual.connections and actual.elements[0].y == actual.elements[1].y
    with pytest.raises(ValueError, match="almeno due voci"):
        fallback_diagram(SlideContent(title="Un solo concetto"), required_family="comparison")


@pytest.mark.asyncio
async def test_data_retry_explains_missing_values_and_uses_qualitative_shapes():
    calls, events = [], []
    candidates = [scene("grid", text="Piano"), scene("box", text="Piano", caption="Schema qualitativo")]

    class Client:
        async def json(self, prompt, schema):
            calls.append(prompt)
            assert "anyOf" in schema["properties"]["elements"]["items"]
            return candidates[len(calls)-1]

    class Renderer:
        async def render(self, *_):
            return {"report": {"ok": True}}

    async def checkpoint():
        pass

    diagram, _ = await design_diagram(Client(), Renderer(), "test", {},
                                     SlideContent(title="Superfici"), "", "", events.append, checkpoint)
    assert diagram["scene"]["elements"][0]["type"] == "box"
    assert "CORREGGI DATI" in calls[1] and "Non inventare valori o archi" in calls[1]
    assert "CORREGGI GEOMETRIA/TESTI" not in calls[1]


@pytest.mark.asyncio
async def test_repeated_invalid_data_stops_even_when_model_moves_the_chart_and_diagnostics_are_safe():
    calls, events = [], []
    secret = "PRIVATE_DOCUMENT_BODY_TOKEN"

    class Client:
        async def json(self, prompt, schema):
            calls.append(prompt)
            return scene(values=[secret, 1], y=4.1 + len(calls)*.01)

    class Renderer:
        async def render(self, *_):
            pytest.fail("Invalid numeric data must never reach Manim")

    async def checkpoint():
        pass

    with pytest.raises(ValueError, match="candidato invalido ripetuto") as failure:
        await design_diagram(Client(), Renderer(), "test", {}, SlideContent(title="Nodi"),
                             secret, "", events.append, checkpoint)
    assert len(calls) == 2
    assert secret not in " ".join(events) + str(failure.value)
    assert any("DATI" in event and "elements.0.values.0" in event for event in events)


def test_feedback_distinguishes_structure_data_and_geometry_without_echoing_unknown_fields():
    for candidate, expected in ((scene(values=["bad", 1]), "DATI"),
                                (scene(x=.2), "GEOMETRIA"),
                                ({**scene(), "SECRET_EXTRA_KEY": "PRIVATE_BODY"}, "STRUTTURA")):
        with pytest.raises(ValueError) as failure:
            ManimSceneSpec.model_validate(candidate)
        feedback = scene_validation_feedback(failure.value)
        assert feedback["category"] == expected
        safe = json.dumps(feedback["issues"])
        assert "SECRET_EXTRA_KEY" not in safe and "PRIVATE_BODY" not in safe


@pytest.mark.parametrize(("candidate", "rule"), [
    (scene("grid"), "values_required"),
    (scene(values=[0, 3]), "network_indices_distinct_and_in_range"),
    (scene(values=[0]), "network_pairs_required"),
    (scene("grid", values=[0, 1, .5], columns=2), "grid_dimensions_and_range"),
])
def test_domain_diagnostics_identify_the_failed_data_rule_without_raw_candidate(candidate, rule):
    with pytest.raises(ValueError) as failure:
        ManimSceneSpec.model_validate(candidate)
    feedback = scene_validation_feedback(failure.value)
    assert feedback["issues"][0]["code"] == rule


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["structure", "render", "json"])
async def test_retry_uses_the_responsible_stage(failure_phase):
    calls, renders = [], []

    class Client:
        async def json(self, prompt, schema):
            calls.append(prompt)
            candidate = scene()
            if len(calls) == 1 and failure_phase == "structure":
                del candidate["elements"][0]["id"]
            if len(calls) == 1 and failure_phase == "json":
                raise ValueError("Il modello non ha restituito JSON valido")
            return candidate

    class Renderer:
        async def render(self, *_):
            renders.append(True)
            if len(renders) == 1 and failure_phase == "render":
                raise ValueError("Contenuto fuori dall'ingombro: aumenta width/height")
            return {"report": {"ok": True}}

    async def checkpoint():
        pass

    _, result = await design_diagram(Client(), Renderer(), "test", {}, SlideContent(title="Nodi"),
                                     "", "", lambda _: None, checkpoint)
    expected = "GEOMETRIA" if failure_phase == "render" else "STRUTTURA"
    assert len(calls) == 2 and "CORREGGI " + expected in calls[1]
    assert result["report"]["ok"]


@pytest.mark.asyncio
async def test_normalized_network_and_declared_qualitative_summary_render_with_real_manim(tmp_path):
    store = Store(tmp_path / "native-manim")
    try:
        project = store.create(ProjectInput(prompt="Verifica scene", use_manim_diagrams=True).model_dump())
        normalized, _ = normalize_scene_geometry(scene(values=[["0", "1"], ["1", "2"]]))
        summary = fallback_diagram(SlideContent(title="Componenti", blocks=[
            {"heading": "Area A", "text": "Primo elemento."},
            {"heading": "Area B", "text": "Secondo elemento."}]))
        renderer = ManimRenderer(store)
        for diagram in ({"kind": "manim", "labels": [], "scene": normalized}, summary):
            rendered = await renderer.render(project["id"], diagram, project)
            assert rendered["report"]["ok"] and rendered["report"]["bounds_checked"]
            assert rendered["report"]["min_font_size"] >= 20
            assert store.asset_path(project["id"], rendered["asset"]).is_file()
    finally:
        store.db.close()
