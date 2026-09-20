import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from h3_slides.page_layout import (
    HEIGHTS, PageMeasurer, fit_pages, format_brief, main_heading,
    ordered_leaves, preserves_content, split_page,
)
from h3_slides.page_v2 import PageSpec


def page_fixture(long=False):
    return PageSpec.model_validate({
        "style": {"gap": 26}, "notes": "Note complete\nNon cancellare.",
        "sources": ["Documento, pagina 2", "Fonte web", "Documento, pagina 2"],
        "nodes": [
            {"id": "title", "kind": "heading", "role": "title", "text": "Un titolo prima dei gruppi"},
            {"id": "outer", "kind": "group", "style": {"flow": "columns", "columns": [2, 1], "gap": 20}},
            {"id": "nested", "parent": "outer", "kind": "group", "style": {"padding": 18}},
            {"id": "paragraph", "parent": "nested", "kind": "text", "text": ("Primo paragrafo: parole, accenti è e formula \\(x^2\\).\n" * (80 if long else 1)), "source": "Fonte A"},
            {"id": "code", "parent": "nested", "kind": "code", "language": "python", "text": ("for i in range(3):\n    print(i)\n" * (90 if long else 1)), "source": "Codice, pagina 3"},
            {"id": "photo", "parent": "outer", "kind": "image", "text": "La didascalia", "asset_id": "abc-123.jpg", "query": "Un soggetto pertinente", "source": "Autore immagine"},
            {"id": "diagram", "parent": "outer", "kind": "diagram", "text": "Le relazioni tra concetti", "asset_id": "manim-" + "a" * 64 + ".png", "query": "Schema", "source": "Fonte schema"},
            {"id": "paragraph_part2", "kind": "text", "text": "ID già occupato, non sovrascrivere", "source": "Fonte B"},
            {"id": "last", "kind": "text", "text": "Ultimo paragrafo dopo i gruppi.", "source": "Fonte C"},
        ],
    })


def assert_lossless(original, pages):
    heading = main_heading(original)
    heading_id = heading.id if heading else None
    expected = {n.id: n for n in ordered_leaves(original) if n.id != heading_id}
    chunks = {key: [] for key in expected}
    order = []
    original_nodes = {n.id: n for n in original.nodes}
    for page in pages:
        PageSpec.model_validate(page.model_dump())
        assert page.sources == original.sources
        assert page.notes == original.notes
        containers = {"root": page.style, **{n.id: n.style for n in page.nodes if n.kind == "group"}}
        old_containers = {"root": original.style, **{n.id: n.style for n in original.nodes if n.kind == "group"}}
        for parent, style in containers.items():
            old_style = old_containers[parent]
            assert style.model_dump(exclude={"columns", "span"}) == old_style.model_dump(exclude={"columns", "span"})
            if style.columns != old_style.columns:
                assert old_style.flow == "columns"
                children = [n for n in page.nodes if n.parent == parent]
                needed = sum(min(len(old_style.columns), n.style.span) for n in children)
                assert len(style.columns) == needed < len(old_style.columns), "Only empty tracks can be pruned"
                tracks = iter(old_style.columns)
                assert all(any(value == track for track in tracks) for value in style.columns), "Surviving track weights keep their order"
        assert page.style.span == original.style.span
        leaves = ordered_leaves(page)
        if heading:
            assert leaves[0].id == heading.id, "Main heading remains before nested content"
            assert leaves[0].text == heading.text
        for node in page.nodes:
            source_id = node.id if node.id in original_nodes else next(
                key for key in expected if node.id.startswith(key + "_part"))
            old = original_nodes[source_id]
            parent_style, old_parent_style = containers[node.parent], old_containers[node.parent]
            expected_span = min(old.style.span, len(parent_style.columns)) if parent_style.columns != old_parent_style.columns else old.style.span
            assert node.style.span == expected_span
            if node.kind == "group":
                assert node.model_dump(exclude={"style"}) == old.model_dump(exclude={"style"})
            else:
                assert node.style.model_dump(exclude={"span"}) == old.style.model_dump(exclude={"span"})
        for node in leaves:
            if node.id == heading_id:
                continue
            source_id = node.id if node.id in expected else next(
                key for key in expected if node.id.startswith(key + "_part"))
            old = expected[source_id]
            assert node.parent == old.parent
            for key in ("kind", "language", "asset_id", "query", "source"):
                assert getattr(node, key) == getattr(old, key), (source_id, key)
            chunks[source_id].append(node.text)
            if not order or order[-1] != source_id:
                order.append(source_id)
    assert order == list(expected), "Reading order survives across continuation pages"
    for key, node in expected.items():
        assert "".join(chunks[key]) == node.text, key


@pytest.mark.parametrize("name,height", HEIGHTS.items())
@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
def test_format_brief_reports_nominal_and_bounded_dimensions(name, height, mode):
    import math
    text = format_brief({"slide_format": name, "canvas_mode": mode})
    assert f"Formato {name}" in text
    assert f"larghezza 1280 px, altezza nominale {height} px" in text
    assert f"massimo {math.ceil(height * 1.15) if mode == 'adaptive' else height} px" in text
    assert "minimo 20" in text and "codice minimo 18" in text


def test_format_brief_legacy_defaults_to_16_9():
    assert "Formato 16:9" in format_brief({})
    assert "massimo 720 px" in format_brief({})


def test_project_format_default_and_enum_are_legacy_compatible():
    from h3_slides.models import ProjectInput
    assert ProjectInput().slide_format == "16:9"
    assert ProjectInput.model_validate({"engine": "v2"}).slide_format == "16:9"
    assert set(ProjectInput.model_json_schema()["properties"]["slide_format"]["enum"]) == set(HEIGHTS)


@pytest.mark.parametrize("name", HEIGHTS)
@pytest.mark.parametrize("mode", ["fixed", "adaptive"])
def test_project_accepts_bounded_v2_formats_and_preserves_them(name, mode):
    from h3_slides.models import ProjectInput
    project = ProjectInput(engine="v2", slide_format=name, canvas_mode=mode)
    assert project.model_dump()["slide_format"] == name and project.canvas_mode == mode


@pytest.mark.parametrize("value", ["9:16", "16/9", "free", "", None, 1.5])
def test_project_rejects_unknown_or_non_string_formats(value):
    from h3_slides.models import ProjectInput
    with pytest.raises(ValueError):
        ProjectInput(engine="v2", slide_format=value)


@pytest.mark.parametrize("field,value", [
    ("kind", "heading"), ("text", "Testo riscritto"), ("language", "javascript"),
    ("asset_id", "b.jpg"), ("query", "Altra query"), ("source", "Altra fonte"),
])
def test_reflow_may_not_change_semantic_leaf_fields(field, value):
    original = page_fixture()
    changed = original.model_copy(deep=True)
    node = next(n for n in changed.nodes if n.id == "code")
    setattr(node, field, value)
    assert not preserves_content(original, [changed])


def test_reflow_rejects_omissions_additions_and_duplicate_content():
    original = page_fixture()
    missing = original.model_copy(deep=True)
    missing.nodes = [n for n in missing.nodes if n.id != "last"]
    assert not preserves_content(original, [missing])
    added = original.model_copy(deep=True)
    added.nodes.append(original.nodes[-1].model_copy(update={"id": "invented"}))
    assert not preserves_content(original, [added])
    assert not preserves_content(original, [original, original.model_copy(deep=True)])
    assert preserves_content(original, [original.model_copy(deep=True)])


def test_reflow_rejects_changed_reading_order_even_when_each_leaf_is_unchanged():
    original = page_fixture()
    changed = original.model_copy(deep=True)
    first = next(i for i, n in enumerate(changed.nodes) if n.id == "paragraph")
    second = next(i for i, n in enumerate(changed.nodes) if n.id == "code")
    changed.nodes[first], changed.nodes[second] = changed.nodes[second], changed.nodes[first]
    PageSpec.model_validate(changed.model_dump())
    assert not preserves_content(original, [changed])


@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("long", [False, True])
def test_split_is_bounded_lossless_and_preserves_tree_order_and_sources(count, long):
    original = page_fixture(long)
    before = original.model_dump()
    pages = split_page(original, count)
    assert 2 <= len(pages) <= count <= 3
    assert_lossless(original, pages)
    assert original.model_dump() == before
    pages[0].sources.append("Modifica locale")
    assert original.sources == before["sources"]


def test_title_only_page_is_not_duplicated_to_fill_split_count():
    original = PageSpec(nodes=[{"id": "title", "kind": "heading", "text": "Solo un titolo"}])
    pages = split_page(original, 3)
    assert len(pages) == 1 and pages[0] == original and pages[0] is not original


def columns_fixture(weights, spans, root=False):
    style = {"flow": "columns", "columns": weights, "gap": 19, "padding": 17,
             "surface": "paper", "radius": 8, "border": True, "align": "center"}
    nodes = [] if root else [
        {"id": "title", "kind": "heading", "role": "title", "text": "Titolo conservato"},
        {"id": "group", "kind": "group", "text": "Contenitore", "style": style},
    ]
    nodes.extend({"id": "body" + str(i), "parent": "root" if root else "group", "kind": "text",
                  "text": f"Contenuto {i} da conservare.", "source": f"Fonte {i}",
                  "style": {"span": span, "bold": True}} for i, span in enumerate(spans))
    return PageSpec.model_validate({"style": style if root else {"gap": 21}, "nodes": nodes,
                                   "sources": ["Fonte comune"], "notes": "Note immutate"})


@pytest.mark.parametrize("root", [False, True])
def test_split_prunes_empty_weighted_tracks_at_group_and_root_without_mutation(root):
    original = columns_fixture([1, 2, 4], [1, 1, 1], root=root)
    before = original.model_dump()
    pages = split_page(original, 3)
    styles = [page.style if root else next(n.style for n in page.nodes if n.id == "group") for page in pages]
    assert [style.columns for style in styles] == [[1], [2], [4]]
    assert_lossless(original, pages)
    assert original.model_dump() == before
    styles[0].columns[0] = 19
    assert original.model_dump() == before and styles[1].columns == [2]


def test_split_keeps_all_weighted_tracks_covered_by_a_surviving_span():
    original = columns_fixture([1, 2, 3, 4], [2, 1, 1])
    before = original.model_dump()
    pages = split_page(original, 3)
    assert [next(n.style.columns for n in page.nodes if n.id == "group") for page in pages] == [[1, 2], [3], [4]]
    assert [next(n.style.span for n in page.nodes if n.kind == "text") for page in pages] == [2, 1, 1]
    assert_lossless(original, pages)
    assert original.model_dump() == before


def test_split_track_mapping_respects_implicit_row_wrap_from_spanning_children():
    original = columns_fixture([1, 2, 4], [2, 2, 1])
    before = original.model_dump()
    pages = split_page(original, 3)
    assert [next(n.style.columns for n in page.nodes if n.id == "group") for page in pages] == [[1, 2], [1, 2], [4]]
    assert_lossless(original, pages)
    assert original.model_dump() == before


def test_split_does_not_prune_a_full_row_or_change_stack_container_styles():
    for flow in ("columns", "stack", "row"):
        original = columns_fixture([2, 5], [1, 1, 1, 1])
        original.nodes[1].style.flow = flow
        before = original.model_dump()
        pages = split_page(original, 2)
        assert all(next(n.style.columns for n in page.nodes if n.id == "group") == [2, 5] for page in pages)
        assert_lossless(original, pages)
        assert original.model_dump() == before


def test_split_text_continuations_use_the_original_node_track_weight():
    original = columns_fixture([2, 5, 9], [1, 1, 1])
    original.nodes[3].text = "Testo lungo da continuare senza perdere parole. " * 100
    before = original.model_dump()
    pages = split_page(original, 3)
    middle = pages[1]
    bodies = [n for n in middle.nodes if n.kind == "text"]
    assert len(bodies) == 1 and bodies[0].id.startswith("body1_part")
    assert next(n.style.columns for n in middle.nodes if n.id == "group") == [5]
    assert_lossless(original, pages)
    assert original.model_dump() == before


def test_text_chunks_preserve_whitespace_and_avoid_existing_part_ids():
    original = PageSpec(nodes=[
        {"id": "title", "kind": "heading", "role": "title", "text": "Titolo"},
        {"id": "paragraph", "kind": "text", "text": "  Prima riga.\nSeconda  riga è lunga.\n" * 140, "source": "Fonte completa"},
        {"id": "paragraph_part2", "kind": "text", "text": "ID da conservare"},
    ])
    pages = split_page(original, 3)
    assert len(pages) == 3
    ids = [n.id for p in pages for n in ordered_leaves(p) if n.id != "title"]
    assert len(ids) == len(set(ids))
    assert "paragraph_part3" in ids
    assert_lossless(original, pages)


@pytest.mark.parametrize("line", ["    print(i)\n", "    print('Una riga di codice intenzionalmente più lunga per il controllo della divisione')\n"])
def test_multiline_code_can_use_continuations_without_splitting_lines(line):
    original = PageSpec(nodes=[
        {"id": "title", "kind": "heading", "role": "title", "text": "Codice completo"},
        {"id": "code", "kind": "code", "language": "python", "text": line * 90, "source": "Pagina codice"},
    ])
    pages = split_page(original, 3)
    assert len(pages) == 3, "Many short code lines need continuation pages too"
    assert_lossless(original, pages)
    for page in pages:
        code = next(n for n in page.nodes if n.kind == "code")
        assert code.text.endswith("\n")
        assert all(part == line for part in code.text.splitlines(keepends=True))


def test_reflow_allows_only_the_original_title_on_each_continuation():
    original = PageSpec(nodes=[
        {"id": "title", "kind": "heading", "role": "title", "text": "Titolo originale"},
        {"id": "first", "kind": "text", "text": "Prima parte"},
        {"id": "second", "kind": "text", "text": "Seconda parte"},
    ])
    pages = [PageSpec(nodes=[original.nodes[0].model_copy(deep=True), original.nodes[index].model_copy(deep=True)]) for index in (1, 2)]
    assert preserves_content(original, pages)
    pages[1].nodes[0].text = "Titolo diverso"
    assert not preserves_content(original, pages)


class FakeProbe:
    def __init__(self, overflow):
        self.overflow = overflow
        self.pages = []

    async def measure(self, project, page):
        self.pages.append(page.model_copy(deep=True))
        overflow = self.overflow(page, len(self.pages))
        if isinstance(overflow, BaseException):
            raise overflow
        return {"overflow": overflow, "height": 828, "neededHeight": 1400 if overflow else 800,
                "baseHeight": 720, "maxHeight": 828, "nodes": len(page.nodes)}


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def json(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if isinstance(self.response, BaseException):
            raise self.response
        return copy.deepcopy(self.response)


class FakeWorker:
    def __init__(self, probe, cancel_at=None):
        self.page_measurer = probe
        self.events = []
        self.checkpoints = 0
        self.cancel_at = cancel_at
        self.store = SimpleNamespace(event=lambda jid, message: self.events.append((jid, message)))

    async def checkpoint(self, jid):
        self.checkpoints += 1
        if self.cancel_at == self.checkpoints:
            raise asyncio.CancelledError()


PROJECT = {"id": "fixture", "slide_format": "16:9", "canvas_mode": "adaptive"}


@pytest.mark.asyncio
async def test_measured_page_that_fits_needs_no_llm_or_extra_pages():
    page = page_fixture()
    probe = FakeProbe(lambda page, number: False)
    client = FakeClient(AssertionError("No LLM call expected"))
    worker = FakeWorker(probe)
    pages, reports = await fit_pages(worker, client, "job", PROJECT, page, 2)
    assert pages == [page] and len(reports) == 1 and not reports[0]["overflow"]
    assert len(probe.pages) == worker.checkpoints == 1 and not client.calls


@pytest.mark.asyncio
async def test_no_probe_retains_compatibility_without_llm_or_page_mutation():
    page = page_fixture()
    worker, client = FakeWorker(None), FakeClient(AssertionError("No call"))
    pages, reports = await fit_pages(worker, client, "job", PROJECT, page, 2)
    assert pages == [page] and pages[0] is page and reports == [{}]
    assert not client.calls and worker.checkpoints == 0


@pytest.mark.asyncio
async def test_one_reflow_can_change_layout_but_restores_notes_and_sources():
    page = page_fixture()
    candidate = page.model_copy(deep=True)
    candidate.style.gap = 12
    candidate.notes = "Do not trust replacement notes"
    candidate.sources = ["Do not trust replacement sources"]
    probe = FakeProbe(lambda page, number: number == 1)
    client = FakeClient({"pages": [candidate.model_dump()]})
    worker = FakeWorker(probe)
    pages, reports = await fit_pages(worker, client, "job", PROJECT, page, 2)
    assert len(client.calls) == 1 and len(probe.pages) == 2
    assert len(pages) == 1 and pages[0].style.gap == 12
    assert preserves_content(page, pages)
    assert pages[0].sources == page.sources and pages[0].notes == page.notes
    assert not reports[0]["overflow"]
    assert "1 fino a 3 pagine" in client.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_changed_llm_text_is_rejected_then_original_content_is_split():
    page = page_fixture()
    altered = page.model_copy(deep=True)
    altered.nodes[-1].text = "Un riassunto che perderebbe contenuto"
    probe = FakeProbe(lambda page, number: number == 1)
    client = FakeClient({"pages": [altered.model_dump()]})
    pages, reports = await fit_pages(FakeWorker(probe), client, "job", PROJECT, page, 2)
    assert len(client.calls) == 1 and len(pages) == 2
    assert len(probe.pages) == 3, "Invalid LLM content is never rendered"
    assert all(not r["overflow"] for r in reports)
    assert_lossless(page, pages)


@pytest.mark.asyncio
async def test_overflow_tries_one_reflow_then_two_and_three_pages_at_most():
    page = page_fixture()
    before = page.model_dump()
    # Original/reflow and both 2-way pages overflow; the 3-way fallback fits.
    probe = FakeProbe(lambda page, number: number <= 4)
    client = FakeClient({"pages": [page.model_dump()]})
    worker = FakeWorker(probe)
    pages, reports = await fit_pages(worker, client, "job", PROJECT, page, 99)
    assert len(client.calls) == 1 and len(probe.pages) == 7
    assert len(pages) == 3 and len(reports) == 3
    assert "1 fino a 3 pagine" in client.calls[0]["prompt"]
    assert_lossless(page, pages)
    assert page.model_dump() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("extra,max_pages,measurements", [(0, 1, 1), (1, 2, 3), (2, 3, 6)])
async def test_exhausted_budget_fails_without_mutating_or_losing_the_draft(extra, max_pages, measurements):
    page = page_fixture()
    before = page.model_dump()
    probe = FakeProbe(lambda page, number: True)
    client = FakeClient(ValueError("Invalid JSON from fixture"))
    worker = FakeWorker(probe)
    with pytest.raises(ValueError, match="Bozza conservata"):
        await fit_pages(worker, client, "job", PROJECT, page, extra)
    assert len(client.calls) == 1 and len(probe.pages) == measurements
    assert f"1 fino a {max_pages} pagine" in client.calls[0]["prompt"]
    assert page.model_dump() == before


@pytest.mark.asyncio
async def test_zero_extra_budget_rejects_multi_page_llm_response():
    page = page_fixture()
    probe = FakeProbe(lambda page, number: True)
    client = FakeClient({"pages": [page.model_dump(), page.model_dump()]})
    with pytest.raises(ValueError, match="Bozza conservata"):
        await fit_pages(FakeWorker(probe), client, "job", PROJECT, page, 0)
    assert len(probe.pages) == 1 and len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["checkpoint", "probe", "llm", "fallback"])
async def test_cancellation_propagates_without_more_measurement_or_reflow(stage):
    page = page_fixture()
    probe = FakeProbe(lambda page, number: asyncio.CancelledError() if stage == "probe" else True)
    client = FakeClient(asyncio.CancelledError() if stage == "llm" else ValueError("Invalid response"))
    worker = FakeWorker(probe, cancel_at=1 if stage == "checkpoint" else 2 if stage == "fallback" else None)
    with pytest.raises(asyncio.CancelledError):
        await fit_pages(worker, client, "job", PROJECT, page, 2)
    assert len(probe.pages) == (0 if stage == "checkpoint" else 1)
    assert len(client.calls) == (1 if stage in {"llm", "fallback"} else 0)


@pytest.mark.asyncio
async def test_measurer_without_runtime_fails_before_spawning_any_process(tmp_path, monkeypatch):
    from h3_slides import page_layout
    monkeypatch.setattr(page_layout.subprocess, "Popen", lambda *a, **k: pytest.fail("No subprocess expected"))
    store = SimpleNamespace(asset_path=lambda *args: pytest.fail("No asset lookup expected"))
    page = PageSpec(nodes=[{"id": "text", "kind": "text", "text": "Una frase"}])
    with pytest.raises(ValueError, match="installazione di Node"):
        await PageMeasurer(tmp_path, store).measure(PROJECT, page)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,asset", [("image", "a1.jpg"), ("diagram", "manim-" + "a" * 64 + ".png")])
@pytest.mark.parametrize("state", ["missing", "unreadable"])
async def test_measurer_rejects_missing_or_unreadable_named_assets_before_probe(tmp_path, monkeypatch, kind, asset, state):
    from h3_slides import page_layout
    path = tmp_path / asset
    if state == "unreadable":
        path.write_bytes(b"Synthetic fixture: not an image")
    lookups = []

    def asset_path(pid, name):
        lookups.append((pid, name))
        return path

    monkeypatch.setattr(page_layout.subprocess, "Popen", lambda *a, **k: pytest.fail("Invalid assets must stop before spawning"))
    page = PageSpec(nodes=[{"id": "asset", "kind": kind, "asset_id": asset}])
    expected = "non trovata" if state == "missing" else "non leggibile"
    with pytest.raises(ValueError, match=expected) as error:
        await PageMeasurer(tmp_path, SimpleNamespace(asset_path=asset_path)).measure(PROJECT, page)
    assert lookups == [(PROJECT["id"], asset)]
    assert str(tmp_path) not in str(error.value)
    assert page.nodes[0].asset_id == asset, "The missing asset is not silently replaced by a placeholder"


@pytest.mark.asyncio
async def test_empty_media_placeholder_has_no_missing_asset_lookup(tmp_path, monkeypatch):
    from h3_slides import page_layout
    monkeypatch.setattr(page_layout.subprocess, "Popen", lambda *a, **k: pytest.fail("No runtime installed in fixture"))
    store = SimpleNamespace(asset_path=lambda *a: pytest.fail("An empty placeholder does not reference an asset"))
    page = PageSpec(nodes=[{"id": "placeholder", "kind": "image", "asset_id": ""}])
    with pytest.raises(ValueError, match="installazione di Node"):
        await PageMeasurer(tmp_path, store).measure(PROJECT, page)


@pytest.mark.asyncio
async def test_measurer_sends_only_rendering_data_and_closes_probe_guard(tmp_path, monkeypatch):
    from h3_slides import page_layout
    executable = tmp_path / "runtime" / "node" / "node.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    captured = {}

    class Guard:
        def assign(self, process):
            captured["assigned"] = process

        def close(self):
            captured["closed"] = True

    class Process:
        returncode = 0

        def communicate(self, data, timeout):
            captured["payload"] = json.loads(data)
            assert timeout == 30
            return json.dumps({"overflow": False, "height": 720}).encode(), b""

        def poll(self):
            return self.returncode

    def popen(args, **kwargs):
        captured["args"], captured["options"] = args, kwargs
        return Process()

    monkeypatch.setattr(page_layout, "ChildGuard", Guard)
    monkeypatch.setattr(page_layout.subprocess, "Popen", popen)
    page = PageSpec(nodes=[{"id": "text", "kind": "text", "text": "Testo di misura"}])
    store = SimpleNamespace(asset_path=lambda *args: pytest.fail("No asset lookup expected"))
    project = {**PROJECT, "title": "Prova", "prompt": "Brief escluso dalla misura", "api_key": "synthetic-secret-not-for-probe"}
    report = await PageMeasurer(tmp_path, store).measure(project, page)
    assert report == {"overflow": False, "height": 720}
    assert captured["closed"] is True and captured["assigned"] is not None
    assert captured["payload"]["page"] == page.model_dump()
    assert "prompt" not in captured["payload"]["project"] and "api_key" not in captured["payload"]["project"]
    assert captured["args"] == [str(executable), str(tmp_path / "scripts" / "measure_page.mjs")]
