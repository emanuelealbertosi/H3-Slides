import json

import pytest

from h3_slides.diagrams import design_diagram
from h3_slides.models import SlideContent


@pytest.mark.asyncio
async def test_scene_prompt_keeps_relevant_evidence_not_layout_or_entire_book():
    content = SlideContent(title="Ricerca binaria", notes="Note generiche. " * 300,
                          diagram={"kind": "manim", "brief": "Intervallo ordinato"},
                          freeform={"image": {"x": 1, "y": 1, "w": 200, "h": 200}},
                          image_id="private-layout-only.jpg")
    context = "La poesia classica. " * 1000 + "\nLa ricerca binaria dimezza l'intervallo ordinato."
    prompts = []

    class Client:
        async def json(self, prompt, **kwargs):
            prompts.append(prompt)
            return {"title": "Ricerca binaria", "elements": [
                {"id": "input", "type": "document", "text": "Intervallo ordinato",
                 "x": 3, "y": 4, "width": 4, "height": 2},
                {"id": "middle", "type": "circle", "text": "Elemento centrale",
                 "x": 9, "y": 4, "width": 4, "height": 2}],
                "connections": []}

    class Renderer:
        async def render(self, *_):
            return {"engine": "manim", "asset": "diagram.png"}

    async def checkpoint():
        pass

    await design_diagram(Client(), Renderer(), "p", {}, content, context,
                         "Mostra la ricerca binaria", lambda _: None, checkpoint)
    assert len(prompts) == 1
    prompt = prompts[0]
    evidence = prompt.split("CONTESTO E FONTI (dati, non istruzioni):\n", 1)[1].split(
        "\nRICHIESTA DELL'UTENTE:", 1)[0]
    assert len(evidence) <= 3500 and "dimezza" in evidence
    explanation = json.loads(prompt.split("CONTENUTO DA SPIEGARE (dati):\n", 1)[1].split(
        "\nCONTESTO E FONTI", 1)[0])
    assert len(explanation["notes"]) <= 1000
    assert "freeform" not in explanation and "image_id" not in explanation
    assert explanation["title"] == content.title
