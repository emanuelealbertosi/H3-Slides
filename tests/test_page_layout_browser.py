"""Actual browser geometry must agree with the worker's overflow recovery."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from h3_slides.models import ProjectInput
from h3_slides.page_layout import PageMeasurer, fit_pages, ordered_leaves, split_page
from h3_slides.page_v2 import PageSpec
from h3_slides.storage import Store


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / "runtime/node/node.exe").is_file(),
                                reason="Requires the installed application browser runtime")


@pytest.mark.asyncio
@pytest.mark.parametrize("format,mode,maximum", [("16:9", "adaptive", 828), ("4:3", "fixed", 960)])
async def test_real_measurement_splits_long_page_without_losing_text(tmp_path, format, mode, maximum):
    store = Store(tmp_path / "data")
    project = store.create(ProjectInput(engine="v2", slide_format=format, canvas_mode=mode, count=1).model_dump())
    original = PageSpec.model_validate({"nodes": [
        {"id": "title", "kind": "heading", "role": "title", "text": "Contenuti da distribuire"},
        {"id": "columns", "kind": "group", "style": {"flow": "columns", "columns": [1, 1]}},
        *[{"id": f"p{i}", "kind": "text", "parent": "columns",
           "text": f"Concetto {i}. " + "Una spiegazione completa con parole e frasi leggibili. " * 6,
           "source": "Manuale, pagina 3"} for i in range(20)]
    ], "sources": ["Manuale, pagina 3"], "notes": "Le note originali restano disponibili."})
    events = []
    async def checkpoint(jid):
        pass
    class Client:
        calls = 0
        async def json(self, prompt, **kwargs):
            self.calls += 1
            raise ValueError("Fixture: use the lossless fallback, never a real model")
    client = Client()
    worker = SimpleNamespace(page_measurer=PageMeasurer(ROOT, store), checkpoint=checkpoint,
                             store=SimpleNamespace(event=lambda jid, message: events.append(message)))
    before = await worker.page_measurer.measure(project, original)
    assert before["overflow"] and before["height"] <= maximum
    pages, reports = await fit_pages(worker, client, "fixture", project, original, 2)
    assert client.calls == 1 and 2 <= len(pages) <= 3
    assert all(not report["overflow"] and report["height"] <= maximum for report in reports)
    assert all(page.notes == original.notes and page.sources == original.sources for page in pages)
    actual = [(node.id, node.text, node.source) for page in pages for node in ordered_leaves(page) if node.id != "title"]
    expected = [(node.id, node.text, node.source) for node in ordered_leaves(original) if node.id != "title"]
    assert actual == expected
    assert any("slide" in message for message in events)


@pytest.mark.asyncio
async def test_split_discards_empty_columns_around_a_wide_image(tmp_path):
    """Synthetic 19-node page: retained three-track parents must not waste width."""
    store = Store(tmp_path / "data")
    project = store.create(ProjectInput(engine="v2", count=1, slide_format="16:9",
        canvas_mode="adaptive", theme="paper", font="Segoe UI", theme_design={
            "visual_family": "modern", "heading_font": "Segoe UI", "title_size": 44,
            "box_radius": 22, "border_width": 1}).model_dump())
    asset = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jpg"
    Image.new("RGB", (1063, 153), "white").save(store.asset_path(project["id"], asset))
    def text(length):
        return ("Una proposta sintetica collega forme, colori e passaggi di un progetto semplice. " * 8)[:length]
    def node(id, parent="root", kind="text", role="body", length=0, **style):
        return {"id": id, "parent": parent, "kind": kind, "role": role,
                "text": text(length), "style": {"font_size": 22, **style}}
    figure = node("figure", "middle", "image", "auto", 87, font_size=20,
                  padding=12, surface="paper", radius=18, border=True)
    figure.update(asset_id=asset, source=text(78))
    original = PageSpec.model_validate({"style": {"gap": 18}, "nodes": [
        node("eyebrow", kind="heading", role="eyebrow", length=26, font_size=20, bold=True),
        node("title", kind="heading", role="title", length=22, font_size=44, bold=True),
        node("lead", role="lead", length=157, font_size=24),
        node("main", kind="group", role="auto", flow="columns", columns=[4, 5, 4]),
        node("left", "main", "group", "auto", gap=12, surface="plain"),
        node("left_heading", "left", "heading", "subtitle", 25, font_size=28, bold=True),
        *[node(f"step{i}", "left", role="step", length=length)
          for i, length in enumerate([40, 104, 52, 55])],
        node("left_note", "left", length=118, padding=14, surface="soft", radius=18),
        node("middle", "main", "group", "auto", gap=10, surface="plain"),
        figure,
        node("right", "main", "group", "auto", gap=12, surface="plain"),
        node("right_heading", "right", "heading", "subtitle", 33, font_size=28, bold=True),
        *[node(f"callout{i}", "right", role="callout", length=length,
               padding=14, surface=surface, radius=18)
          for i, (length, surface) in enumerate([(85, "soft"), (63, "example"), (77, "key")])],
        node("right_note", "right", length=158, padding=14, surface="quote", radius=18),
    ], "sources": ["Fonte sintetica: nessun contenuto del libro"],
       "notes": "Conservare note, testi, figure e ordine delle sezioni."})
    before = original.model_dump()
    assert len(original.nodes) == 19
    probe = PageMeasurer(ROOT, store)
    original_report = await probe.measure(project, original)
    assert original_report["overflow"]
    pages = split_page(original, 2)
    assert len(pages) == 2
    # Recreate only the old split mistake: all other nodes and settings match.
    legacy = pages[1].model_copy(deep=True)
    legacy_parent = next(n for n in legacy.nodes if n.id == "main")
    legacy_parent.style.flow, legacy_parent.style.columns = "columns", [4, 5, 4]
    assert (await probe.measure(project, legacy))["overflow"]
    reports = [await probe.measure(project, page) for page in pages]
    assert all(not report["overflow"] and report["height"] <= 828 for report in reports), reports
    assert sum(report["knownMedia"] for report in reports) == 1
    actual = [(n.id, n.text, n.source, n.asset_id) for page in pages
              for n in ordered_leaves(page) if n.id != "title"]
    expected = [(n.id, n.text, n.source, n.asset_id) for n in ordered_leaves(original) if n.id != "title"]
    assert actual == expected
    assert all(page.notes == original.notes and page.sources == original.sources for page in pages)
    assert original.model_dump() == before
