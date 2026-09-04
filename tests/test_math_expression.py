import math
import pytest

from h3_slides.math_expression import compile_expression, sample_expression
from h3_slides.diagram_spec import ManimSceneSpec
from h3_slides.manim_scene import build_scene


def test_safe_expressions_are_evaluated_without_eval():
    assert compile_expression("y = 1/x")(2) == .5
    assert compile_expression("sin(pi/2)")(0) == pytest.approx(1)
    assert compile_expression("sqrt(x^2) + abs(x)")(-3) == pytest.approx(6)


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
