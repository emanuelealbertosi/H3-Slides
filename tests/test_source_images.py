import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from h3_slides.source_images import (source_image_catalog, ranked_source_images,
                                     image_prompt_catalog, automatic_source_image)
from h3_slides.models import ProjectInput, Generation, SlideContent
from h3_slides.storage import Store
from h3_slides.worker import Worker


def entry(image_id, context, **kwargs):
    return {"image_id": image_id, "source": "Figura · Documento.pdf, pagina PDF 2",
            "kind": "figure", "pdf_page": 2, "context": context, "description": "", **kwargs}


def test_rank_all_figures_before_limiting_and_explain_page_context():
    catalog = [entry(f"old-{i}.jpg", "La poesia classica tratta forme letterarie.") for i in range(30)]
    catalog.append(entry("pertinente.jpg", "La ricerca binaria dimezza un intervallo ordinato ad ogni confronto."))
    ranked = ranked_source_images(catalog, "Ricerca binaria su un intervallo ordinato", limit=8)
    assert len(ranked) == 8 and ranked[0]["image_id"] == "pertinente.jpg"
    assert automatic_source_image(ranked)["image_id"] == "pertinente.jpg"
    prompt = image_prompt_catalog(ranked, "Ricerca binaria")
    assert "ricerca binaria" in prompt[0]["page_excerpt"].lower()
    assert "score" not in prompt[0] and "context" not in prompt[0]
    assert all(len(item["page_excerpt"]) <= 700 for item in prompt)


def test_image_context_has_one_total_budget_not_a_full_page_per_figure():
    catalog = [entry(f"figure-{i}.jpg", "La ricerca binaria confronta intervalli ordinati. " * 100)
               for i in range(20)]
    prompt = image_prompt_catalog(ranked_source_images(catalog, "Ricerca binaria"), "Ricerca binaria")
    assert len(prompt) == 12
    assert 0 < sum(len(item["page_excerpt"]) for item in prompt) <= 3200


def test_unrelated_or_generic_lone_match_does_not_force_a_figure():
    catalog = [entry("a.jpg", "Una fotocamera possiede un obiettivo e un otturatore.")]
    assert automatic_source_image(ranked_source_images(catalog, "Architettura delle reti neurali")) is None
    assert automatic_source_image(ranked_source_images(catalog, "Fotocamera alta risoluzione multi scatto")) is None
    assert automatic_source_image(ranked_source_images(catalog, "fotocamera"))["image_id"] == "a.jpg"
    assert automatic_source_image(ranked_source_images(catalog, "")) is None


def test_catalog_uses_selected_native_figures_not_pdf_page_previews(tmp_path):
    index = {"pages": [
        {"pdf_page": 1, "text": "Una pagina preliminare."},
        {"pdf_page": 2, "text": "La fotosintesi converte luce e acqua in sostanze organiche."},
    ]}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    store = SimpleNamespace(asset_path=lambda _pid, name: tmp_path / name)
    project = {"id": "p", "sources": [{"name": "Documento.pdf", "page_index_file": "index.json",
        "images": [
            {"id": "page.jpg", "label": "Documento.pdf, pagina PDF 2", "kind": "page", "pdf_page": 2},
            {"id": "figure.jpg", "label": "Figura · Documento.pdf, pagina PDF 2", "kind": "figure", "pdf_page": 2},
            {"id": "unselected.jpg", "label": "Figura · Documento.pdf, pagina PDF 1", "kind": "figure", "pdf_page": 1},
            {"id": "legacy-page.jpg", "label": "Documento.pdf, pagina PDF 2"},
        ]}]}
    result = source_image_catalog(store, project, [{"image_id": name} for name in
                                                  ("page.jpg", "figure.jpg", "legacy-page.jpg")])
    assert len(result) == 1 and result[0]["image_id"] == "figure.jpg"
    assert "fotosintesi" in result[0]["context"]


@pytest.mark.parametrize("payload", ["{invalid", "null", '{"pages": null}'])
def test_bad_optional_index_does_not_break_generation(tmp_path, payload):
    (tmp_path / "index.json").write_text(payload, encoding="utf-8")
    store = SimpleNamespace(asset_path=lambda _pid, name: tmp_path / name)
    project = {"id": "p", "sources": [{"name": "Fonte", "page_index_file": "index.json",
        "images": [{"id": "figure.jpg", "kind": "figure", "caption": "Albero genealogico familiare"}]}]}
    catalog = source_image_catalog(store, project, [{"image_id": "figure.jpg"}])
    assert automatic_source_image(ranked_source_images(catalog, "Albero genealogico"))["image_id"] == "figure.jpg"


def test_image_attachment_is_offered_without_inventing_a_description(tmp_path):
    store = SimpleNamespace(asset_path=lambda _pid, name: tmp_path / name)
    project = {"id": "p", "sources": [{"name": "Foto.jpg", "kind": "jpg",
                                      "images": [{"id": "photo.jpg", "label": "Foto.jpg"}]}]}
    catalog = source_image_catalog(store, project, [{"image_id": "photo.jpg"}])
    assert len(catalog) == 1
    assert image_prompt_catalog(ranked_source_images(catalog, "Un monumento"), "Un monumento")[0]["page_excerpt"] == ""
    assert automatic_source_image(ranked_source_images(catalog, "Un monumento")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "remote"])
async def test_worker_chooses_document_figure_alongside_manim_without_extra_llm(tmp_path, monkeypatch, mode):
    store = Store(tmp_path)
    try:
        project = store.create(ProjectInput(title="Biologia", prompt="La fotosintesi clorofilliana",
            count=1, text_density="brief", use_source_images=True, use_manim_diagrams=True,
            use_web_images=True).model_dump())
        project["sources"] = [{"id": "doc", "name": "Biologia.md", "kind": "md", "warnings": [],
            "text": "La fotosintesi clorofilliana converte luce e acqua in sostanze organiche.",
            "images": [{"id": "photosynthesis.jpg", "kind": "figure", "label": "Figura fotosintesi"}]}]
        store.save_project(project)
        calls = []
        class Client:
            def __init__(self, provider, *_):
                self.provider = provider
            async def prepare(self): pass
            async def json(self, prompt, **kwargs):
                calls.append(prompt)
                if "Proponi esattamente" in prompt:
                    return {"slides": [{"title": "Fotosintesi clorofilliana", "layout": "content"}]}
                if "Estrai fatti" in prompt:
                    return {"summary": "La fotosintesi clorofilliana usa luce e acqua."}
                assert '"page_excerpt"' in prompt
                assert "blocchi DISTINTI" in prompt
                return SlideContent(title="Fotosintesi clorofilliana",
                    bullets=["La luce fornisce energia."], image_id="").model_dump()
        async def diagram(*_, **__):
            return {"kind": "manim", "labels": [], "brief": "Trasformazione", "scene": None}, {
                "engine": "manim", "asset": "manim-poster.png"}
        async def forbidden_web(*_, **__):
            pytest.fail("A selected document figure should avoid image web research")
        worker = Worker(store, None)
        worker.clients = Client
        worker.web_images.acquire = forbidden_web
        monkeypatch.setattr("h3_slides.worker.design_diagram", diagram)
        job = worker.submit(project["id"], Generation(provider={"mode": mode, "model": "fake",
            "remote_consent": True, "base_url": "https://provider.example/v1"},
            prompt=project["prompt"], count=1))
        await worker.tasks[job["id"]]
        saved = store.project(project["id"])["slides"][0]
        assert store.job(job["id"])["status"] == "completed", store.job(job["id"])
        assert saved["content"]["image_id"] == "photosynthesis.jpg"
        assert saved["content"]["diagram"]["kind"] == "manim" and saved["diagram_render"]["asset"]
        assert "Figura fotosintesi" in saved["content"]["notes"]
        assert len(calls) == 3  # Summary, outline, slide; selection never needs a separate LLM call.
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_adding_manim_keeps_existing_photo_freeform_position(tmp_path, monkeypatch):
    store = Store(tmp_path)
    try:
        project = store.create(ProjectInput(prompt="Illustra la fotosintesi",
            use_manim_diagrams=True, use_source_images=True).model_dump())
        placement = {"x": 620, "y": 220, "w": 560, "h": 340}
        project["sources"] = [{"id": "d", "name": "Foto", "kind": "jpg", "text": "",
                              "images": [{"id": "photo.jpg", "label": "Foto"}], "warnings": []}]
        project["slides"] = [{"id": "s", "revision": 1, "status": "ready",
            "content": SlideContent(title="Fotosintesi", image_id="photo.jpg", layout="freeform",
                                    freeform={"visual": placement}).model_dump()}]
        store.save_project(project)
        worker = Worker(store, None)
        class Client:
            def __init__(self, *_): pass
            async def prepare(self): pass
        async def context(*_):
            return "Fotosintesi", [{"image_id": "photo.jpg", "source": "Foto"}]
        async def diagram(*_, **__):
            return {"kind": "manim", "labels": [], "brief": "Fotosintesi", "scene": None}, {
                "engine": "manim", "asset": "diagram.png"}
        worker.clients, worker.sources_context = Client, context
        monkeypatch.setattr("h3_slides.worker.design_diagram", diagram)
        job = worker.submit(project["id"], Generation(provider={"model": "fake"},
            prompt="Crea il diagramma", slide_id="s", diagram_only=True))
        await worker.tasks[job["id"]]
        result = store.project(project["id"])["slides"][0]
        assert store.job(job["id"])["status"] == "completed"
        assert result["content"]["image_id"] == "photo.jpg"
        assert result["content"]["freeform"] == {"image": placement}
        assert result["diagram_render"]["asset"] == "diagram.png" and result["revision"] == 2
    finally:
        store.db.close()
