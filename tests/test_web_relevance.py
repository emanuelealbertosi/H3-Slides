"""Offline regressions for broad-topic discovery and complete source retrieval."""
import hashlib
import json
import time

import pytest

from h3_slides import web_research as wr


@pytest.mark.parametrize("query, expected", [
    ("rivoluzione francese cause ed esiti", "rivoluzione francese"),
    ("Rivoluzione francese e le conseguenze", "Rivoluzione francese"),
    ("French Revolution causes and consequences", "French Revolution"),
    ("OM-5 Mark II funzioni computazionali", "OM-5 Mark II"),
    ("OM System OM-5 Mark II caratteristiche", "OM System OM-5 Mark II"),
    ("reti neurali vantaggi e svantaggi", "reti neurali"),
    ("Rivoluzione francese", None),
    ("Python funzioni", None),
    ("funzioni computazionali OM-5 Mark II", None),
    ("storia delle cause della rivoluzione francese", None),
    ('"Rivoluzione francese" cause', None),
    ("intitle:Rivoluzione francese cause", None),
])
def test_queries_preserve_original_subject_and_identifiers(query, expected):
    assert wr.wikipedia_queries(query) == [query] + ([expected] if expected else [])


@pytest.mark.asyncio
async def test_main_topic_is_read_before_incidental_biographies(monkeypatch):
    calls = []
    original = "rivoluzione francese cause ed esiti"
    async def api(_session, language, **params):
        calls.append((language, params["srsearch"]))
        assert params["srprop"] == "snippet"
        if params["srsearch"] == original:
            titles = ["Moti del 1848", "Edmund Burke", "Storiografia", "Benito Mussolini", "Iosif Stalin"]
            results = [{"pageid": i + 1, "title": title, "snippet": "Una menzione della rivoluzione francese."}
                       for i, title in enumerate(titles)]
        else:
            titles = ["Rivoluzione francese", "Cause della Rivoluzione francese", "Terrore (rivoluzione francese)"]
            results = [{"pageid": i + 20, "title": title} for i, title in enumerate(titles)]
            results.append({"pageid": 2, "title": "Edmund Burke"})
        return {"query": {"search": results}}
    monkeypatch.setattr(wr, "wikipedia_api", api)
    results = await wr.WebResearch(None).search(None, original, "wikipedia", "")
    assert calls == [("it", original), ("it", "rivoluzione francese")]
    assert results[0]["title"] == "Rivoluzione francese"
    assert [r["title"] for r in results] == ["Rivoluzione francese", "Cause della Rivoluzione francese"]
    assert len({r["wiki_page_id"] for r in results}) == 2


def test_recovered_subject_does_not_fill_quota_with_homonyms_or_incidental_mentions():
    titles = ["Rivoluzione francese", "La rivoluzione francese", "Rivoluzione francese del 1848",
              "Rivoluzione haitiana", "Rivoluzione", "Regime del Terrore", "Edmund Burke"]
    results = [{"title": title, "search_snippet": "Un riferimento alla rivoluzione francese"} for title in titles]
    selected = wr.focused_wikipedia_results(results, "rivoluzione francese cause ed esiti")
    assert [r["title"] for r in selected] == ["Rivoluzione francese"]


def test_no_subject_guess_when_there_is_no_exact_article():
    results = [{"title": "OM-5"}, {"title": "OM-5 Mark II funzioni computazionali"}]
    selected = wr.focused_wikipedia_results(results, "OM-5 Mark II funzioni computazionali")
    assert len(selected) == 2
    assert selected[0]["title"] == "OM-5 Mark II funzioni computazionali"


def test_title_matching_is_accent_case_and_punctuation_aware():
    query = "città etrusche caratteristiche"
    exact = {"title": "Città etrusche"}
    related = {"title": "Storia delle città etrusche"}
    incidental = {"title": "Roma", "search_snippet": "Studi sulle città etrusche"}
    wrong = {"title": "Città"}
    assert wr.wikipedia_relevance(exact, query) > wr.wikipedia_relevance(related, query)
    assert wr.wikipedia_relevance(related, query) > wr.wikipedia_relevance(incidental, query)
    assert wr.wikipedia_relevance(incidental, query) > wr.wikipedia_relevance(wrong, query)


@pytest.mark.asyncio
async def test_denial_is_not_bypassed_by_a_different_query(monkeypatch):
    calls = []
    async def api(_session, language, **params):
        calls.append(params["srsearch"])
        raise ValueError("Wikipedia HTTP 429")
    monkeypatch.setattr(wr, "wikipedia_api", api)
    with pytest.raises(ValueError, match="429"):
        await wr.WebResearch(None).search(None, "rivoluzione francese cause", "wikipedia", "")
    assert calls == ["rivoluzione francese cause"]


@pytest.mark.asyncio
async def test_english_extension_keeps_distinct_language_page_ids(monkeypatch):
    calls = []
    async def api(_session, language, **params):
        calls.append((language, params["srsearch"]))
        return {"query": {"search": [{"pageid": 7, "title": "Neural networks"}]}}
    monkeypatch.setattr(wr, "wikipedia_api", api)
    result = await wr.WebResearch(None).search(None, "Neural networks", "wikipedia", "")
    assert len(calls) == 2
    assert [(r["wiki_language"], r["wiki_page_id"]) for r in result] == [("it", 7), ("en", 7)]


@pytest.mark.asyncio
async def test_found_core_article_does_not_search_english_just_to_fill_quota(monkeypatch):
    calls = []
    async def api(_session, language, **params):
        calls.append((language, params["srsearch"]))
        return {"query": {"search": [] if params["srsearch"].endswith("cause") else
            [{"pageid": 7, "title": "Rivoluzione francese"}]}}
    monkeypatch.setattr(wr, "wikipedia_api", api)
    result = await wr.WebResearch(None).search(None, "rivoluzione francese cause", "wikipedia", "")
    assert calls == [("it", "rivoluzione francese cause"), ("it", "rivoluzione francese")]
    assert len(result) == 1


@pytest.mark.asyncio
async def test_late_wikipedia_section_is_available_to_slide_evidence(monkeypatch):
    late = "Il Terrore fu una fase della Rivoluzione francese associata al Comitato di salute pubblica."
    text = "Introduzione e contesto storico. " * 1400 + "\n\n" + late + "\n" * 10
    assert text.index(late) > 24000
    async def api(*_args, **_kwargs):
        return {"query": {"pages": {"12": {"title": "Rivoluzione francese", "extract": text,
            "fullurl": "https://it.wikipedia.org/wiki/Rivoluzione_francese"}}}}
    monkeypatch.setattr(wr, "wikipedia_api", api)
    result = await wr.read_wikipedia(None, {"wiki_language": "it", "wiki_page_id": 12,
        "title": "Rivoluzione francese", "url": "https://it.wikipedia.org/?curid=12"})
    assert result["text"] == text and result["truncated"] is False
    bundle = {"query": "rivoluzione francese", "sources": [{**result, "id": "W1"}]}
    evidence = wr.web_evidence(bundle, "Terrore Comitato salute pubblica")
    assert late in evidence and len(evidence) <= 5000
    assert "text" not in wr.public_research(bundle)["sources"][0]


@pytest.mark.asyncio
async def test_exceptionally_long_wikipedia_page_remains_bounded(monkeypatch):
    async def api(*_args, **_kwargs):
        return {"query": {"pages": {"12": {"extract": "Informazione. " * 30000}}}}
    monkeypatch.setattr(wr, "wikipedia_api", api)
    result = await wr.read_wikipedia(None, {"wiki_language": "it", "wiki_page_id": 12,
        "title": "Voce", "url": "https://it.wikipedia.org/?curid=12"})
    assert len(result["text"]) == wr.MAX_SOURCE_CHARS == 240000
    assert result["truncated"] is True and wr.MAX_PAGE_BYTES == 2000000


@pytest.mark.asyncio
async def test_direct_web_also_preserves_late_sections(monkeypatch):
    text = "Contesto generale. " * 2000 + "\nUn capitolo finale importante."
    async def get(*_args, **_kwargs):
        return 200, "text/plain", text, "https://example.com/document"
    monkeypatch.setattr(wr, "bounded_get", get)
    result = await wr.read_page(None, {"title": "Documento", "url": "https://example.com/document"})
    assert result["text"] == text and result["truncated"] is False


@pytest.mark.asyncio
async def test_old_cache_does_not_reuse_bad_search_order(tmp_path, monkeypatch):
    query, pid = "rivoluzione francese cause ed esiti", "fixture"
    class AssetStore:
        def asset_path(self, project, filename):
            assert project == pid
            return tmp_path / filename
    old_key = hashlib.sha256(json.dumps(["web-v2", "wikipedia", "", query, 3]).encode()).hexdigest()
    old = {"created_at": time.time(), "sources": [{"title": "Stale unrelated article"}]}
    (tmp_path / ("web-" + old_key + ".json")).write_text(json.dumps(old), encoding="utf-8")
    calls = []
    async def search(*_args):
        calls.append(1)
        return [{"title": "Rivoluzione francese", "url": "https://it.wikipedia.org/?curid=12"}]
    async def read(_session, candidate):
        return {**candidate, "text": "Fonte pertinente. " * 30, "retrieved_at": time.time(), "truncated": True}
    async def checkpoint():
        pass
    researcher = wr.WebResearch(AssetStore())
    monkeypatch.setattr(researcher, "search", search)
    monkeypatch.setattr(wr, "read_wikipedia", read)
    events = []
    args = (pid, query, 3, False, events.append, checkpoint)
    result = await researcher.collect(*args)
    assert calls == [1] and result["sources"][0]["title"] == "Rivoluzione francese"
    assert not result["cache_used"] and wr.CACHE_VERSION != "web-v2"
    assert any("sezioni finali" in warning for warning in result["warnings"])
    assert any("risultati marginali" in warning for warning in result["warnings"])
    assert any("ricerca anche della voce principale: rivoluzione francese" in event for event in events)
    second = await researcher.collect(*args)
    assert second["cache_used"] and calls == [1]
