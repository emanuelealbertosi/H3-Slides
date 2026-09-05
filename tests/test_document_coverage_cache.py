"""Worker cache tests: real temporary store and retrieval, no provider/network."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from h3_slides import worker as worker_module
from h3_slides.models import Generation, ProjectInput, Provider
from h3_slides.storage import Store, now, uid
from h3_slides.worker import Worker


TEXT = "Live ND simula un filtro a densità neutra combinando più esposizioni."
CONTEXT = "Manuale.pdf: " + TEXT
BRIEF = {"title": "Fotografia", "instructions": "Spiega Live ND e aggiornamenti firmware 2026."}
SUFFICIENT = {
    "status": "sufficient", "reason": "Il documento spiega le modalità richieste.",
    "missing_topics": [], "evidence": [{"source": "Manuale.pdf", "quote": TEXT}],
}
MISSING = {
    "status": "missing", "reason": "Gli aggiornamenti richiesti non sono documentati.",
    "missing_topics": ["aggiornamenti firmware 2026"],
    "evidence": [{"source": "Manuale.pdf", "quote": TEXT}],
}


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    store = Store(tmp_path)
    project = store.create(ProjectInput(title="Fotografia", prompt=BRIEF["instructions"]).model_dump())
    project["sources"] = [{"id": "document", "name": "Manuale.pdf", "kind": "md", "text": TEXT,
                           "images": [], "warnings": []}]
    store.save_project(project)
    job = store.save_job({"id": uid(), "project_id": project["id"], "status": "running",
                          "progress": 0, "events": [], "created_at": now()})
    provider = Provider(mode="remote", model="fixture-model", base_url="http://127.0.0.1:1234/v1")
    request = Generation(provider=provider, prompt=BRIEF["instructions"])
    client = SimpleNamespace(provider=provider, sampling={"temperature": .2, "max_tokens": 2048,
                                                          "timeout_seconds": 600})
    worker = Worker(store, None)
    calls = []
    state = {"result": copy.deepcopy(SUFFICIENT)}

    async def assess(client, brief, context, evidence, checkpoint):
        await checkpoint()
        calls.append({"brief": copy.deepcopy(brief), "context": context, "evidence": evidence})
        return copy.deepcopy(state["result"])

    monkeypatch.setattr(worker_module, "assess_coverage", assess)

    async def run(*, brief=None, context=CONTEXT):
        return await worker.assess_document_coverage(client, project, request, context,
                                                     job["id"], BRIEF if brief is None else brief)

    fixture = SimpleNamespace(store=store, project=project, job=job, request=request,
        client=client, worker=worker, calls=calls, state=state, run=run,
        caches=lambda: list((tmp_path / "assets" / project["id"]).glob("coverage-*.json")))
    yield fixture
    store.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [SUFFICIENT, MISSING])
async def test_reuses_same_brief_evidence_and_model(scenario, decision):
    scenario.state["result"] = decision
    first = await scenario.run()
    second = await scenario.run()
    assert first == second == decision
    assert len(scenario.calls) == 1 and len(scenario.caches()) == 1
    assert any("riuso della verifica" in event["message"]
               for event in scenario.store.job(scenario.job["id"])["events"])


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "brief", "context", "passages", "source_name", "model", "endpoint", "mode", "sampling",
])
async def test_changed_input_or_model_identity_invalidates(scenario, change):
    await scenario.run()
    kwargs = {}
    if change == "brief":
        kwargs["brief"] = {**BRIEF, "instructions": "Spiega Live ND e le modalità di esposizione."}
    elif change == "context":
        kwargs["context"] = CONTEXT + " La funzione ha limiti durante lo scatto."
    elif change == "passages":
        scenario.project["sources"][0]["text"] += " Live ND combina esposizioni più lunghe."
    elif change == "source_name":
        scenario.project["sources"][0]["name"] = "Manuale-revisionato.pdf"
    elif change == "model":
        scenario.client.provider.model = "another-fixture-model"
    elif change == "endpoint":
        scenario.client.provider.base_url = "http://127.0.0.1:5678/v1"
    elif change == "mode":
        scenario.client.provider.mode = "local"
    else:
        scenario.client.sampling["temperature"] = .7
    await scenario.run(**kwargs)
    assert len(scenario.calls) == 2


@pytest.mark.asyncio
async def test_timeout_change_alone_does_not_invalidate_verified_result(scenario):
    await scenario.run()
    scenario.client.sampling["timeout_seconds"] = 900
    await scenario.run()
    assert len(scenario.calls) == 1


@pytest.mark.asyncio
async def test_uncertain_decision_is_not_cached(scenario):
    scenario.state["result"] = {"status": "uncertain", "reason": "Verifica non conclusiva.",
                                "missing_topics": [], "evidence": []}
    for _ in range(2):
        result = await scenario.run()
        assert result["status"] == "uncertain"
    assert len(scenario.calls) == 2 and not scenario.caches()


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", [
    "{unclosed", "[]", "null", '{"status":"unknown"}',
    json.dumps({"status": "sufficient", "reason": "ok", "missing_topics": []}),
    json.dumps({**SUFFICIENT, "evidence": [{"source": "Inventato.pdf", "quote": TEXT}]}),
    json.dumps({**SUFFICIENT, "evidence": [{"source": "Manuale.pdf", "quote": "Citazione inventata assente dal documento."}]}),
    json.dumps({**MISSING, "missing_topics": ["argomento inventato"]}),
    json.dumps({**MISSING, "missing_topics": ["https://private.example/secrets"]}),
    json.dumps({"status": "uncertain", "reason": "non conclusivo", "missing_topics": [], "evidence": []}),
])
async def test_corrupt_or_unverified_cache_is_reassessed(scenario, broken):
    await scenario.run()
    path = scenario.caches()[0]
    path.write_text(broken, encoding="utf-8")
    result = await scenario.run()
    assert result == SUFFICIENT and len(scenario.calls) == 2
    assert json.loads(path.read_text(encoding="utf-8")) == SUFFICIENT


@pytest.mark.asyncio
async def test_cancelled_job_does_not_reuse_existing_cache(scenario):
    await scenario.run()
    job = scenario.store.job(scenario.job["id"])
    job["status"] = "cancelled"
    scenario.store.save_job(job)
    with pytest.raises(asyncio.CancelledError):
        await scenario.run()
    assert len(scenario.calls) == 1


@pytest.mark.asyncio
async def test_cancellation_during_assessment_propagates_without_cache(scenario, monkeypatch):
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError
    monkeypatch.setattr(worker_module, "assess_coverage", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await scenario.run()
    assert not scenario.caches()


@pytest.mark.asyncio
async def test_cancel_after_assessment_prevents_cache_write(scenario, monkeypatch):
    async def cancel_job(*args, **kwargs):
        job = scenario.store.job(scenario.job["id"])
        job["status"] = "cancelled"
        scenario.store.save_job(job)
        return copy.deepcopy(SUFFICIENT)
    monkeypatch.setattr(worker_module, "assess_coverage", cancel_job)
    with pytest.raises(asyncio.CancelledError):
        await scenario.run()
    assert not scenario.caches()


@pytest.mark.asyncio
async def test_cached_result_does_not_persist_raw_documents_or_provider_secrets(scenario):
    scenario.project["sources"][0]["text"] += " Live ND " + "PRIVATE-CONTENT-" * 30
    scenario.client.provider.api_key = "TOPSECRET-CREDENTIAL"
    await scenario.run()
    raw = scenario.caches()[0].read_text(encoding="utf-8")
    assert "PRIVATE-CONTENT-" not in raw and "TOPSECRET-CREDENTIAL" not in raw
    assert json.loads(raw) == SUFFICIENT
