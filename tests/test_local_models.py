import json
import os
from pathlib import Path
import struct
import pytest
from aiohttp.test_utils import TestClient, TestServer
from h3_slides import app as app_module
from h3_slides.app import create_app, run_child
from h3_slides.llm import LlamaManager
from h3_slides.local_models import LocalModelFiles, validate_model
from h3_slides.preflight import inspect_installation

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


def gguf(path):
    path.write_bytes(struct.pack("<4sIQQ", b"GGUF", 3, 1, 1)+b"fixture, not real weights")
    return path


def test_links_are_persistent_no_copy_and_missing_disks_are_nonfatal(tmp_path):
    outside = tmp_path / "Modelli esterni"
    outside.mkdir()
    model = gguf(outside / "modello à.gguf")
    root = tmp_path / "app"
    config = {"model_roots": ["models"], "context_size":16384, "gpu_layers":-1}
    library = LocalModelFiles(root / "data")
    original = model.read_bytes()
    linked = library.register(str(model))
    library.register(str(model))
    assert model.read_bytes() == original
    assert library.read() == {"files":[linked], "default_model":linked}
    assert not (root / "models").exists()
    manager = LlamaManager(root, config, None)
    assert manager.catalog()[0]["id"] == linked
    renamed = model.with_suffix(".moved")
    model.rename(renamed)
    assert manager.catalog() == []
    assert library.read()["default_model"] == linked
    renamed.rename(model)
    assert manager.catalog()[0]["id"] == linked


def test_invalid_files_projector_split_and_cancellation(tmp_path):
    for value in ["", "relative.gguf", str(tmp_path / "missing.gguf")]:
        with pytest.raises(ValueError):
            validate_model(value)
    fake = tmp_path / "invalid.gguf"
    fake.write_bytes(b"not a gguf")
    with pytest.raises(ValueError):
        validate_model(str(fake))
    projector = gguf(tmp_path / "mmproj.gguf")
    with pytest.raises(ValueError, match="proiettore"):
        validate_model(str(projector))
    first = gguf(tmp_path / "model-00001-of-00002.gguf")
    with pytest.raises(ValueError, match="parti"):
        validate_model(str(first))
    second = gguf(tmp_path / "model-00002-of-00002.gguf")
    with pytest.raises(ValueError, match="primo"):
        validate_model(str(second))
    assert validate_model(str(first)) == first


@pytest.mark.asyncio
async def test_model_api_empty_pick_cancel_validation_and_persistence(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    app["manager"].config = {**app["manager"].config, "model_roots":[]}
    model = gguf(tmp_path / "modello.gguf")
    selection = ""
    async def picker(*_):
        return selection
    monkeypatch.setattr(app_module, "choose_model_file", picker)
    async with TestClient(TestServer(app)) as client:
        assert (await (await client.get("/api/models")).json())["models"] == []
        assert (await client.post("/api/local-models/pick", json={})).status == 403
        response = await client.post("/api/local-models/pick", json={}, headers=HEADERS)
        assert (await response.json())["cancelled"]
        assert not (tmp_path / "data/model_files.json").exists()
        response = await client.post("/api/local-models/register", json={"path":str(model)+".absent"}, headers=HEADERS)
        assert response.status == 400
        selection = str(model)
        response = await client.post("/api/local-models/pick", json={}, headers=HEADERS)
        assert (await response.json())["model"] == str(model)
        catalog = await (await client.get("/api/models")).json()
        assert catalog["default_model"] == str(model)
        assert len(catalog["models"]) == 1
        assert not catalog["status"]["running"]
        original_active = app["worker"].active
        app["worker"].active = lambda: True
        assert (await client.post("/api/local-models/register", json={"path":str(model)}, headers=HEADERS)).status == 400
        app["worker"].active = original_active


def test_clean_core_install_warns_for_weights_and_engine_without_failing(tmp_path):
    (tmp_path / "config.example.json").write_text((ROOT / "config.example.json").read_text())
    errors, warnings = inspect_installation(tmp_path, core_only=True)
    assert errors == []
    assert any("GGUF" in w for w in warnings)
    assert any("llama-server" in w for w in warnings)
    errors, _ = inspect_installation(tmp_path)
    assert any("Node" in e for e in errors)
    (tmp_path / "config.local.json").write_text("{broken")
    errors, _ = inspect_installation(tmp_path, core_only=True)
    assert any("Configurazione" in e for e in errors)


@pytest.mark.asyncio
async def test_first_run_browser_without_models(tmp_path, monkeypatch):
    app = create_app(ROOT, tmp_path / "data")
    app["manager"].config = {**app["manager"].config, "model_roots":[], "llama_executable":"missing/llama-server.exe"}
    model = gguf(tmp_path / "GGUF con spazi.gguf")
    async def picker(*_):
        return ""  # Exercise cancel without opening an interactive Windows window.
    monkeypatch.setattr(app_module, "choose_model_file", picker)
    async with TestClient(TestServer(app)) as client:
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(ROOT / "runtime/browsers"))
        await run_child(app, [ROOT / "runtime/node/node.exe", ROOT / "tests/first-run.mjs",
                             str(client.make_url("/")), str(model)], ROOT, tmp_path / "first-run.log", env, timeout=90)
