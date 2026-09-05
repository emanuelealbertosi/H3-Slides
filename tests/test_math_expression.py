import math
import pytest

from h3_slides.math_expression import compile_expression, sample_expression, function_line
from h3_slides.diagram_spec import ManimSceneSpec
from h3_slides.manim_scene import build_scene
from h3_slides.diagrams import normalize_scene_geometry, ManimRenderer, design_diagram
from h3_slides.models import ProjectInput, SlideContent
from h3_slides.storage import Store


def test_safe_expressions_are_evaluated_without_eval():
    assert compile_expression("y = 1/x")(2) == .5
    assert compile_expression("sin(pi/2)")(0) == pytest.approx(1)
    assert compile_expression("sqrt(x^2) + abs(x)")(-3) == pytest.approx(6)
    assert math.isnan(compile_expression("x^0.5")(-1))


@pytest.mark.parametrize("source", [
    "__import__('os').system('dir')", "x.__class__", "[x for x in range(3)]",
    "open('secret')", "2**100",
])
def test_executable_or_unbounded_expressions_are_rejected(source):
    with pytest.raises(ValueError):
        compile_expression(source)


def test_reciprocal_is_sampled_as_two_branches_around_asymptote():
    segments = sample_expression("1/x", -5, 5, -5, 5, [0])
    assert len(segments) == 2
    assert max(x for x, _ in segments[0]) < 0
    assert min(x for x, _ in segments[1]) > 0
    assert all(math.isfinite(y) for segment in segments for _, y in segment)


def test_function_plot_schema_carries_real_domain_and_asymptotes():
    scene = ManimSceneSpec.model_validate({
        "title": "Funzione inversa",
        "elements": [{
            "id": "funzione", "type": "function_plot", "x": 6, "y": 4.1,
            "width": 10, "height": 5.5, "text": "y = 1/x",
            "expression": "1/x", "x_min": -5, "x_max": 5,
            "y_min": -5, "y_max": 5, "asymptotes": [0],
        }],
    })
    assert scene.elements[0].expression == "1/x"
    assert scene.elements[0].asymptotes == [0]


def test_function_plot_builds_native_manim_scene():
    value = {
        "title": "Funzione inversa",
        "elements": [{
            "id": "funzione", "type": "function_plot", "x": 6, "y": 4.1,
            "width": 10, "height": 5.5, "text": "y = 1/x",
            "expression": "1/x", "x_min": -5, "x_max": 5,
            "y_min": -5, "y_max": 5, "asymptotes": [0],
        }],
    }
    root, _header, _footer, stages, report = build_scene(
        value, {"theme": "paper", "font": "Arial"})
    assert report["types"] == ["function_plot"]
    assert report["bounds_checked"] is True
    assert len(stages) == 1
    assert root.width <= 12 and root.height <= 8


def calculus_scene():
    return {"title": "Secante e tangente", "takeaway": "Esempio illustrativo: f(x) = x²",
            "elements": [{"id": "curve", "type": "function_plot", "x": 6, "y": 4.15,
                          "width": 10, "height": 5.8, "text": "Funzione e rette",
                          "expression": "x^2", "x_min": -1, "x_max": 3,
                          "y_min": -3, "y_max": 9, "tangent_at": 1, "secant_x": [1, 2],
                          "series": [{"expression": "2*x", "label": "Derivata", "tone": "blue"}]}]}


def test_tangent_and_secant_are_computed_from_the_curve():
    assert function_line("x^2", 1) == pytest.approx((2, -1), abs=1e-8)
    assert function_line("x^2", 1, 2) == pytest.approx((3, -2))
    assert function_line("sin(x)", 0) == pytest.approx((1, 0), abs=1e-8)
    for expression, at, other in [("1/x", 0, None), ("abs(x)", 0, None), ("x^2", 1, 1)]:
        with pytest.raises(ValueError):
            function_line(expression, at, other)


@pytest.mark.parametrize("field,value", [
    ("series", [{"expression": "open('file')"}]),
    ("secant_x", [1]), ("secant_x", [1, 1]), ("tangent_at", 8),
])
def test_invalid_calculus_data_is_rejected(field, value):
    scene = calculus_scene()
    scene["elements"][0][field] = value
    with pytest.raises(ValueError):
        ManimSceneSpec.model_validate(scene)


@pytest.mark.parametrize("count,notes", [(2, 0), (2, 1), (2, 4), (3, 0), (4, 0)])
def test_overlapping_function_panels_reflow_and_build_without_losing_data(count, notes):
    expressions = ["exp(x)", "sin(x)", "cos(x)", "x^2"]
    value = {"title": "Confronto di funzioni", "elements": [
        {"id": f"plot{i}", "type": "function_plot", "expression": expressions[i],
         "text": expressions[i], "x": 6, "y": 4.15, "width": 10, "height": 5.5,
         "x_min": -2, "x_max": 2, "y_min": -2, "y_max": 8}
        for i in range(count)] + [
        {"id": f"note{i}", "type": "text", "text": "Confronto", "x": 6, "y": 4.15,
         "width": 3, "height": 1.2} for i in range(notes)]}
    repaired, changed = normalize_scene_geometry(value)
    assert changed and value["elements"][0]["width"] == 10
    scene = ManimSceneSpec.model_validate(repaired)
    assert [e.expression for e in scene.elements[:count]] == [s.replace("^", "**") for s in expressions[:count]]
    assert all(e.x_min == -2 and e.y_max == 8 for e in scene.elements[:count])
    root, _, _, _, report = build_scene(scene.model_dump(), {"theme": "paper"})
    assert report["plotted_curves"] == count and report["bounds_checked"]
    assert root.width <= 12 and root.height <= 8


def test_plot_with_formula_is_not_treated_as_missing_samples():
    value = calculus_scene()
    value["elements"][0]["type"] = "plot"
    repaired, changed = normalize_scene_geometry(value)
    scene = ManimSceneSpec.model_validate(repaired)
    assert changed and scene.elements[0].type == "function_plot"
    assert scene.elements[0].tangent_at == 1 and scene.elements[0].secant_x == [1, 2]


@pytest.mark.asyncio
async def test_calculus_llm_contract_and_real_manim_render(tmp_path):
    store = Store(tmp_path / "data")
    project = store.create(ProjectInput(prompt="Spiega la derivata", use_manim_diagrams=True).model_dump())
    content = SlideContent(title="Derivata", diagram={"kind": "manim", "brief": "Secante e tangente"})
    events = []

    class Client:
        async def json(self, prompt, schema=None):
            assert "tangent_at" in prompt and "secant_x" in prompt
            function_schema = next(variant for variant in schema["properties"]["elements"]["items"]["anyOf"]
                                   if variant["properties"]["type"].get("const") == "function_plot")
            assert "series" in function_schema["properties"]
            return calculus_scene()

    async def checkpoint():
        pass

    try:
        diagram, rendered = await design_diagram(
            Client(), ManimRenderer(store), project["id"], project, content, "",
            "Confronta funzione, derivata, secante e tangente", events.append, checkpoint)
        assert diagram["scene"]["elements"][0]["secant_x"] == [1, 2]
        assert rendered["report"]["ok"]
        assert rendered["report"]["plotted_curves"] == 4
        assert rendered["report"]["bounds_checked"]
        assert rendered["width"] == 1800 and rendered["height"] == 1200
        assert store.asset_path(project["id"], rendered["asset"]).is_file()
        assert not any("Correzione" in event for event in events)
    finally:
        store.db.close()
