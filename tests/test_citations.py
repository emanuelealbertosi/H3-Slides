import copy

import pytest

from h3_slides.citations import SourceCitationError, resolve_web_source


@pytest.fixture
def research():
    return {"sources": [
        {"id": "W1", "title": "Python tutorial", "url": "https://docs.python.org/3/tutorial/",
         "retrieved_at": 1},
        {"id": "W2", "title": "Funzioni computazionali OM-5", "url": "https://example.org/om-5",
         "retrieved_at": 2},
    ]}


@pytest.mark.parametrize("ref", [
    "W1", "[W1]", "  [W1]  ", "https://docs.python.org/3/tutorial/",
    "W1 · Python tutorial", "[W1] · Python tutorial", "W1 — Python tutorial",
    "W1 · Python\n tutorial",
    "Python tutorial — https://docs.python.org/3/tutorial/ (consultato 2026-09-05)",
    "Python tutorial — https://docs.python.org/3/tutorial/ (consultato 2020-02-29)",
    "[Python tutorial](https://docs.python.org/3/tutorial/)",
    "[Python tutorial](<https://docs.python.org/3/tutorial/>)",
    "[W1](https://docs.python.org/3/tutorial/)",
    "[W1 · Python tutorial](https://docs.python.org/3/tutorial/)",
    "[https://docs.python.org/3/tutorial/](https://docs.python.org/3/tutorial/)",
    "[Python tutorial](https://docs.python.org/3/tutorial/) (consultato 2026-09-05)",
    "[Python tutorial — https://docs.python.org/3/tutorial/ (consultato 2026-09-05)]"
    "(https://docs.python.org/3/tutorial/)",
])
def test_known_complete_forms_resolve_same_acquired_object(research, ref):
    assert resolve_web_source(ref, research) is research["sources"][0]


@pytest.mark.parametrize("ref", [
    "", "W9", "[[W1]]", "W1]", "[W1", "W01", "w1", "Python tutorial",
    "Secondo W1 la fotocamera fa tutto", "Fonte [W1]", "W1, W2",
    "W1 · Titolo inventato", "W1 · Python tutorial, fatti non verificati",
    "https://unknown.example/", "https://docs.python.org/3/tutorial/#invented",
    "https://docs.python.org/3/tutorial/?unknown=1", "https://docs.python.org/3/tutorial",
    "Python tutorial — https://unknown.example/ (consultato 2026-09-05)",
    "Titolo inventato — https://docs.python.org/3/tutorial/ (consultato 2026-09-05)",
    "Python tutorial — https://docs.python.org/3/tutorial/ (consultato 2026-02-30)",
    "Python tutorial — https://docs.python.org/3/tutorial/ (consultato ieri)",
    "[Python tutorial](https://unknown.example/)",
    "[Titolo inventato](https://docs.python.org/3/tutorial/)",
    "[W1 · Titolo inventato](https://docs.python.org/3/tutorial/)",
    "[W1](https://docs.python.org/3/tutorial/) e altre fonti",
    "Guarda [W1](https://docs.python.org/3/tutorial/)",
    "[W1](https://docs.python.org/3/tutorial/) (consultato 2026-02-30)",
    "[W1](https://docs.python.org/3/tutorial/ \"Titolo\")",
    "[W1](https://docs.python.org/3/tutorial/)\nhttps://unknown.example/",
    "W1 · Python tutorial — https://unknown.example/",
    None, 1, [], {},
])
def test_unknown_partial_or_mismatched_references_are_not_evidence(research, ref):
    assert resolve_web_source(ref, research) is None


def test_formatted_historical_id_resolves_by_unique_title_not_new_id(research):
    assert resolve_web_source("W1 · Funzioni computazionali OM-5", research) is research["sources"][1]
    assert resolve_web_source("W9 · Funzioni computazionali OM-5", research) is research["sources"][1]
    assert resolve_web_source("[W9 · Funzioni computazionali OM-5](https://example.org/om-5)",
                              research) is research["sources"][1]
    assert resolve_web_source("[W1](https://example.org/om-5)", research) is research["sources"][1]


def test_ambiguous_title_needs_matching_id_or_explicit_url(research):
    duplicate = {**research["sources"][0], "id": "W3", "url": "https://example.org/other"}
    research["sources"].append(duplicate)
    assert resolve_web_source("W9 · Python tutorial", research) is None
    assert resolve_web_source("W1 · Python tutorial", research) is research["sources"][0]
    assert resolve_web_source("W3 · Python tutorial", research) is duplicate
    assert resolve_web_source("[Python tutorial](https://example.org/other)", research) is duplicate


def test_duplicate_ids_and_urls_are_not_resolved_arbitrarily(research):
    research["sources"].append(dict(research["sources"][0]))
    assert resolve_web_source("W1", research) is None
    assert resolve_web_source("https://docs.python.org/3/tutorial/", research) is None


def test_url_parentheses_are_preserved_without_normalizing_or_following_links():
    source = {"id": "W1", "title": "Funzione (matematica)",
              "url": "https://it.wikipedia.org/wiki/Funzione_(matematica)"}
    research = {"sources": [source]}
    ref = "[Funzione (matematica)](https://it.wikipedia.org/wiki/Funzione_(matematica))"
    assert resolve_web_source(ref, research) is source


@pytest.mark.parametrize("data", [None, [], {}, {"sources": None}, {"sources": [None, {}, 1]}])
def test_missing_or_invalid_research_never_selects_a_source(data):
    assert resolve_web_source("W1", data) is None


def test_normalization_is_read_only_and_error_remains_value_error_compatible(research):
    before = copy.deepcopy(research)
    resolve_web_source("W1 · Python tutorial", research)
    assert research == before
    assert isinstance(SourceCitationError("Fonti mancanti"), ValueError)


@pytest.mark.parametrize("historical_id", ["W1", "W9"])
def test_worker_long_title_label_roundtrip_and_safe_id_remapping(research, historical_id):
    source = research["sources"][1]
    source["title"] = "Funzioni computazionali e uso della fotocamera OM-5: " + "dettaglio " * 15
    assert len(source["title"]) > 170
    # Keep this construction identical to the worker's display source label.
    worker_label = source["id"] + " · " + source["title"][:170]
    assert resolve_web_source(worker_label, research) is source
    historical_label = historical_id + " · " + source["title"][:170]
    assert resolve_web_source(historical_label, research) is source
    assert resolve_web_source("[" + historical_label + "](" + source["url"] + ")", research) is source


@pytest.mark.parametrize("length", [1, 100, 169, 171, 180])
def test_long_title_does_not_allow_arbitrary_prefixes(research, length):
    source = research["sources"][0]
    source["title"] = "Titolo di una fonte " + "matematica " * 20
    assert resolve_web_source("W1 · " + source["title"][:length], research) is None


def test_truncated_title_collision_rejected_even_with_apparent_matching_id(research):
    prefix = "x" * 170
    research["sources"][0]["title"] = prefix + " fonte prima"
    research["sources"][1]["title"] = prefix + " fonte seconda"
    for source_id in ("W1", "W2", "W9"):
        assert resolve_web_source(source_id + " · " + prefix, research) is None
    # Complete titles still distinguish the acquired sources.
    assert resolve_web_source("W1 · " + prefix + " fonte prima", research) is research["sources"][0]


def test_truncated_title_collision_with_short_complete_title_is_not_remapped(research):
    prefix = "x" * 170
    research["sources"][0]["title"] = prefix
    research["sources"][1]["title"] = prefix + " parte distintiva"
    assert resolve_web_source("W1 · " + prefix, research) is None
    assert resolve_web_source("W2 · " + prefix, research) is None
    assert resolve_web_source("W9 · " + prefix, research) is None


def test_only_worker_label_not_canonical_citation_can_use_title_abbreviation(research):
    source = research["sources"][0]
    source["title"] = "x" * 190
    ref = source["title"][:170] + " — " + source["url"] + " (consultato 2026-09-05)"
    assert resolve_web_source(ref, research) is None
