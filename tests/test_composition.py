import pytest
from h3_slides.composition import split_content
from h3_slides.models import SlideContent, ProjectInput
from h3_slides.content_rules import validate_content, content_contract


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_variable_paragraphs_keep_real_prose(count):
    text = "Un paragrafo collega le cause agli effetti e spiega il significato attraverso un esempio concreto. "*2
    c = SlideContent(title="Spiegazione", layout="cards", blocks=[{"text": text}]*count)
    validate_content(c, ProjectInput().model_dump(), "")


def test_combined_budget_prevents_four_oversized_boxes():
    c = SlideContent(title="Troppo testo", blocks=[{"text": "Una frase completa. "*30}]*4)
    with pytest.raises(ValueError, match="complessivo"):
        validate_content(c, ProjectInput().model_dump(), "")


def test_planned_count_divides_budget_for_small_models():
    p = ProjectInput(use_manim_diagrams=True).model_dump()
    schema, rules = content_contract(p, 3)
    assert schema["properties"]["blocks"]["minItems"] == 3
    assert schema["properties"]["blocks"]["maxItems"] == 3
    assert schema["$defs"]["TextBlock"]["properties"]["text"]["maxLength"] == 740//3+120
    assert "246" in rules and "740" in rules


@pytest.mark.asyncio
async def test_worker_repairs_overlong_small_model_draft(tmp_path):
    from types import SimpleNamespace
    from h3_slides.storage import Store
    from h3_slides.worker import Worker
    from h3_slides.models import Generation
    store = Store(tmp_path)
    project = store.create(ProjectInput(prompt="Spiega un processo", count=1, use_manim_diagrams=True).model_dump())
    schemas = []
    class DraftLLM:
        def __init__(self, *_): pass
        async def prepare(self): pass
        async def json(self, prompt, schema=None, **_):
            if "Proponi esattamente" in prompt:
                return {"slides":[{"title":"Processo","purpose":"Quattro passaggi","layout":"steps","block_count":4}]}
            schemas.append(schema["$defs"]["TextBlock"]["properties"]["text"]["maxLength"])
            words = ("Una spiegazione chiara collega il passaggio precedente al successivo e ne illustra le conseguenze. "*3
                     if len(schemas)==1 else
                     "Il passaggio viene descritto attraverso un esempio semplice. La spiegazione collega le cause agli effetti in modo chiaro.")
            return SlideContent(title="Processo", layout="steps", blocks=[{"text":words}]*4).model_dump()
    worker = Worker(store, SimpleNamespace())
    worker.clients = DraftLLM
    try:
        job = worker.submit(project["id"], Generation(provider={"model":"fake"}, prompt=project["prompt"], count=1))
        await worker.tasks[job["id"]]
        assert store.job(job["id"])["status"] == "completed"
        assert schemas == [305, 185]
        assert len(store.project(project["id"])["slides"][0]["content"]["blocks"]) == 4
    finally:
        await worker.close()
        store.db.close()


def test_split_preserves_every_character_and_quote_provenance():
    text = "Prima frase letterale del libro. Seconda frase con dettagli e accenti: perché è così. "*18
    c = SlideContent(title="Titolo", blocks=[{"text":text, "kind":"quote", "source":"libro.md, p. 2"}],
                     sources=["libro.md, p. 2"], notes="Note originali", image_id="abc.jpg")
    pieces = split_content(c.model_dump())
    assert len(pieces) >= 2
    assert "".join(p["blocks"][0]["text"] for p in pieces) == text
    assert all(p["blocks"][0]["source"] == "libro.md, p. 2" and p["notes"] == c.notes
               and p["image_id"] == c.image_id and p["sources"] == c.sources for p in pieces)
    assert c.blocks[0].text == text


def test_split_keeps_bullets_stored_behind_prose():
    c = SlideContent(title="Titolo", blocks=[{"text":"Paragrafo uno."}, {"text":"Paragrafo due."}],
                     bullets=["Punto precedente conservato"])
    assert all(p["bullets"] == c.bullets for p in split_content(c.model_dump()))
    with pytest.raises(ValueError, match="dividere"):
        split_content(SlideContent(title="Titolo").model_dump())


def test_layout_rejects_executable_or_unknown_instructions():
    with pytest.raises(ValueError):
        SlideContent(title="Titolo", layout="<script>")
    with pytest.raises(ValueError):
        SlideContent(title="Titolo", layout_variant=-1)


@pytest.mark.asyncio
async def test_split_api_checks_revision_and_keeps_all_content(tmp_path):
    from pathlib import Path
    from aiohttp.test_utils import TestClient, TestServer
    from h3_slides.app import create_app
    from h3_slides.storage import uid
    app = create_app(Path(__file__).resolve().parents[1], tmp_path / "data")
    headers = {"X-H3-Slides":"1"}
    async with TestClient(TestServer(app)) as client:
        p = app["store"].create(ProjectInput(title="Prova divisione").model_dump())
        c = SlideContent(title="Testi da conservare", blocks=[{"text":"Primo paragrafo."}, {"text":"Secondo paragrafo."}],
                         notes="Note da conservare", sources=["Fonte verificata"])
        sid = uid()
        p["slides"] = [{"id":sid,"revision":1,"status":"ready","content":c.model_dump()}]
        app["store"].save_project(p)
        url = f"/api/projects/{p['id']}/slides/{sid}/split"
        assert (await client.post(url, json={"revision":1})).status == 403
        assert (await client.post(url, headers=headers, json={"revision":0})).status == 409
        assert len(app["store"].project(p["id"])["slides"]) == 1
        result = await client.post(url, headers=headers, json={"revision":1})
        assert result.status == 200
        updated = await result.json()
        assert updated["count"] == 2
        assert updated["slides"][0]["id"] == sid and updated["slides"][0]["revision"] == 2
        assert len({s["id"] for s in updated["slides"]}) == 2
        assert [s["content"]["blocks"][0]["text"] for s in updated["slides"]] == [b.text for b in c.blocks]
        assert all(s["content"]["notes"] == c.notes and s["content"]["sources"] == c.sources for s in updated["slides"])
        assert (await client.post(url, headers=headers, json={"revision":1})).status == 409
