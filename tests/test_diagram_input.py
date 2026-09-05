import copy

import pytest

from h3_slides.diagram_input import normalize_scene_input


def scene(element, *others):
    return {"title": "Dati", "elements": [element, *others]}


def test_explicit_arrows_are_moved_not_inferred_or_lost():
    source = scene({"id": "a", "type": "document", "text": "Ingresso"},
                   {"id": "b", "type": "circle", "text": "Risultato"},
                   {"type": "arrow", "from": "a", "to": "b", "text": "Produce"})
    before = copy.deepcopy(source)
    result, changed = normalize_scene_input(source)
    assert changed and source == before
    assert len(result["elements"]) == 2
    assert result["connections"] == [{"source": "a", "target": "b", "label": "Produce"}]
    assert normalize_scene_input(result) == (result, False)


@pytest.mark.parametrize("edge", [
    {"type": "arrow", "source": "a", "target": "missing"},
    {"type": "arrow", "source": "a", "target": "a"},
    {"type": "arrow", "start": [0, 0], "end": [1, 1]},
    {"type": "arrow", "source": "a", "target": "b", "weight": 3},
])
def test_incomplete_or_ambiguous_arrows_are_not_silently_removed(edge):
    with pytest.raises(ValueError, match="Collegamento"):
        normalize_scene_input(scene({"id": "a", "type": "circle"}, {"id": "b", "type": "circle"}, edge))


def test_graph_named_nodes_and_edges_keep_exact_declared_topology():
    result, changed = normalize_scene_input(scene({"type": "directed_graph",
        "nodes": [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}],
        "edges": [{"source": "n2", "target": "n1"}]}))
    node = result["elements"][0]
    assert changed and node == {"type": "network", "directed": True, "labels": ["A", "B"], "values": [1, 0]}


@pytest.mark.parametrize("edges", [[["A", "missing"]], [[0, 2]], [[True, 1]],
                                  [{"source": "A", "target": "B", "weight": 9}]])
def test_graph_adapter_never_creates_nodes_or_discards_edge_weights(edges):
    with pytest.raises(ValueError, match="Rete"):
        normalize_scene_input(scene({"type": "network", "labels": ["A", "B"], "edges": edges}))


def test_scatter_pairs_and_bar_records_preserve_signed_values():
    result, _ = normalize_scene_input(scene({"type": "scatter_plot", "points": [[1, -2], [3, 0]]},
        {"type": "bar_chart", "data": [{"label": "A", "value": -4}, {"label": "B", "value": 0}]}))
    assert result["elements"][0] == {"type": "scatter", "x_values": [1, 3], "values": [-2, 0]}
    assert result["elements"][1] == {"type": "bars", "labels": ["A", "B"], "values": [-4, 0]}


def test_histogram_aliases_are_only_raw_samples_and_explicit_edges():
    result, _ = normalize_scene_input(scene({"type": "histogram", "data": [1, 2, 2], "bins": [0, 2, 3]}))
    assert result["elements"][0] == {"type": "histogram", "samples": [1, 2, 2], "bin_edges": [0, 2, 3]}
    ambiguous = scene({"type": "histogram", "values": [1, 2, 3]})
    assert normalize_scene_input(ambiguous) == (ambiguous, False)


@pytest.mark.parametrize("element", [
    {"type": "histogram", "data": [1, "missing"], "bins": [0, 2]},
    {"type": "histogram", "data": [1, 2], "bins": 2},
    {"type": "network", "nodes": ["A", "A"], "edges": []},
    {"type": "network", "labels": ["A", "B"], "edges": [[0, 1]], "values": [1, 0]},
    {"type": "function_plot", "formula": "x^2", "expression": "1/x"},
    {"type": "box", "position": {"x": 1, "y": 2}, "x": 3},
])
def test_conflicting_aliases_or_missing_data_trigger_correction(element):
    with pytest.raises(ValueError):
        normalize_scene_input(scene(element))


def test_function_intervals_and_formula_are_preserved():
    result, _ = normalize_scene_input({"scene": scene({"type": "function", "formula": "1/x",
                                                      "domain": [-3, 3], "range": [-5, 5]})})
    assert result["elements"][0] == {"type": "function_plot", "expression": "1/x",
                                    "x_min": -3, "x_max": 3, "y_min": -5, "y_max": 5}


@pytest.mark.parametrize("element", [
    {"type": "directed_graph", "directed": 0, "labels": ["A"], "values": []},
    {"type": "bar_chart", "data": [{"label": "A", "value": 1}], "values": [True]},
    {"type": "network", "labels": ["A", "B"], "edges": [[0, 1]], "values": [False, True]},
    {"type": "arrow", "source": [], "target": {}},
    {"type": "scatter", "points": [[10**1000, 0], [1, 2]]},
])
def test_malformed_json_and_boolean_numbers_are_never_silently_sanitized(element):
    with pytest.raises(ValueError):
        normalize_scene_input(scene(element))


def test_unknown_type_container_remains_a_validation_error_not_a_crash():
    value = scene({"id": "a", "type": {"unknown": 1}})
    assert normalize_scene_input(value) == (value, False)


def test_generic_graph_without_explicit_topology_does_not_guess_edges():
    value = scene({"type": "graph", "labels": ["A", "B", "C", "D"], "values": [1, 2, 2, 3]})
    assert normalize_scene_input(value) == (value, False)


def test_xy_objects_and_equal_numeric_domain_aliases_are_supported():
    result, _ = normalize_scene_input(scene({"type": "scatter", "points": [{"x": 10, "y": -2}, {"x": 30, "y": 0}]},
        {"type": "function_plot", "expression": "x", "domain": ["0", "1"], "x_min": "0", "x_max": "1"}))
    assert result["elements"][0]["x_values"] == [10, 30]
    assert result["elements"][1]["x_min"] == 0 and result["elements"][1]["x_max"] == 1
