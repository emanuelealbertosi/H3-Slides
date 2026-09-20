import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from h3_slides.llm import parse_json
from h3_slides.models import Generation, Provider, ProjectInput
from h3_slides.page_v2 import PageSpec, PageStream
from h3_slides.storage import Store
from h3_slides.worker import Worker
from h3_slides.worker_v2 import run_pages


PREFIX = '{"style":{"gap":39,"flow":"columns","columns":[2,1]},"nodes":[{"id":"title","parent":"root","kind":"heading","text":"'


def test_open_text_grows_before_quote_or_node_closes_and_keeps_page_style():
    parser = PageStream()
    first = parser.feed(PREFIX + "Una")
    second = parser.feed(" slide")
    assert first["nodes"][0]["text"] == "Una"
    assert second["nodes"][0]["text"] == "Una slide"
    assert second["style"]["gap"] == 39
    assert second["style"]["columns"] == [2, 1]
    assert PageSpec.model_validate(second).nodes[0].parent == "root"


@pytest.mark.parametrize("content", [
    'Virgolette "testo", barre \\ e riga\nnuova',
    "Accenti è à, simbolo π, emoji 😀 e 𝄞",
    r"Formula \(\frac{1}{x}\) e \[\alpha + \beta\]",
    'Testo letterale <script>alert("x")</script>',
])
def test_every_packet_boundary_preserves_literal_text_and_unicode(content):
    parser = PageStream()
    parser.feed(PREFIX)
    encoded = json.dumps(content, ensure_ascii=True)[1:-1]
    previews = []
    for char in encoded:
        draft = parser.feed(char)
        if draft:
            PageSpec.model_validate(draft)
            text = draft["nodes"][0]["text"]
            assert content.startswith(text)
            text.encode("utf-8")  # No isolated Unicode surrogates in previews.
            previews.append(text)
    parser.feed('"}]}')
    assert parser.nodes[0].text == content
    assert any(previews)


def test_raw_latex_matches_final_parser_without_waiting_for_whole_page():
    raw = r'Formula \(\frac{1}{x}\) con \alpha e \nabla'
    full = PREFIX + raw + '"}]}'
    expected = parse_json(full)["nodes"][0]["text"]
    parser = PageStream()
    parser.feed(PREFIX)
    seen = []
    for char in raw:
        draft = parser.feed(char)
        if draft:
            text = draft["nodes"][0]["text"]
            assert expected.startswith(text)
            seen.append(text)
    parser.feed('"}]}')
    assert parser.nodes[0].text == expected
    assert any("Formula" in value for value in seen)


def test_quoted_or_nested_nodes_do_not_become_the_page_array():
    parser = PageStream()
    fake = 'Ignore "nodes": [{"id":"fake","kind":"text","text":"wrong"}]'
    assert parser.feed('{"notes":' + json.dumps(fake)) is None
    assert parser.feed(',"nodes":[{"id":"real","parent":"root","kind":"text","text":"giusto')
    assert [node.id for node in parser.nodes] == ["real"]
    nested = PageStream()
    assert nested.feed('{"other":{"nodes":[{"id":"fake","parent":"root","kind":"text","text":"wrong"}]}') is None


@pytest.mark.parametrize("prefix", [
    "Ecco {il risultato}:\n",
    'Ecco {prima {un esempio} e "una } citata"}:\n',
])
def test_braced_prose_prefix_recovers_before_the_real_page(prefix):
    parser = PageStream()
    for char in prefix:
        assert parser.feed(char) is None
    first = parser.feed(PREFIX + "Una")
    assert first["nodes"][0]["text"] == "Una"
    assert parser.feed(" pagina")["nodes"][0]["text"] == "Una pagina"
    parser.feed('"}]}')
    expected = PageSpec.model_validate(parse_json(prefix + PREFIX + 'Una pagina"}]}'))
    assert parser.nodes == expected.nodes


def test_prefix_recovery_skips_entire_quoted_and_nested_examples():
    fake = json.dumps({"nodes": [{"id": "fake", "parent": "root", "kind": "text", "text": "wrong"}]})
    for prefix in (json.dumps(fake), "{esempio " + fake + "}", "{esempio " + json.dumps(fake) + "}"):
        parser = PageStream()
        for char in prefix:
            assert parser.feed(char) is None
        assert not parser.nodes
        draft = parser.feed(PREFIX + "giusto")
        assert [node["id"] for node in draft["nodes"]] == ["title"]
        assert draft["nodes"][0]["text"] == "giusto"


@pytest.mark.parametrize("prefix", [
    '{"other":{"nodes":[{"id":"fake","parent":"root","kind":"text","text":"wrong"}]}}',
    '{"notes":"prefazione", broken}',
    '{"notes" broken}',
])
def test_prefix_recovery_never_restarts_an_object_after_a_json_key(prefix):
    parser = PageStream()
    for char in prefix + PREFIX + 'wrong"}]}':
        assert parser.feed(char) is None
    assert not parser.nodes


def test_identity_must_be_complete_and_no_parent_is_invented():
    parser = PageStream()
    assert parser.feed('{"nodes":[{"id":"title","kind":"heading","text":"Titolo"') is None
    draft = parser.feed(',"parent":"root"')
    assert draft["nodes"][0]["id"] == "title"
    no_parent = PageStream()
    assert no_parent.feed('{"nodes":[{"id":"p","parent":"missing","kind":"text","text":"Testo') is None


def test_optional_containers_wait_until_complete_and_group_parents_stay_valid():
    parser = PageStream()
    parser.feed('{"nodes":[{"id":"group","parent":"root","kind":"group"},'
                '{"id":"p","parent":"group","kind":"text","text":"Primo","style":{"font_size":')
    draft = parser.last_draft
    assert draft["nodes"][-1]["text"] == "Primo"
    assert draft["nodes"][-1]["style"]["font_size"] == 24
    assert parser.feed('3') is None
    complete_style = parser.feed('0}')
    assert complete_style["nodes"][-1]["style"]["font_size"] == 30
    assert PageSpec.model_validate(complete_style).nodes[-1].parent == "group"


def test_complete_invalid_nodes_remain_strict_and_size_is_bounded():
    parser = PageStream()
    assert parser.feed('{"nodes":[{"id":"bad","parent":"root","kind":"script","text":"a') is None
    with pytest.raises(ValueError):
        parser.feed('"}]}')
    with pytest.raises(ValueError, match="troppo grande"):
        PageStream().feed(" " * 400001)


def test_scanning_can_advance_without_rebuilding_previews(monkeypatch):
    parser = PageStream()
    calls = []
    snapshot = parser.snapshot
    monkeypatch.setattr(parser, "snapshot", lambda: calls.append(True) or snapshot())
    text = PREFIX + "x" * 12000
    for char in text:
        assert parser.feed(char, emit=False) is None
    assert not calls
    assert len(parser.snapshot()["nodes"][0]["text"]) == 12000
    assert len(calls) == 1 and parser.characters == len(text)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_worker_throttles_writes_flushes_before_media_and_preserves_diagnostics(tmp_path, monkeypatch, cancel):
    store = Store(tmp_path / "isolated")
    project = store.create(ProjectInput(engine="v2", count=1).model_dump())
    pid = project["id"]
    store.save_job({"id": "job", "status": "running", "events": []})
    clock = [10.0]
    monkeypatch.setattr("h3_slides.worker_v2.time", SimpleNamespace(monotonic=lambda: clock[0]))
    saved = []
    original_save = store.save_project
    def save(value, notify=True):
        if value["slides"]:
            saved.append((clock[0], copy.deepcopy(value["slides"][0])))
        return original_save(value, notify=notify)
    monkeypatch.setattr(store, "save_project", save)
    data = {"nodes": [{"id": "title", "parent": "root", "kind": "heading", "text": "Inizio della pagina"}]}
    text = json.dumps(data)
    marker = text.index("Inizio")
    class Client:
        async def json(self, prompt, schema=None, **kwargs):
            if "on_text" not in kwargs:
                return {"slides": [{"title": "Titolo", "purpose": "Spiegazione"}]}
            callback = kwargs["on_text"]
            await callback(text[:marker] + "I")
            assert store.project(pid)["slides"][0]["page_draft"]["nodes"][0]["text"] == "I"
            for char in "nizio":
                clock[0] += .01
                await callback(char)
            assert store.project(pid)["slides"][0]["page_draft"]["nodes"][0]["text"] == "I"
            clock[0] += .25
            await callback(" ")
            assert store.project(pid)["slides"][0]["page_draft"]["nodes"][0]["text"] == "Inizio "
            if cancel:
                raise asyncio.CancelledError()
            await callback(text[marker + len("Inizio "):])
            return data
    media_observed = []
    async def media(*args):
        slide = store.project(pid)["slides"][0]
        assert slide["page_stream"]["phase"] == "media"
        assert slide["page_stream"]["characters"] == len(text)
        assert slide["page_draft"]["nodes"][0]["text"] == "Inizio della pagina"
        media_observed.append(True)
    monkeypatch.setattr("h3_slides.worker_v2.resolve_media", media)
    request = Generation(provider=Provider(), prompt="Spiega", count=1)
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await run_pages(Worker(store, SimpleNamespace()), Client(), "job", pid, request, "", [])
    else:
        await run_pages(Worker(store, SimpleNamespace()), Client(), "job", pid, request, "", [])
    states = [slide.get("page_stream", {}).get("phase") for _, slide in saved]
    assert "waiting" in states and "writing" in states
    writing = [(at, slide) for at, slide in saved if slide.get("page_stream", {}).get("phase") == "writing"]
    active_writing = [(at, slide) for at, slide in writing if slide["status"] == "generating"]
    assert len(active_writing) == 2
    assert active_writing[1][0] - active_writing[0][0] >= .25
    final = store.project(pid)["slides"][0]
    if cancel:
        assert final["status"] == "failed" and final["page_stream"]["phase"] == "writing"
        assert final["page_draft"]["nodes"][0]["text"] == "Inizio "
        assert not media_observed
    else:
        assert final["status"] == "ready" and "page_stream" not in final
        assert media_observed == [True]
    messages = [event["message"] for event in store.job("job")["events"]]
    assert sum("primi caratteri" in message for message in messages) == 1
    assert sum("prima bozza" in message for message in messages) == 1
