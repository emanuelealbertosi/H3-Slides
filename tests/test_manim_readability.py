import re
from manim import Text, tempconfig
import pytest
from h3_slides.diagram_spec import ManimSceneSpec
from h3_slides.diagrams import normalize_scene_geometry
from h3_slides.manim_scene import build_scene
from h3_slides.manim_typography import fit_text


def compact(text):
    return re.sub(r"\s+", "", text)


def test_normalization_never_discards_label_suffixes():
    texts = ["Acquisizione completa delle informazioni dal documento originale",
             "Presentazione dei risultati con tutte le etichette leggibili"]
    value = {"title": "Informazioni complete", "elements": [
        {"id": f"node{i}", "type": "box", "x": x, "y": 4, "width": 2, "height": .9, "text": t}
        for i, (x, t) in enumerate(zip((3, 9), texts))]}
    result, _ = normalize_scene_geometry(value)
    assert [e["text"] for e in result["elements"]] == texts
    value["elements"][0]["text"] = "Testo " * 100
    result, _ = normalize_scene_geometry(value)
    assert result["elements"][0]["text"] == value["elements"][0]["text"].strip()
    with pytest.raises(ValueError):
        ManimSceneSpec.model_validate(result)  # Redesign, never a silently cut success.


def test_small_nodes_grow_without_losing_words_shapes_or_relationships(tmp_path):
    scene = {"title": "Trasformazione delle informazioni", "elements": [
        {"id": "source", "type": "box", "x": 3, "y": 4, "width": 2, "height": .9,
         "text": "Acquisizione completa delle informazioni dal documento originale"},
        {"id": "result", "type": "document", "x": 9, "y": 4, "width": 2, "height": .9,
         "text": "Presentazione dei risultati con tutte le etichette leggibili"}],
        "connections": [{"source": "source", "target": "result", "label": "elaborazione dei dati"}]}
    with tempconfig({"media_dir": str(tmp_path)}):
        root, _, _, _, report = build_scene(scene, {"theme": "paper", "font": "Arial"})
    rendered = [compact(obj.text) for obj in root.get_family() if isinstance(obj, Text)]
    for text in [scene["title"], *(e["text"] for e in scene["elements"]), scene["connections"][0]["label"]]:
        assert compact(text) in rendered
    assert report["shortened_texts"] == 0 and report["text_layout_adjusted"]
    assert report["connections"] == 1 and report["types"] == ["box", "document"]
    assert 500 <= report["display_min_width"] <= 1100
    assert report["display_min_width"] / 1800 * report["min_glyph_height_px"] >= 16
    assert root.width <= 12 and root.height <= 8


def test_impossible_slot_is_rejected_instead_of_an_ellipsis(tmp_path):
    with tempconfig({"media_dir": str(tmp_path)}):
        with pytest.raises(ValueError, match="completo"):
            fit_text("Questa etichetta deve rimanere completa fino all'ultima parola", .2, .1,
                     font="Arial", color="#000000", size=24, minimum=20)


@pytest.mark.parametrize("kind,labels,values", [
    ("gantt", ["Analisi dei requisiti funzionali", "Verifica finale dei risultati"], [0, 3, 2, 6]),
    ("bars", ["Risultati prima della verifica", "Risultati dopo la correzione", "Controllo finale dei dati"], [12, 17, 21]),
    ("timeline", ["Raccolta dei dati iniziali", "Verifica delle informazioni", "Presentazione dei risultati"], [0, 5, 10]),
    ("tree", ["Sistema informativo", "Archivio documenti", "Gestione utenti"], [0, 0]),
    ("network", ["Client remoto", "Server locale", "Archivio dati", "Rete interna"], [0, 1, 1, 2, 2, 3, 3, 0]),
])
def test_long_compound_labels_are_rendered_without_truncation(kind, labels, values, tmp_path):
    value = {"title": "Attività", "elements": [{"id": "chart", "type": kind, "x": 6, "y": 4.1,
        "width": 11, "height": 5.8, "labels": labels, "values": values}]}
    normalized, _ = normalize_scene_geometry(value)
    assert ManimSceneSpec.model_validate(normalized).elements[0].labels == value["elements"][0]["labels"]
    with tempconfig({"media_dir": str(tmp_path)}):
        root, _, _, _, report = build_scene(normalized, {"theme": "paper", "font": "Arial"})
    rendered = [compact(obj.text) for obj in root.get_family() if isinstance(obj, Text)]
    assert all(compact(label) in rendered for label in labels)
    assert report["shortened_texts"] == 0 and report["min_font_size"] >= 20
    assert root.width <= 12 and root.height <= 8
