import io
import json
from types import SimpleNamespace
import pymupdf as fitz
import pytest
from h3_slides.ingest import ingest
from h3_slides.models import ProjectInput
from h3_slides.storage import Store
from h3_slides.retrieval import resolve_section, select_pages, prepare_pdf, rank_evidence


def test_literal_retrieval_preserves_specific_page_and_code():
    records = [
        {"label": "Libro p. 2", "text": "Linguaggi compilati, sorgente e macchina."},
        {"label": "Libro p. 10", "text": "Importazione di moduli: import math; print(math.sqrt(25))."},
        {"label": "Libro p. 9", "text": "Debug, breakpoint, esecuzione passo passo."},
    ]
    found = rank_evidence(records, "Debug e breakpoint")
    assert found.startswith("[Libro p. 9]")
    assert "Libro p. 10" not in found
    assert "math.sqrt(25)" in rank_evidence(records, "Importazione math")


def pages(offset=20):
    return [{"pdf_page": n, "printed_page": n-offset if n > offset else None,
             "text": ("Il linguaggio Python\n" if n == offset+2 else
                      "La sintassi di Python e le variabili\n" if n == offset+16 else "") +
                     "Contenuto leggibile della pagina. " * 4} for n in range(1, offset+30)]


def plan():
    return {"scope": "section", "title": "Il linguaggio Python", "printed_start": 2,
            "printed_end": 15, "next_title": "La sintassi di Python e le variabili",
            "evidence": "Unità 1, L1 p.2; L2 p.16"}


def test_numbering_offset_is_not_hardcoded():
    assert resolve_section(pages(20), plan()) == (22, 35)
    assert resolve_section(pages(7), plan()) == (9, 22)


def test_wrong_title_or_end_is_rejected():
    with pytest.raises(ValueError):
        resolve_section(pages(), {**plan(), "title": "Lezione inesistente"})
    with pytest.raises(ValueError):
        resolve_section(pages(), {**plan(), "printed_end": 14})


@pytest.mark.asyncio
async def test_model_finds_section_from_toc_and_brief():
    data = pages()
    data[8]["text"] = "Indice\nUNITÀ 1\nL1 Il linguaggio Python 2\nL2 La sintassi di Python e le variabili 16"
    prompts = []
    class Client:
        async def json(self, prompt, **kwargs):
            prompts.append(prompt)
            return plan()
    async def checkpoint():
        pass
    selected, details = await select_pages(Client(), {"name": "libro.pdf"}, {"pages": data},
                                          "20 slide della lezione 1 dell'UDA 1", lambda s: None, checkpoint)
    assert [p["pdf_page"] for p in selected] == list(range(22, 36))
    assert "UNITÀ 1" in prompts[0]
    assert details["index_pages"] == [9]


def test_large_pdf_is_indexed_without_rendering_all_pages(tmp_path):
    store = Store(tmp_path)
    project = store.create(ProjectInput().model_dump())
    doc = fitz.open()
    for n in range(80):
        page = doc.new_page()
        page.insert_text((40, 40), "Testo leggibile per pagina di prova " + str(n))
        page.insert_text((40, 810), str(n+1))
    source = ingest(store, project["id"], "libro.pdf", doc.tobytes())
    assert source["page_count"] == 80
    assert source["images"] == []
    index = json.loads(store.asset_path(project["id"], source["page_index_file"]).read_text(encoding="utf-8"))
    assert index["pages"][3]["printed_page"] == 4
    store.db.close()


@pytest.mark.asyncio
async def test_ambiguous_section_never_silently_uses_whole_book():
    data = pages()
    data[0]["text"] = "Indice\nAltra unità e altra lezione " * 3
    class Client:
        async def json(self, *_args, **kwargs):
            return {**plan(), "scope": "uncertain"}
    async def checkpoint():
        pass
    with pytest.raises(ValueError, match="non è stata identificata"):
        await select_pages(Client(), {}, {"pages": data}, "UDA 99", lambda s: None, checkpoint)


@pytest.mark.asyncio
async def test_whole_generic_report_needs_no_toc_or_model_navigation():
    data = [{"pdf_page":i+1, "printed_page":None,
             "text":"Risultati e attività del progetto. " * 3} for i in range(80)]
    class NoNavigation:
        async def json(self, *_args, **_kwargs):
            raise AssertionError("Documento intero non deve cercare sezioni")
    async def checkpoint():
        pass
    selected, details = await select_pages(NoNavigation(), {"name":"report.pdf"}, {"pages":data},
        "Presenta il report", lambda _:None, checkpoint, scope_mode="whole")
    assert len(selected) == 80
    assert details["title"] == "Documento completo"


@pytest.mark.asyncio
async def test_whole_pdf_does_not_bypass_large_scan_limit():
    data = [{"pdf_page":i+1, "printed_page":None, "text":""} for i in range(61)]
    async def checkpoint():
        pass
    with pytest.raises(ValueError, match="OCR"):
        await select_pages(None, {}, {"pages":data}, "Tutto", lambda _:None, checkpoint, scope_mode="whole")


@pytest.mark.asyncio
async def test_pdf_scope_change_invalidates_previous_selection(tmp_path):
    store = Store(tmp_path)
    try:
        p = store.create(ProjectInput().model_dump())
        with fitz.open() as doc:
            for label in ["Premessa", "Risultati"]:
                page = doc.new_page()
                page.insert_text((40,40), label + ": dettagli leggibili di un report non scolastico.")
            source = ingest(store, p["id"], "report.pdf", doc.tobytes())
        p["sources"] = [source]
        store.save_project(p)
        calls = []
        class Client:
            async def json(self, prompt, **_kwargs):
                calls.append(prompt)
                return {"start":1, "end":1, "title":"Premessa", "certain":True}
        async def checkpoint():
            pass
        for scope, expected in [("auto",[1]), ("whole",[1,2]), ("auto",[1])]:
            source = store.project(p["id"])["sources"][0]
            prepared = await prepare_pdf(store, p["id"], source, Client(), "Presenta il report",
                                         lambda _:None, checkpoint, scope_mode=scope)
            assert prepared["selection"]["pdf_pages"] == expected
        assert len(calls) == 2
    finally:
        store.db.close()
