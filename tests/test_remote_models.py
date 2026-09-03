import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
import pytest

from h3_slides.app import create_app, run_child
import h3_slides.app as application
from h3_slides.llm import LLM
from h3_slides.models import Provider
from h3_slides.remote_models import RemoteModelRequest, list_remote_models, normalize_catalog, remote_api_url
import h3_slides.remote_models as catalog

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


def fake_server(monkeypatch, status=200, payload=None, raw=None, exception=None):
    calls = []
    raw = raw if raw is not None else json.dumps(payload if payload is not None else {
        "data": [{"id": "chat-b"}, {"id": "chat-a", "name": "Chat A"}, {"id": "chat-b"}]
    }).encode()

    class Response:
        def __init__(self):
            self.status = status
            self.content = self

        async def __aenter__(self):
            if exception:
                raise exception
            return self

        async def __aexit__(self, *args):
            return False

        async def iter_chunked(self, size):
            for i in range(0, len(raw), size):
                yield raw[i:i + size]

    class Session:
        def __init__(self, **kwargs):
            calls.append({"session": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def get(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return Response()

    # Patch only the catalog module's aiohttp binding, not aiohttp's TestClient.
    monkeypatch.setattr(catalog, "aiohttp", SimpleNamespace(
        ClientSession=Session, ClientTimeout=aiohttp.ClientTimeout, ClientError=aiohttp.ClientError,
    ))
    return calls


@pytest.mark.asyncio
async def test_catalog_auth_sorted_deduplicated_and_no_redirects(monkeypatch):
    calls = fake_server(monkeypatch)
    result = await list_remote_models(RemoteModelRequest(
        base_url=" https://provider.example/api/v1/ ", api_key=" test-credential "
    ))
    assert result == {"models": [{"id": "chat-a", "name": "Chat A"}, {"id": "chat-b", "name": "chat-b"}],
                      "truncated": False}
    assert calls[1] == {"url": "https://provider.example/api/v1/models",
                        "headers": {"Accept": "application/json", "Authorization": "Bearer test-credential"},
                        "allow_redirects": False}
    assert calls[0]["session"]["timeout"].total == 15
    assert calls[0]["session"]["trust_env"] is False


@pytest.mark.asyncio
async def test_catalog_without_key(monkeypatch):
    calls = fake_server(monkeypatch, payload={"data": []})
    assert (await list_remote_models(RemoteModelRequest(base_url="https://provider.example/v1")))["models"] == []
    assert "Authorization" not in calls[1]["headers"]


@pytest.mark.parametrize("status,match", [(401, "chiave"), (403, "permessi"), (404, "Base URL"),
                                        (429, "limitato"), (302, "reindirizza"), (500, "HTTP 500")])
@pytest.mark.asyncio
async def test_provider_error_bodies_not_exposed(monkeypatch, caplog, status, match):
    fake_server(monkeypatch, status=status, raw=b"PRIVATE RESPONSE test-credential")
    with pytest.raises(ValueError, match=match) as error:
        await list_remote_models(RemoteModelRequest(base_url="https://provider.example/v1", api_key="test-credential"))
    assert "PRIVATE" not in str(error.value) + caplog.text
    assert "test-credential" not in str(error.value) + caplog.text


@pytest.mark.parametrize("exception,match", [
    (asyncio.TimeoutError("test-credential"), "15 secondi"),
    (aiohttp.ClientConnectionError("test-credential"), "collegarsi"),
])
@pytest.mark.asyncio
async def test_connection_errors_are_sanitized(monkeypatch, exception, match):
    fake_server(monkeypatch, exception=exception)
    with pytest.raises(ValueError, match=match) as error:
        await list_remote_models(RemoteModelRequest(base_url="https://provider.example/v1"))
    assert "test-credential" not in str(error.value)


@pytest.mark.parametrize("raw,match", [(b"not json", "JSON valido"), (b"x" * (2*1024*1024+1), "2 MB")],
                         ids=["invalid-json", "oversized"])
@pytest.mark.asyncio
async def test_bad_or_oversized_catalog(monkeypatch, raw, match):
    fake_server(monkeypatch, raw=raw)
    with pytest.raises(ValueError, match=match):
        await list_remote_models(RemoteModelRequest(base_url="https://provider.example/v1"))


@pytest.mark.parametrize("url", [
    "http://provider.example/v1", "file:///models", "https://user:secret@provider.example/v1",
    "https://provider.example/v1?key=secret", "https://provider.example/v1#fragment",
    "https://provider.example:70000/v1", "https:///v1", "https://provider.example/invalid path",
])
def test_remote_urls_keep_existing_https_security(url):
    with pytest.raises(ValueError, match="HTTPS"):
        remote_api_url(url)


def test_key_cannot_inject_headers():
    with pytest.raises(ValueError, match="caratteri"):
        RemoteModelRequest(base_url="https://provider.example/v1", api_key="a\r\nX-Test: b")


def test_catalog_shape_and_safe_metadata():
    for payload in ([], {}, {"data": "invalid"}, {"data": [{"id": None}, {"id": "\n"}]}):
        with pytest.raises(ValueError):
            normalize_catalog(payload)
    assert normalize_catalog({"data": [None, {"id": "a", "name": "A", "extra": "ignored"}]}) == {
        "models": [{"id": "a", "name": "A"}], "truncated": False
    }
    result = normalize_catalog({"data": [{"id": f"model-{i:04}"} for i in range(2001)]})
    assert result["truncated"] and len(result["models"]) == 2000


@pytest.mark.asyncio
async def test_catalog_and_generation_use_same_base_url():
    provider = Provider(mode="remote", base_url=" https://provider.example/api/v1/ ",
                        model="chat-a", remote_consent=True)
    llm = LLM(provider, None)
    await llm.prepare()
    assert llm.url == RemoteModelRequest(base_url=provider.base_url).base_url
    assert llm.model == "chat-a"


@pytest.mark.asyncio
async def test_http_catalog_security_no_jobs_or_credentials_saved(tmp_path, monkeypatch, caplog):
    calls = fake_server(monkeypatch)
    app = create_app(ROOT, tmp_path / "data")
    async with TestClient(TestServer(app)) as client:
        body = {"base_url": "https://provider.example/v1", "api_key": "test-credential"}
        denied = await client.post("/api/remote-models", json=body)
        assert denied.status == 403
        denied = await client.post("/api/remote-models", headers={**HEADERS, "Origin": "https://other.example"}, json=body)
        assert denied.status == 403
        invalid = await client.post("/api/remote-models", headers=HEADERS, json={**body, "prompt": "not allowed"})
        assert invalid.status == 400
        assert calls == []
        response = await client.post("/api/remote-models", headers=HEADERS, json=body)
        assert response.status == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert len((await response.json())["models"]) == 2
        assert app["store"].jobs() == []
        assert app["store"].projects() == []
        assert "test-credential" not in caplog.text
    for path in (tmp_path / "data").rglob("*"):
        if path.is_file():
            assert b"test-credential" not in path.read_bytes()


@pytest.mark.asyncio
async def test_model_selector_browser(tmp_path, monkeypatch):
    async def test_catalog(settings):
        await asyncio.sleep(.03)
        if settings.api_key != "test-only":
            raise ValueError("Accesso al catalogo negato: verifica la chiave API.")
        return {"models": [{"id": "demo/chat-small", "name": "Chat small"},
                           {"id": "demo/chat-vision", "name": "Chat vision"}], "truncated": False}

    monkeypatch.setattr(application, "list_remote_models", test_catalog)
    app = create_app(ROOT, tmp_path / "data")
    async with TestClient(TestServer(app)) as client:
        await run_child(app, [ROOT / "runtime/node/node.exe", ROOT / "tests/remote-models-ui.mjs",
                             str(client.make_url("/"))], ROOT, tmp_path / "model-selector-ui.log",
                        dict(os.environ), timeout=90)
        assert app["store"].jobs() == []  # Browser intercepts generation: no remote LLM call.
