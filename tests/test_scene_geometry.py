import copy
import math

import pytest

from h3_slides.diagrams import normalize_scene_geometry
from h3_slides.diagram_spec import ManimSceneSpec


def box(identity, **values):
    return {"id": identity, "type": "box", "text": identity,
            "x": 6, "y": 4, "width": 3, "height": 2, **values}


def normalized_scene(elements):
    original = {"title": "Geometria", "elements": elements, "connections": []}
    untouched = copy.deepcopy(original)
    result, changed = normalize_scene_geometry(original)
    assert original == untouched
    return result, changed


@pytest.mark.parametrize("omitted", [("width", "height"), ("x", "y"), ("x", "y", "width", "height")])
def test_missing_geometry_gets_packed_with_deterministic_defaults(omitted):
    elements = [box("a"), box("b"), box("c")]
    for element in elements:
        for key in omitted:
            element.pop(key)
    result, changed = normalized_scene(elements)
    assert changed
    scene = ManimSceneSpec.model_validate(result)
    assert len(scene.elements) == 3
    assert [(element.id, element.type, element.text) for element in scene.elements] == [
        (identity, "box", identity) for identity in ("a", "b", "c")]
    assert all(key in element for element in result["elements"] for key in ("x", "y", "width", "height"))
    assert all("values" not in element for element in result["elements"])


@pytest.mark.parametrize("annotations", [2, 3, 4])
def test_mixed_chart_and_annotation_rail_stays_inside_canvas(annotations):
    chart = {"id": "chart", "type": "plot", "x": 6, "y": 4,
             "width": 11, "height": 6, "values": [1, 4, 2, 5]}
    result, changed = normalized_scene([chart] + [box(f"note{i}") for i in range(annotations)])
    assert changed
    scene = ManimSceneSpec.model_validate(result)
    assert scene.elements[0].values == chart["values"]
    for element in scene.elements:
        assert element.y - element.height/2 >= 1.05
        assert element.y + element.height/2 <= 7.25


@pytest.mark.parametrize("field,bad_value", [
    ("width", {}), ("height", []), ("x", {"value": 3}), ("y", [4]),
    ("width", "large"), ("width", 10**400),
])
def test_malformed_geometry_is_left_for_validation_without_crashing_reflow(field, bad_value):
    malformed = box("invalid", **{field: bad_value})
    result, _ = normalized_scene([box("a", width=10, height=5),
                                  box("b", width=10, height=5), malformed])
    assert result["elements"][2][field] == bad_value
    with pytest.raises(ValueError):
        ManimSceneSpec.model_validate(result)


@pytest.mark.parametrize("bad_type", ["invented_shape", {}, []])
def test_unknown_or_malformed_shape_is_never_replaced_with_a_known_type(bad_type):
    result, _ = normalized_scene([box("unknown", type=bad_type)])
    assert result["elements"][0]["type"] == bad_type
    with pytest.raises(ValueError):
        ManimSceneSpec.model_validate(result)


@pytest.mark.parametrize("kind,payload", [
    ("histogram", {"samples": [-2, 0, 1, 3], "bin_edges": [-2, 0, 2, 4]}),
    ("scatter", {"x_values": [-2, 0, 1], "values": [1, -3, 2]}),
])
def test_new_charts_keep_supplied_data_and_labels_during_mixed_reflow(kind, payload):
    chart = {"id": "chart", "type": kind, "x": 6, "y": 4, "width": 11, "height": 6,
             "x_label": "Ascissa", "y_label": "Ordinata", **payload}
    result, changed = normalized_scene([chart, box("a"), box("b")])
    assert changed
    repaired = result["elements"][0]
    assert repaired["type"] == kind
    assert repaired["width"] >= 5 and repaired["height"] >= 3.5
    assert {key: repaired[key] for key in payload} == payload
    assert repaired["x_label"] == chart["x_label"] and repaired["y_label"] == chart["y_label"]
    assert all(math.isfinite(element[key]) for element in result["elements"]
               for key in ("x", "y", "width", "height"))


def test_missing_chart_geometry_preserves_directed_edges_and_signed_data():
    elements = [{"id": "graph", "type": "network", "labels": ["A", "B", "C"],
                 "values": [0, 1, 1, 2], "directed": True},
                {"id": "comparison", "type": "bars", "labels": ["A", "B"], "values": [-2, 0]}]
    result, changed = normalized_scene(elements)
    assert changed
    assert result["elements"][0]["directed"] is True
    assert result["elements"][0]["values"] == [0, 1, 1, 2]
    assert result["elements"][1]["values"] == [-2, 0]
    for element in result["elements"]:
        assert element["x"] - element["width"]/2 >= .15
        assert element["x"] + element["width"]/2 <= 11.85
        assert element["y"] - element["height"]/2 >= 1.05
        assert element["y"] + element["height"]/2 <= 7.25
