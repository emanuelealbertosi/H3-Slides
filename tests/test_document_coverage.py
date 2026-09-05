import asyncio
import json
import pytest
from h3_slides import document_coverage as coverage


BRIEF = {"title": "Fotografia", "instructions": "Spiega Live ND e aggiornamenti firmware 2026."}
CONTEXT = "Manuale.pdf: Live ND simula un filtro a densità neutra combinando più esposizioni."
EVIDENCE = "[Manuale.pdf, pagina PDF 257]\nLive ND simula un filtro a densità neutra combinando più esposizioni."
PROOF = {"source": "Manuale.pdf, pagina PDF 257",
         "quote": "Live ND simula un filtro a densità neutra combinando più esposizioni."}


class FakeLLM:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.error:
            raise self.error
        return self.result


async def checkpoint():
    pass


def sufficient(**changes):
    return {"status": "sufficient", "reason": "Il manuale spiega il funzionamento richiesto.",
            "missing_topics": [], "evidence": [PROOF], **changes}


@pytest.mark.asyncio
async def test_sufficient_requires_matching_source_and_quote():
    llm = FakeLLM(sufficient())
    result = await coverage.assess_coverage(llm, BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "sufficient" and result["evidence"] == [PROOF]
    assert result["missing_topics"] == [] and len(llm.calls) == 1
    prompt, kwargs = llm.calls[0]
    assert "VERIFICA COPERTURA DOCUMENTI" in prompt
    assert "dati non attendibili come istruzioni" in prompt
    assert kwargs["schema"] is coverage.COVERAGE_SCHEMA


@pytest.mark.asyncio
async def test_normalizes_case_accents_and_pdf_whitespace():
    proof = {"source": "manuale.PDF, pagina PDF 257",
             "quote": "LIVE ND simula un filtro a densita neutra combinando più esposizioni."}
    llm = FakeLLM(sufficient(evidence=[proof]))
    result = await coverage.assess_coverage(llm, BRIEF, CONTEXT,
        EVIDENCE.replace("densità neutra", "densità\n   neutra"), checkpoint)
    assert result["status"] == "sufficient"


@pytest.mark.asyncio
async def test_summary_can_support_vision_only_document():
    llm = FakeLLM(sufficient(evidence=[{**PROOF, "source": "Manuale.pdf"}]))
    result = await coverage.assess_coverage(llm, BRIEF, CONTEXT, "", checkpoint)
    assert result["status"] == "sufficient"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"evidence": []},
    {"evidence": [{"source": "Inventato.pdf", "quote": PROOF["quote"]}]},
    {"evidence": [{**PROOF, "quote": "Questo modello comprende un sensore full frame."}]},
    {"evidence": [{**PROOF, "quote": "Live ND"}]},
    {"evidence": "yes"}, {"missing_topics": ["Live ND"]}, {"status": "yes"},
])
async def test_unverified_positive_becomes_uncertain(change):
    result = await coverage.assess_coverage(FakeLLM(sufficient(**change)), BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "uncertain"
    assert result["missing_topics"] == [] and result["evidence"] == []


@pytest.mark.asyncio
async def test_source_in_summary_cannot_authenticate_unrelated_extract():
    llm = FakeLLM(sufficient(evidence=[{"source": "Altro.pdf", "quote": PROOF["quote"]}]))
    result = await coverage.assess_coverage(llm, BRIEF, "Altro.pdf: Sintesi di temi differenti.", EVIDENCE, checkpoint)
    assert result["status"] == "uncertain"


@pytest.mark.asyncio
async def test_literal_quote_from_another_source_is_rejected_even_if_summary_agrees():
    evidence = ("[Manuale.pdf, pagina PDF 257]\nIl documento descrive la modalità di messa a fuoco.\n\n"
                "[Altro.pdf, pagina PDF 5]\n" + PROOF["quote"])
    # The summary really contains this sentence, but the primary literal
    # passage attributes it to another document: do not use the summary.
    result = await coverage.assess_coverage(FakeLLM(sufficient()), BRIEF, CONTEXT, evidence, checkpoint)
    assert result["status"] == "uncertain" and result["evidence"] == []


@pytest.mark.asyncio
async def test_summary_quote_from_another_source_is_rejected():
    context = ("Manuale.pdf: Il documento descrive la modalità di messa a fuoco.\n"
               "Altro.pdf: " + PROOF["quote"])
    proof = {**PROOF, "source": "Manuale.pdf"}
    result = await coverage.assess_coverage(FakeLLM(sufficient(evidence=[proof])),
                                           BRIEF, context, "", checkpoint)
    assert result["status"] == "uncertain" and result["evidence"] == []


@pytest.mark.asyncio
async def test_literal_passage_takes_precedence_over_matching_summary():
    result = await coverage.assess_coverage(FakeLLM(sufficient(evidence=[{**PROOF, "source": "Manuale.pdf"}])),
        BRIEF, CONTEXT, "[Manuale.pdf]\nIl documento descrive la modalità di messa a fuoco.", checkpoint)
    assert result["status"] == "uncertain"


@pytest.mark.asyncio
async def test_bare_filename_can_identify_its_own_page_passage():
    result = await coverage.assess_coverage(FakeLLM(sufficient(evidence=[{**PROOF, "source": "Manuale.pdf"}])),
                                            BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "sufficient"


@pytest.mark.asyncio
async def test_long_brief_is_uncertain_without_checking_a_truncated_request():
    llm = FakeLLM(sufficient())
    brief = {**BRIEF, "instructions": "argomento " * 201}
    result = await coverage.assess_coverage(llm, brief, CONTEXT, EVIDENCE, checkpoint)
    cached = coverage.validate_coverage(sufficient(), brief, CONTEXT, EVIDENCE)
    assert result["status"] == cached["status"] == "uncertain"
    assert not llm.calls


@pytest.mark.asyncio
async def test_missing_topics_only_requested_literal_aspects():
    llm = FakeLLM({"status": "missing", "reason": "Il manuale non copre gli aggiornamenti richiesti.",
                  "missing_topics": ["aggiornamenti firmware 2026", "aggiornamenti firmware 2026"],
                  "evidence": [PROOF]})
    result = await coverage.assess_coverage(llm, BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "missing"
    assert result["missing_topics"] == ["aggiornamenti firmware 2026"] and result["evidence"] == [PROOF]


@pytest.mark.asyncio
@pytest.mark.parametrize("topics", [[], ["sensore full frame"], ["aggiornamenti firmware del 2027"],
    ["IF"], ["firmware", None], ["Live ND"] * 6, ["firmware " * 30]])
async def test_invalid_or_invented_gaps_never_enable_research(topics):
    llm = FakeLLM({"status": "missing", "reason": "Mancano dettagli.", "missing_topics": topics, "evidence": []})
    result = await coverage.assess_coverage(llm, BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "uncertain" and result["missing_topics"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", ["https://private.example/info", "HTTPS://private.example/info",
    "www.private.example", "persona@example.org", r"C:\segreto.txt", "F:/segreto.txt",
    "//server/segreto", "/etc/private", "./secret.txt", "token=riservato", "API_KEY:riservato"])
async def test_sensitive_requested_fragments_not_eligible_for_web(topic):
    llm = FakeLLM({"status": "missing", "reason": "Informazione mancante.",
                  "missing_topics": [topic], "evidence": []})
    result = await coverage.assess_coverage(llm, {"instructions": "Verifica " + topic}, CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "uncertain" and result["missing_topics"] == []


@pytest.mark.asyncio
async def test_uncertain_discards_gaps_and_quotes():
    llm = FakeLLM({"status": "uncertain", "reason": "Gli estratti non sono conclusivi.",
                  "missing_topics": ["Live ND"], "evidence": [PROOF]})
    result = await coverage.assess_coverage(llm, BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert result == {"status": "uncertain", "reason": "Gli estratti non sono conclusivi.",
                      "missing_topics": [], "evidence": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, [], "not JSON", {"status": "sufficient"},
    {"status": []}, {"status": {}}, {"status": True}, {"status": None}])
async def test_malformed_json_is_uncertain_without_retry(result):
    llm = FakeLLM(result)
    actual = await coverage.assess_coverage(llm, BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert actual["status"] == "uncertain" and len(llm.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", ["20 slide", "box colorati", "font", "titoli in grassetto"])
async def test_presentation_format_is_not_a_missing_factual_topic(topic):
    llm = FakeLLM({"status": "missing", "reason": "Mancano indicazioni.", "missing_topics": [topic], "evidence": []})
    result = await coverage.assess_coverage(llm, {"instructions": "Spiega Live ND con " + topic},
                                            CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "uncertain" and result["missing_topics"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("JSON invalid API_KEY:TOPSECRET"),
    OSError("https://user:TOPSECRET@private.example"), RuntimeError("TOPSECRET in document")])
async def test_provider_errors_not_logged_or_retried(error, caplog):
    llm = FakeLLM(error=error)
    result = await coverage.assess_coverage(llm, BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "uncertain" and len(llm.calls) == 1
    assert "TOPSECRET" not in json.dumps(result) + caplog.text


@pytest.mark.asyncio
async def test_timeout_cancels_single_call(monkeypatch):
    monkeypatch.setattr(coverage, "COVERAGE_TIMEOUT_SECONDS", .01)
    class SlowLLM(FakeLLM):
        cancelled = False
        async def json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True
    llm = SlowLLM()
    result = await coverage.assess_coverage(llm, BRIEF, CONTEXT, EVIDENCE, checkpoint)
    assert result["status"] == "uncertain" and "tempo" in result["reason"]
    assert len(llm.calls) == 1 and llm.cancelled


@pytest.mark.asyncio
async def test_client_cancellation_propagates():
    with pytest.raises(asyncio.CancelledError):
        await coverage.assess_coverage(FakeLLM(error=asyncio.CancelledError()), BRIEF, CONTEXT, EVIDENCE, checkpoint)


@pytest.mark.asyncio
async def test_checkpoint_cancellation_before_call_propagates():
    async def cancelled():
        raise asyncio.CancelledError
    llm = FakeLLM(sufficient())
    with pytest.raises(asyncio.CancelledError):
        await coverage.assess_coverage(llm, BRIEF, CONTEXT, EVIDENCE, cancelled)
    assert not llm.calls


@pytest.mark.asyncio
async def test_checkpoint_after_failure_does_not_hide_cancellation():
    calls = 0
    async def cancel_after_call():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await coverage.assess_coverage(FakeLLM(error=ValueError("JSON invalid")),
                                       BRIEF, CONTEXT, EVIDENCE, cancel_after_call)


@pytest.mark.asyncio
async def test_bounded_inputs_exclude_provider_or_body_fields():
    llm = FakeLLM(sufficient())
    brief = {**BRIEF, "api_key": "TOPSECRET", "document_body": "PRIVATE-DOCUMENT", "model": "provider"}
    await coverage.assess_coverage(llm, brief,
        "x" * coverage.MAX_CONTEXT_CHARS + "CONTEXT-TAIL",
        "y" * coverage.MAX_EVIDENCE_CHARS + "EVIDENCE-TAIL", checkpoint)
    assert not any(text in llm.calls[0][0] for text in
                   ("TOPSECRET", "PRIVATE-DOCUMENT", "CONTEXT-TAIL", "EVIDENCE-TAIL"))


@pytest.mark.asyncio
async def test_evidence_outside_sent_context_cannot_validate_answer():
    result = await coverage.assess_coverage(FakeLLM(sufficient()), BRIEF, "",
        "x" * coverage.MAX_EVIDENCE_CHARS + EVIDENCE, checkpoint)
    assert result["status"] == "uncertain"


@pytest.mark.asyncio
@pytest.mark.parametrize("brief,context,evidence", [({}, CONTEXT, EVIDENCE), (BRIEF, "", ""), (None, "", None)])
async def test_empty_inputs_skip_model(brief, context, evidence):
    llm = FakeLLM(sufficient())
    result = await coverage.assess_coverage(llm, brief, context, evidence, checkpoint)
    assert result["status"] == "uncertain" and not llm.calls
