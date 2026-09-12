import os
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from h3_slides.mtp import MtpSupport, MAX_ARRAY_ITEMS, MAX_RECORDS, MAX_STRING_BYTES
from h3_slides.runtime_settings import LoadingSettings


HELP = """llama-server
--spec-type TYPE              speculative decoding type (none, draft-simple, draft-mtp)
--spec-draft-n-max N          maximum number of predicted draft tokens
--draft-max N                REMOVED: use --spec-draft-n-max instead
--help                       show help
"""


def string(value):
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw))+raw


def metadata(key, value):
    if isinstance(value, str):
        return string(key)+struct.pack("<I", 8)+string(value)
    if isinstance(value, list):
        return string(key)+struct.pack("<IIQ", 9, 8, len(value))+b"".join(string(item) for item in value)
    return string(key)+struct.pack("<Iq", 11, value)


def gguf(path, *, architecture="qwen35", blocks=65, heads=1, tensors=None, extra=None, version=3):
    values = {"general.architecture": architecture, architecture+".block_count": blocks,
              architecture+".nextn_predict_layers": heads, **(extra or {})}
    names = [f"blk.{blocks-1}.nextn.eh_proj.weight"] if tensors is None else tensors
    raw = struct.pack("<4sIQQ", b"GGUF", version, len(names), len(values))
    raw += b"".join(metadata(key, value) for key, value in values.items())
    raw += b"".join(string(name)+struct.pack("<IQIQ", 1, 16, 0, 0) for name in names)
    path.write_bytes(raw)
    return path


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"synthetic runtime")
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=HELP)
    monkeypatch.setattr("h3_slides.mtp.subprocess.run", run)
    return executable, calls


def test_mtp_profile_is_opt_in_one_prediction_and_strictly_bounded():
    settings = LoadingSettings()
    assert settings.mtp_enabled is False and settings.mtp_predictions == 1
    assert LoadingSettings(mtp_enabled=True, mtp_predictions=16).mtp_predictions == 16
    for value in [0, 17, True, "2", 1.5]:
        with pytest.raises(ValidationError):
            LoadingSettings(mtp_predictions=value)
    for value in [1, "true", None]:
        with pytest.raises(ValidationError):
            LoadingSettings(mtp_enabled=value)


def test_integrated_mtp_detection_uses_metadata_and_actual_tensor_without_loading_weights(tmp_path, runtime):
    executable, calls = runtime
    model = gguf(tmp_path / "arbitrary-name.gguf", extra={"tokenizer.ggml.tokens": ["a", "b", "token"]})
    before = model.read_bytes()
    report = MtpSupport().probe(executable, model)
    assert report == {"supported": True, "runtime_supported": True, "model_supported": True,
        "architecture": "qwen35", "spec_type": "draft-mtp", "predictions_flag": "--spec-draft-n-max",
        "reason_code": "supported", "reason": report["reason"]}
    assert "rilevata" in report["reason"] and "memoria" in report["reason"]
    assert model.read_bytes() == before
    assert calls[0][0] == [str(executable.resolve()), "--help"]
    assert calls[0][1]["timeout"] == 5
    assert "-m" not in calls[0][0] and "--model" not in calls[0][0]
    if os.name == "nt":
        assert calls[0][1]["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert calls[0][1]["startupinfo"].wShowWindow == subprocess.SW_HIDE


@pytest.mark.parametrize("architecture", ["qwen35", "qwen35moe", "future_supported_arch"])
def test_capability_is_not_an_architecture_allowlist(tmp_path, runtime, architecture):
    model = gguf(tmp_path / "model.gguf", architecture=architecture)
    result = MtpSupport().probe(runtime[0], model)
    assert result["supported"] and result["architecture"] == architecture


@pytest.mark.parametrize("options", [
    {"heads": 0}, {"heads": -1}, {"heads": 66}, {"tensors": []},
    {"tensors": ["blk.63.nextn.eh_proj.weight"]}, {"extra": {"qwen35.router_layer": 1}},
])
def test_filename_and_partial_evidence_do_not_enable_mtp(tmp_path, runtime, options):
    report = MtpSupport().probe(runtime[0], gguf(tmp_path / "QWEN-MTP-SUPPORTED.gguf", **options))
    assert not report["supported"] and report["runtime_supported"]
    assert report["model_supported"] is False and report["reason_code"] == "model_mtp_absent"


@pytest.mark.parametrize("help_text,spec,enabled", [
    (HELP, "draft-mtp", True),
    (HELP.replace("draft-mtp)", "mtp)"), "mtp", True),
    ("--spec-type TYPE none, draft-mtp\n--draft-max N REMOVED: use --spec-draft-n-max\n", "draft-mtp", False),
    ("--spec-type TYPE none, draft-mtp REMOVED\n--spec-draft-n-max N count\n", None, False),
    ("--spec-type TYPE none, draft-mtp-ngram\n--spec-draft-n-max N count\n", None, False),
    ("--spec-type TYPE none, draft-simple\n--spec-draft-n-max N count\n", None, False),
])
def test_runtime_help_requires_live_spec_type_and_prediction_flags(tmp_path, runtime, monkeypatch, help_text, spec, enabled):
    monkeypatch.setattr("h3_slides.mtp.subprocess.run", lambda *_, **__: SimpleNamespace(returncode=0, stdout=help_text))
    report = MtpSupport().probe(runtime[0], gguf(tmp_path / "model.gguf"))
    assert report["runtime_supported"] is enabled and report["spec_type"] == spec
    assert report["supported"] is enabled
    if "--spec-draft-n-max" not in help_text.splitlines()[-1] and not enabled:
        assert report["predictions_flag"] in (None, "--spec-draft-n-max")


def test_model_and_runtime_cache_invalidate_on_file_identity_changes(tmp_path, runtime):
    executable, calls = runtime
    model = gguf(tmp_path / "model.gguf")
    support = MtpSupport()
    first = support.probe(executable, model)
    assert support.probe(executable, model) == first and len(calls) == 1
    gguf(model, heads=0, extra={"general.name": "changed model"})
    assert support.probe(executable, model)["model_supported"] is False
    assert len(calls) == 1, "A model change does not rerun an unchanged executable"
    executable.write_bytes(b"updated executable")
    assert support.probe(executable, model)["model_supported"] is False and len(calls) == 2


def test_split_gguf_finds_head_in_later_shard_and_rechecks_each_part(tmp_path, runtime):
    first = gguf(tmp_path / "model-00001-of-00002.gguf", tensors=["blk.0.attn.weight"])
    second = gguf(tmp_path / "model-00002-of-00002.gguf")
    support = MtpSupport()
    assert support.probe(runtime[0], first)["supported"]
    gguf(second, tensors=["blk.1.attn.weight"])
    assert not support.probe(runtime[0], first)["supported"]
    second.unlink()
    report = support.probe(runtime[0], first)
    assert report["model_supported"] is None and report["reason_code"] == "model_missing"


@pytest.mark.parametrize("payload,code", [
    (b"not GGUF", "model_invalid"),
    (struct.pack("<4sIQQ", b"GGUF", 99, 0, 0), "model_invalid"),
    (struct.pack("<4sIQQ", b"GGUF", 3, MAX_RECORDS+1, 0), "model_scan_limit"),
    (struct.pack("<4sIQQQ", b"GGUF", 3, 0, 1, MAX_STRING_BYTES+1), "model_scan_limit"),
    (struct.pack("<4sIQQ", b"GGUF", 3, 0, 1)+string("tokens")+struct.pack("<IIQ", 9, 8, MAX_ARRAY_ITEMS+1), "model_scan_limit"),
    (struct.pack("<4sIQQ", b"GGUF", 3, 0, 1)+string("tokens")+struct.pack("<I", 99), "model_invalid"),
])
def test_malformed_or_excessive_metadata_is_unknown_not_supported(tmp_path, runtime, payload, code):
    path = tmp_path / "bad.gguf"
    path.write_bytes(payload)
    report = MtpSupport().probe(runtime[0], path)
    assert not report["supported"] and report["model_supported"] is None
    assert report["reason_code"] == code


def test_global_scan_budget_is_enforced_without_touching_weight_region(tmp_path, runtime, monkeypatch):
    model = gguf(tmp_path / "model.gguf", extra={"tokenizer.ggml.tokens": ["token"]*100})
    monkeypatch.setattr("h3_slides.mtp.MAX_SCAN_BYTES", 64)
    assert MtpSupport().probe(runtime[0], model)["reason_code"] == "model_scan_limit"
    monkeypatch.setattr("h3_slides.mtp.MAX_SCAN_BYTES", 128*1024*1024)
    original = Path.open
    def protected_open(path, *args, **kwargs):
        return original(path, *args, **kwargs)
    # A sparse weight trailer has no effect on parsing: the helper stops after
    # the tensor directory and does not attempt to interpret or allocate it.
    with model.open("ab") as output:
        output.write(b"INVALID WEIGHT BYTES THAT MUST NOT BE PARSED"*100)
    assert MtpSupport().probe(runtime[0], model)["supported"]


def test_timeout_and_failed_help_are_explained_without_raising(tmp_path, runtime, monkeypatch):
    model = gguf(tmp_path / "model.gguf")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("runtime --help", 5)
    monkeypatch.setattr("h3_slides.mtp.subprocess.run", timeout)
    assert MtpSupport().probe(runtime[0], model)["reason_code"] == "runtime_timeout"
    monkeypatch.setattr("h3_slides.mtp.subprocess.run", lambda *_, **__: SimpleNamespace(returncode=1, stdout="failure"))
    assert MtpSupport().probe(runtime[0], model)["reason_code"] == "runtime_help_failed"
    assert MtpSupport().probe(tmp_path / "absent.exe", model)["reason_code"] == "runtime_missing"


def test_parallel_calls_share_cached_help_without_database_or_model_load(tmp_path, runtime):
    model = gguf(tmp_path / "model.gguf")
    support = MtpSupport()
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(lambda _: support.probe(runtime[0], model), range(12)))
    assert all(report["supported"] for report in reports) and len(runtime[1]) == 1
    reports[0]["supported"] = False
    assert support.probe(runtime[0], model)["supported"], "Returned dictionaries cannot poison the cache"
