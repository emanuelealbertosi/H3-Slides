from pathlib import Path
import pytest
from pydantic import ValidationError
from h3_slides.llm import LlamaManager
from h3_slides.models import DiagramSpec
from h3_slides.runtime_settings import LoadingSettings, InferenceSettings


def test_profiles_persist_separately_and_reject_unknown_model(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    a, b = models / "a.gguf", models / "b.gguf"
    a.touch()
    b.touch()
    config = {"model_roots": [str(models)], "context_size": 16384, "gpu_layers": -1}
    manager = LlamaManager(tmp_path, config, None)
    profile = manager.profile(str(a.resolve()))
    profile["loading"]["context_size"] = 8192
    profile["inference"]["temperature"] = .7
    manager.save_profile(profile)
    reloaded = LlamaManager(tmp_path, config, None)
    assert reloaded.profile(str(a.resolve())) == profile
    assert reloaded.profile(str(b.resolve()))["inference"]["temperature"] == .35
    assert reloaded.profile(str(b.resolve()))["loading"]["context_size"] == 16384
    with pytest.raises(ValueError, match="catalogo"):
        reloaded.save_profile({"model": "untrusted.gguf"})


def test_invalid_settings_and_diagrams():
    with pytest.raises(ValidationError):
        LoadingSettings(batch_size=32, ubatch_size=512)
    with pytest.raises(ValidationError):
        InferenceSettings(temperature=4)
    with pytest.raises(ValidationError):
        LoadingSettings(extra_cli="--host 0.0.0.0")
    with pytest.raises(ValidationError):
        DiagramSpec(kind="flow", labels=["one"])
    assert DiagramSpec(kind="cycle", labels=["A", "B"]).kind == "cycle"
