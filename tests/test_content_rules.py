import pytest
from h3_slides.models import ProjectInput, SlideContent
from h3_slides.content_rules import content_contract, validate_content, fit_complete_sentences


def test_slide_generation_schema_omits_deferred_manim_geometry():
    schema, _ = content_contract({"text_density": "detailed"}, None)
    assert schema["$defs"]["DiagramSpec"]["properties"]["scene"] == {"type": "null"}
    assert not {"Connection", "Element", "ManimSceneSpec"} & schema["$defs"].keys()
    assert "freeform" not in schema["properties"]
    assert "freeform_base" not in schema["properties"]
    assert "freeform_compact" not in schema["properties"]
    assert "freeform" not in schema["properties"]["layout"]["enum"]


def test_freeform_geometry_is_editor_owned_and_bounded():
    content = SlideContent(title="Libera", layout="freeform", blocks=[{"text": "Testo."}],
                           freeform={"heading": {"x": 48, "y": 60, "w": 1184, "h": 120},
                                     "block-0": {"x": 48, "y": 200, "w": 380, "h": 440}})
    assert content.freeform["block-0"].w == 380
    with pytest.raises(ValueError, match="canvas"):
        SlideContent(title="Fuori", layout="freeform", blocks=[{"text": "Testo."}],
                     freeform={"block-0": {"x": 1200, "y": 200, "w": 380, "h": 440}})


def test_old_slides_remain_valid():
    old = SlideContent(title="Vecchia slide", bullets=["Testo conservato"])
    assert old.blocks == []


@pytest.mark.parametrize("density", ["detailed", "complete"])
@pytest.mark.parametrize("visual", [False, True])
def test_prose_contract_requires_visible_paragraphs(density, visual):
    p = ProjectInput(text_density=density, use_manim_diagrams=visual).model_dump()
    schema, rules = content_contract(p)
    assert schema["properties"]["blocks"]["minItems"] == 1
    assert schema["properties"]["blocks"]["maxItems"] == 4
    assert schema["properties"]["bullets"]["maxItems"] == 0
    assert "paragrafo" in rules and "NON" in rules
    with pytest.raises(ValueError, match="paragrafi"):
        validate_content(SlideContent(title="Titolo", bullets=["Poche parole"]), p, "")
    c = SlideContent(title="Titolo", blocks=[{"text":"Frase completa. "*22}]*2)
    validate_content(c, p, "")


def test_exact_quote_and_source_are_checked():
    p = ProjectInput().model_dump()
    p["sources"] = [{"name":"libro.md"}]
    paragraph = "Un paragrafo originale collega il concetto a una conseguenza concreta. "*3
    c = SlideContent(title="Citazione", blocks=[
        {"text":paragraph, "kind":"quote", "source":"libro.md, p. 2"},
        {"text":"La spiegazione collega le cause agli effetti attraverso un esempio concreto. "*3}])
    validate_content(c, p, "[libro.md, p. 2]\n"+paragraph)
    assert c.sources == ["libro.md, p. 2"]
    with pytest.raises(ValueError, match="Citazione non verificabile"):
        validate_content(c, p, "Una fonte diversa.")
    with pytest.raises(ValueError, match="Citazione non verificabile"):
        validate_content(c, ProjectInput().model_dump(), paragraph)
    with pytest.raises(ValueError, match="Citazione non verificabile"):
        validate_content(c, p, "[altro.md, p. 2]\n"+paragraph)
    c.blocks[0].source = "libro.md, pagina inventata 999"
    validate_content(c, p, "[libro.md, pagina PDF 22, pagina stampata 2]\n"+paragraph)
    assert c.blocks[0].source == "libro.md, pagina PDF 22, pagina stampata 2"


def test_brief_stays_brief():
    p = ProjectInput(text_density="brief").model_dump()
    validate_content(SlideContent(title="Titolo", bullets=["Accenno"]), p, "")
    with pytest.raises(ValueError):
        validate_content(SlideContent(title="Titolo", bullets=["x"*100]), p, "")


def test_incomplete_sentence_is_not_saved():
    c = SlideContent(title="Titolo", blocks=[{"text":"Una frase completa. "*15+"parola interrott"},
                                            {"text":"Una frase completa. "*15}])
    with pytest.raises(ValueError, match="frase incompleta"):
        validate_content(c, ProjectInput().model_dump(), "")


def test_final_fit_preserves_full_sentences_and_original_text():
    p = ProjectInput().model_dump()
    original = "Un paragrafo spiega il concetto e lo collega a un esempio concreto. "*12+"parola interrotta"
    c = SlideContent(title="Titolo", blocks=[{"text":original}, {"text":"Una frase completa. "*15}])
    assert fit_complete_sentences(c, p)
    validate_content(c, p, "")
    assert c.blocks[0].text.endswith(".")
    assert len(c.blocks[0].text) <= 650
    assert original in c.notes
    c.blocks[0].kind, c.blocks[0].source, c.blocks[0].text = "quote", "libro.md", original
    fit_complete_sentences(c, p)
    assert c.blocks[0].text == original  # A literal source passage is never rewritten.
