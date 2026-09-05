"""Intent recognition must not create extra chart obligations from prose."""
from types import SimpleNamespace

import pytest

from h3_slides.diagram_intent import (requested_family, requested_families, requested_scene_families,
                                     validate_designed_scene)
from h3_slides.diagram_spec import ManimSceneSpec


@pytest.mark.parametrize(("instruction", "family"), [
    ("Disegna un istogramma", "histogram"), ("Two histograms", "histogram"),
    ("Un grafico a barre", "bars"), ("Column chart", "bars"), ("Bar graph", "bars"),
    ("Grafico a linee", "plot"), ("Line graph", "plot"), ("plot", "plot"),
    ("Scatter plot", "scatter"), ("Grafico di dispersione", "scatter"),
    ("La nuvola di punti", "scatter"), ("Grafico della funzione y = 1/x", "function_plot"),
    ("Plot the function", "function_plot"), ("Un plot di una funzione", "function_plot"),
    ("f(x) = x^2", "function_plot"), ("Function plot", "function_plot"),
    ("Disegna un grafo", "network"), ("Un diagramma di rete", "network"),
    ("An undirected graph", "network"), ("Graph with nodes and edges", "network"),
    ("Diagramma ad albero", "tree"), ("Decision tree", "tree"), ("Gerarchia", "tree"),
    ("Un diagramma di Venn", "venn"), ("Gantt chart", "gantt"),
    ("Linea del tempo", "timeline"), ("A timeline", "timeline"),
    ("Un diagramma di flusso", "flowchart"), ("A flow chart", "flowchart"),
    ("Confronta i due processi", "comparison"), ("A comparison of methods", "comparison"),
    ("Compare A and B", "comparison"), ("Please compare methods", "comparison"),
    ("Compare two processes", "comparison"),
])
def test_explicit_italian_and_english_visual_requests(instruction, family):
    assert requested_family(instruction) == family
    assert requested_families(instruction) == [family]


@pytest.mark.parametrize("text", [
    "Il fotografo imposta la macchina", "La fotografia mostra il soggetto",
    "Venne mostrato il risultato", "L'indicatore scompare", "Compare un indicatore",
    "Il risultato compare nel pannello", "Il risultato comparendo diventa visibile",
    "Funzioni computazionali avanzate", "Computational functions improve the image",
    "La bibliografia contiene riferimenti", "A graphical user interface", "",
])
def test_descriptive_prose_does_not_invent_a_required_family(text):
    assert requested_family(text) == ""
    assert requested_families(text) == []


def test_multiple_local_requests_preserve_order_and_specific_forms():
    value = "Confronta un istogramma, un grafo e la funzione y = x^2; aggiungi un altro grafo."
    assert requested_families(value) == ["comparison", "histogram", "network", "function_plot"]
    assert requested_family(value) == "histogram"
    assert requested_families("A scatter plot and a function plot") == ["scatter", "function_plot"]
    assert requested_family("Confronto tra funzioni y=1/x e y=x") == "function_plot"


@pytest.mark.parametrize(("instruction", "families"), [
    ("Non usare grafi, usa un istogramma", ["histogram"]),
    ("Non usare grafi e istogrammi, usa un grafico a barre", ["bars"]),
    ("Non usare grafi, istogrammi o Venn; mostra una timeline", ["timeline"]),
    ("Un istogramma senza un diagramma di rete", ["histogram"]),
    ("Evita il confronto; mostra un grafo", ["network"]),
    ("Non un grafo ma un istogramma", ["histogram"]),
    ("Do not use a network, use a histogram", ["histogram"]),
    ("Don't use a histogram or scatter plot; show a bar chart", ["bars"]),
    ("Avoid a network and use a histogram", ["histogram"]),
    ("No histogram, but a timeline", ["timeline"]),
])
def test_explicit_local_negations_do_not_require_the_excluded_family(instruction, families):
    assert requested_families(instruction) == families


@pytest.mark.parametrize("instruction", [
    "Non solo grafi ma anche istogrammi", "Non usare solo grafi, ma anche istogrammi",
    "Not only a network but also a histogram", "Do not use only a network; add a histogram",
    "Non meno di due grafi e un istogramma", "No fewer than two networks and a histogram",
])
def test_not_only_is_an_addition_not_a_prohibition(instruction):
    assert requested_families(instruction) == ["network", "histogram"]


@pytest.mark.parametrize(("instruction", "families"), [
    ("Evita sovrapposizioni nel grafico a barre", ["bars"]),
    ("Non superare 5 nodi nel network", ["network"]),
    ("Non usare troppe etichette nel grafico a barre", ["bars"]),
    ("Senza dettagli superflui nella timeline", ["timeline"]),
    ("Avoid overlaps in the bar chart", ["bars"]),
    ("Do not exceed 5 nodes in the network", ["network"]),
    ("Do not use long labels in the histogram", ["histogram"]),
    ("Evita sovrapposizioni nel grafo, senza un istogramma", ["network"]),
])
def test_layout_and_quantity_prohibitions_do_not_exclude_the_visual_family(instruction, families):
    assert requested_families(instruction) == families


@pytest.mark.parametrize(("title", "brief", "instructions", "expected"), [
    ("Grafico a barre", "Un grafico a barre con categorie", "Non usare grafico a barre, mostra un istogramma",
     ["histogram"]),
    ("Confronto con grafico a barre", "", "Non usare grafico a barre, mostra un istogramma",
     ["comparison", "histogram"]),
    ("Diagramma di flusso", "Diagramma di flusso", "Non usare diagrammi di flusso; disegna un grafo",
     ["network"]),
    ("A network", "A network and histogram", "Do not use a network, show a scatter plot",
     ["histogram", "scatter"]),
    ("Grafo e istogramma", "Senza un grafo", "", ["histogram"]),
    ("Istogramma", "", "Aggiungi un grafo", ["histogram", "network"]),
    ("Grafo", "Senza un grafo", "Mostra un grafo", ["network"]),
    ("Grafo", "", "Non usare grafi; mostra un grafo e un istogramma", ["network", "histogram"]),
    ("Grafico a barre", "", "Evita sovrapposizioni nel grafico a barre", ["bars"]),
    ("", "", "Non superare 5 nodi nel network", ["network"]),
    ("", "", "", []),
])
def test_scene_local_corrections_override_old_titles_without_losing_positive_requests(
        title, brief, instructions, expected):
    assert requested_scene_families(title, brief, instructions) == expected


def atom(identifier, x, y, kind="box"):
    return {"id": identifier, "type": kind, "x": x, "y": y, "width": 2.4, "height": 1.3,
            "text": identifier}


def two_processes(kind="box"):
    return ManimSceneSpec.model_validate({"title": "Confronto fra processi", "elements": [
        atom("a0", 3, 2.5, kind), atom("a1", 3, 5.5, kind),
        atom("b0", 9, 2.5, kind), atom("b1", 9, 5.5, kind)], "connections": [
        {"source": "a0", "target": "a1"}, {"source": "b0", "target": "b1"}]})


@pytest.mark.parametrize("kind", ["box", "circle", "document"])
def test_comparison_accepts_readable_independent_processes_with_internal_arrows(kind):
    scene = two_processes(kind)
    validate_designed_scene(scene, "comparison")


def test_single_flow_and_a_detached_heading_are_not_a_comparison():
    scene = ManimSceneSpec.model_validate({"title": "Un solo processo", "elements": [
        atom("a", 2, 3.3, "circle"), atom("b", 6, 3.3, "document"),
        atom("c", 10, 3.3, "circle"), atom("heading", 6, 6, "text")],
        "connections": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]})
    with pytest.raises(ValueError, match="confronto"):
        validate_designed_scene(scene, "comparison")
    validate_designed_scene(scene, "flowchart")


def test_interleaved_graph_components_do_not_form_readable_comparison_panels():
    scene = two_processes("circle")
    scene.connections[0].target = "b1"
    scene.connections[1].target = "a1"
    with pytest.raises(ValueError, match="distinti leggibili"):
        validate_designed_scene(scene, "comparison")


def test_separate_qualitative_panels_remain_a_valid_generic_comparison():
    scene = ManimSceneSpec.model_validate({"title": "Confronto", "elements": [
        atom("metodo_a", 3, 4), atom("metodo_b", 9, 4)]})
    validate_designed_scene(scene, ["comparison"])


@pytest.mark.parametrize(("kind", "data"), [
    ("bars", {"values": [-4, 2], "labels": ["A", "B"]}),
    ("histogram", {"samples": [1, 2, 3], "bin_edges": [0, 2, 4]}),
    ("scatter", {"x_values": [1, 2], "values": [-1, 3]}),
    ("plot", {"values": [2, 5]}), ("grid", {"values": [0, 1]}),
    ("function_plot", {"series": [object()]}), ("function_plot", {"tangent_at": 0}),
    ("function_plot", {"secant_x": [0, 1]}),
    ("gantt", {"labels": ["A", "B"], "values": [0, 2, 1, 3]}),
    ("venn", {"labels": ["A", "B"]}),
])
def test_generic_comparison_accepts_legitimate_quantitative_or_set_visuals(kind, data):
    # The separate scene compiler checks data ranges, formula safety and shape
    # geometry. Intent validation must not reject these chart families itself.
    element = SimpleNamespace(id="chart", type=kind, x=6, y=4, width=10, height=5, **data)
    scene = SimpleNamespace(elements=[element], connections=[])
    validate_designed_scene(scene, "comparison")
    validate_designed_scene(scene, [kind, "comparison"])


def test_one_histogram_bin_is_not_a_comparison_of_bins():
    element = SimpleNamespace(id="chart", type="histogram", x=6, y=4, width=10, height=5,
                              samples=[1, 2], bin_edges=[0, 3])
    with pytest.raises(ValueError, match="confronto"):
        validate_designed_scene(SimpleNamespace(elements=[element], connections=[]), "comparison")


def test_multiple_concrete_requirements_are_checked_without_requiring_unmentioned_types():
    elements = [SimpleNamespace(id="a", type="histogram", x=3, y=4, width=5, height=4,
                                samples=[1, 2], bin_edges=[0, 1, 3]),
                SimpleNamespace(id="b", type="network", x=9, y=4, width=5, height=4)]
    scene = SimpleNamespace(elements=elements, connections=[])
    validate_designed_scene(scene, ["histogram", "network", "comparison"])
    with pytest.raises(ValueError, match="function_plot"):
        validate_designed_scene(scene, ["histogram", "function_plot"])


def test_existing_all_box_single_flow_rule_still_applies():
    scene = ManimSceneSpec.model_validate({"title": "Flusso", "elements": [
        atom("a", 2, 4), atom("b", 6, 4), atom("c", 10, 4)],
        "connections": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]})
    with pytest.raises(ValueError, match="solo da rettangoli"):
        validate_designed_scene(scene)
