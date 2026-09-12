import copy
import hashlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image

from h3_slides.document_image_search import DocumentImageSearch
from h3_slides.models import ProjectInput
from h3_slides.storage import Store


def request(**values):
    return SimpleNamespace(**{
        "query": "", "source": "document", "include_pages": False, "search_id": "", "page": 0, **values})


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path)
    project = store.create(ProjectInput(prompt="Una presentazione sulle piante", count=1).model_dump())
    source = {"id": "source", "kind": "pdf", "name": "Botanica.pdf", "images": [], "page_count": 30,
              "selection": {"pdf_pages": [2, 3], "scope_mode": "auto", "summary": "Le piante · PDF 2–3",
                  "prompt_hash": hashlib.sha256(project["prompt"].encode()).hexdigest()}}
    project["sources"] = [source]
    finder = DocumentImageSearch()
    yield store, project, source, finder
    store.db.close()


def asset(store, project, source, ident="figure.jpg", *, page=2, kind="figure", **values):
    Image.new("RGB", (720, 420), "navy").save(store.asset_path(project["id"], ident), format="JPEG")
    row = {"id": ident, "label": f"Figura · {source['name']}, pagina PDF {page}",
           "pdf_page": page, "kind": kind, **values}
    source["images"].append(row)
    return row


def test_manual_search_respects_selected_pages_without_mutating_project(setup):
    store, p, source, finder = setup
    asset(store, p, source, "inside.jpg", page=2)
    asset(store, p, source, "old-run.jpg", page=18)
    snapshot = copy.deepcopy(p)
    before = sorted(path.name for path in store.asset_path(p["id"], "inside.jpg").parent.iterdir())
    page = finder.search(store, p, "s", request())
    assert page["total"] == 1 and len(page["results"]) == 1
    row = finder.result(store, p, "s", page["search_id"], page["results"][0]["id"])
    assert row["image_id"] == "inside.jpg" and row["source_id"] == "source"
    assert "PDF 2–3" in page["message"]
    assert p == snapshot
    assert before == sorted(path.name for path in store.asset_path(p["id"], "inside.jpg").parent.iterdir())
    assert not {"image_id", "path", "preview", "context"} & page["results"][0].keys()


def test_ten_results_at_a_time_repeat_pages_and_unknown_ids(setup):
    store, p, source, finder = setup
    for i in range(23):
        asset(store, p, source, f"f{i}.jpg")
    first = finder.search(store, p, "s", request())
    ident = first["search_id"]
    assert len(ident) == 40 and ident.startswith("doc-")
    assert len(first["results"]) == 10 and first["has_more"]
    assert finder.search(store, p, "s", request(search_id=ident)) == first
    with pytest.raises(ValueError, match="ordine"):
        finder.search(store, p, "s", request(search_id=ident, page=2))
    second = finder.search(store, p, "s", request(search_id=ident, page=1))
    last = finder.search(store, p, "s", request(search_id=ident, page=2))
    assert len(second["results"]) == 10 and len(last["results"]) == 3 and not last["has_more"]
    assert len({r["id"] for part in (first, second, last) for r in part["results"]}) == 23
    with pytest.raises(KeyError):
        finder.result(store, p, "s", ident, "../../secret.jpg")
    with pytest.raises(ValueError, match="prima"):
        finder.search(store, p, "s", request(page=1))


def test_full_document_uses_actual_selection_not_unsaved_scope_switch(setup):
    store, p, source, finder = setup
    asset(store, p, source, "inside.jpg", page=2)
    asset(store, p, source, "outside.jpg", page=25)
    p["pdf_scope"] = "whole"
    page = finder.search(store, p, "s", request())
    assert page["total"] == 1 and "ultima porzione lavorata" in page["message"]
    source["selection"].update(pdf_pages=list(range(1, 31)), scope_mode="whole", summary="Documento completo · PDF 1–30")
    page = finder.search(store, p, "s", request())
    assert page["total"] == 2 and page["scopes"][0]["whole"] is True


@pytest.mark.parametrize("selection", [None, {}, {"pdf_pages": []}, {"pdf_pages": [True]}, {"pdf_pages": [31]}, {"pdf_pages": "2"}])
def test_missing_or_invalid_scope_does_not_expose_old_assets(setup, selection):
    store, p, source, finder = setup
    asset(store, p, source)
    source["selection"] = selection
    page = finder.search(store, p, "s", request(include_pages=True))
    assert not page["results"] and "porzione non ancora individuata" in page["message"]
    p["pdf_scope"] = "whole"
    assert not finder.search(store, p, "s", request())["results"], "A setting alone does not prove all pages were worked"


def test_changed_brief_warns_but_retains_last_worked_portion(setup):
    store, p, source, finder = setup
    asset(store, p, source)
    p["prompt"] = "Ora tutto il libro"
    page = finder.search(store, p, "s", request())
    assert page["total"] == 1 and "ultima porzione lavorata" in page["message"]


def test_page_previews_are_opt_in_and_standalone_images_are_always_available(setup):
    store, p, source, finder = setup
    asset(store, p, source, "page.jpg", kind="page", label="Botanica.pdf, pagina PDF 2")
    attachment = {"id": "photo", "kind": "png", "name": "Foto.png", "images": []}
    p["sources"].append(attachment)
    asset(store, p, attachment, "photo.jpg", kind="image", label="Foto personale")
    p["use_source_images"] = False
    page = finder.search(store, p, "s", request())
    assert page["total"] == 1 and page["results"][0]["document"] == "Foto.png"
    assert page["results"][0]["pdf_page"] is None
    page = finder.search(store, p, "s", request(include_pages=True))
    assert page["total"] == 2 and any(row["kind"] == "page" for row in page["results"])


def test_legacy_pdf_page_label_is_explicit_and_kind_aware(setup):
    store, p, source, finder = setup
    a = asset(store, p, source, "legacy-figure.jpg", label="Figura · Botanica.pdf, pagina PDF 2")
    b = asset(store, p, source, "legacy-page.jpg", label="Botanica.pdf, pagina PDF 2")
    c = asset(store, p, source, "unknown.jpg", label="Illustrazione 2")
    for item in (a, b, c):
        item.pop("pdf_page")
        item.pop("kind")
    page = finder.search(store, p, "s", request())
    assert page["total"] == 1 and page["results"][0]["kind"] == "figure"
    assert finder.search(store, p, "s", request(include_pages=True))["total"] == 2


def test_query_ranks_by_page_text_without_hiding_unmatched_images(setup):
    store, p, source, finder = setup
    for i in range(12):
        asset(store, p, source, f"old{i}.jpg", page=2)
    asset(store, p, source, "target.jpg", page=3)
    source["page_index_file"] = "index.json"
    store.asset_path(p["id"], "index.json").write_text(json.dumps({"pages": [
        {"pdf_page": 2, "text": "La poesia classica nasce nel Mediterraneo."},
        {"pdf_page": 3, "text": "Fotosintesi clorofilliana delle piante tramite energia luminosa."}]}), encoding="utf-8")
    page = finder.search(store, p, "s", request(query="fotosintesi clorofilliana"))
    row = finder.result(store, p, "s", page["search_id"], page["results"][0]["id"])
    assert row["image_id"] == "target.jpg" and page["total"] == 13
    assert "riconoscimento visivo" in page["message"]
    assert finder.search(store, p, "s", request(query="Nessuna corrispondenza"))["total"] == 13
    for state in finder.searches.values():
        assert all(not {"context", "description", "confident", "score"} & row.keys() for row in state["rows"])


def test_full_book_browsing_is_not_silently_limited_to_four_hundred(setup):
    store, p, source, finder = setup
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "navy").save(image, format="JPEG")
    raw = image.getvalue()
    for index in range(411):
        ident = f"image-{index}.jpg"
        store.asset_path(p["id"], ident).write_bytes(raw)
        source["images"].append({"id": ident, "label": f"Figura {index}", "kind": "figure", "pdf_page": 2})
    first = finder.search(store, p, "s", request())
    assert first["total"] == 411
    found = list(first["results"])
    for index in range(1, 42):
        page = finder.search(store, p, "s", request(search_id=first["search_id"], page=index))
        assert page["has_more"] == (index < 41)
        found.extend(page["results"])
    assert len(found) == len({row["id"] for row in found}) == 411


def test_missing_and_unsafe_assets_are_skipped_and_preview_is_sanitized(setup):
    store, p, source, finder = setup
    asset(store, p, source)
    source["images"].extend([{ "id": ident, "kind": "figure", "pdf_page": 2} for ident in
                            ("missing.jpg", "../../secret.jpg", "C:\\secret.jpg", "payload.svg")])
    page = finder.search(store, p, "s", request())
    assert page["total"] == 1 and "4 immagini non disponibili" in page["message"]
    raw = finder.preview(store, p, "s", page["search_id"], page["results"][0]["id"])
    with Image.open(io.BytesIO(raw)) as image:
        assert image.format == "JPEG" and image.width <= 400 and image.height <= 300
    store.asset_path(p["id"], "figure.jpg").unlink()
    with pytest.raises(ValueError, match="non più disponibile"):
        finder.result(store, p, "s", page["search_id"], page["results"][0]["id"])


@pytest.mark.parametrize("mutation", ["prompt", "selection", "source_removed", "image_removed", "image_metadata", "pdf_scope"])
def test_mutations_invalidate_continuation_preview_and_selection(setup, mutation):
    store, p, source, finder = setup
    asset(store, p, source)
    page = finder.search(store, p, "s", request())
    ident, chosen = page["search_id"], page["results"][0]["id"]
    if mutation == "prompt": p["prompt"] += " nuovo"
    elif mutation == "selection": source["selection"]["pdf_pages"] = [3]
    elif mutation == "source_removed": p["sources"] = []
    elif mutation == "image_removed": source["images"] = []
    elif mutation == "image_metadata": source["images"][0]["pdf_page"] = 3
    else: p["pdf_scope"] = "whole"
    with pytest.raises(ValueError, match="cambiate"):
        finder.search(store, p, "s", request(search_id=ident))
    with pytest.raises(ValueError, match="cambiate"):
        finder.result(store, p, "s", ident, chosen)
    with pytest.raises(ValueError, match="cambiate"):
        finder.preview(store, p, "s", ident, chosen)


def test_search_ids_cannot_cross_project_slide_or_expiry(setup):
    store, p, source, finder = setup
    asset(store, p, source)
    page = finder.search(store, p, "s", request())
    ident, chosen = page["search_id"], page["results"][0]["id"]
    for project, sid in (({**p, "id": "other"}, "s"), (p, "other-slide")):
        with pytest.raises(ValueError, match="scaduta"):
            finder.result(store, project, sid, ident, chosen)
    finder.searches[ident]["expires"] = time.monotonic()-1
    with pytest.raises(ValueError, match="scaduta"):
        finder.result(store, p, "s", ident, chosen)


def test_parallel_file_io_avoids_sqlite_and_cache_is_bounded(setup):
    store, p, source, finder = setup
    asset(store, p, source)
    with ThreadPoolExecutor(max_workers=4) as executor:
        pages = list(executor.map(lambda _: finder.search(store, p, "s", request()), range(28)))
        assert len(finder.searches) == 24
        page = pages[-1]
        raw = executor.submit(finder.preview, store, p, "s", page["search_id"], page["results"][0]["id"]).result()
        assert raw.startswith(b"\xff\xd8")
