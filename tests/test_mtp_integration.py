import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from h3_slides import llm as module
from h3_slides.app import create_app
from h3_slides.llm import LlamaManager, LLM
from h3_slides.models import Provider
from h3_slides.runtime_settings import RemoteInferenceSettings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = dict(supported=True, runtime_supported=True, model_supported=True,
               architecture='qwen35', spec_type='draft-mtp', predictions_flag='--spec-draft-n-max',
               reason_code='supported', reason='Testa MTP integrata rilevata.')


@pytest.fixture
def managed(tmp_path, monkeypatch):
    model = tmp_path / 'model.gguf'
    model.write_bytes(struct.pack('<4sIQQ', b'GGUF', 3, 1, 1) + b'synthetic header')
    executable = tmp_path / 'llama-server.exe'
    executable.touch()
    (tmp_path / 'logs').mkdir()
    manager = LlamaManager(tmp_path, dict(model_roots=[str(tmp_path)], context_size=16384,
        gpu_layers=-1, llama_executable=str(executable), llama_port=12345), SimpleNamespace(assign=lambda p: None))
    launches, observations = [], []
    class Process:
        code = None
        def poll(self): return self.code
        def terminate(self): self.code = 0
        def wait(self): return self.code
    def popen(args, **kwargs):
        launches.append(args)
        return Process()
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def connect_ex(self, *_): return 1
    class Response:
        status = 200
        async def __aenter__(self):
            observations.append(dict(manager.status()['mtp']))
            return self
        async def __aexit__(self, *_): pass
    class Session:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        def get(self, *_): return Response()
    monkeypatch.setattr(module, 'socket', SimpleNamespace(socket=Socket))
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    monkeypatch.setattr(module.aiohttp, 'ClientSession', Session)
    manager.mtp_capability = AsyncMock(return_value=SUPPORT.copy())
    return manager, str(model.resolve()), launches, observations


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,supported,predictions', [(True, True, 1), (True, True, 16), (True, False, 4), (False, True, 1)])
async def test_mtp_launch_flags_health_gate_and_profile_reuse(managed, enabled, supported, predictions):
    manager, model, launches, observations = managed
    manager.mtp_capability.return_value = {**SUPPORT, 'supported': supported}
    profile = manager.profile(model)
    profile['loading'].update(mtp_enabled=enabled, mtp_predictions=predictions)
    manager.save_profile(profile)
    assert not launches
    try:
        await manager.start(model)
        args = launches[0]
        if enabled and supported:
            assert args[args.index('--spec-type')+1] == 'draft-mtp'
            assert args[args.index('--spec-draft-n-max')+1] == str(predictions)
        else:
            assert '--spec-type' not in args and '--spec-draft-n-max' not in args
        assert '--draft-max' not in args and '--model-draft' not in args
        assert manager.mtp_capability.await_count == int(enabled)
        assert observations[0]['active'] is False
        assert manager.status()['mtp']['active'] == (enabled and supported)
        await manager.start(model)
        assert len(launches) == 1, 'Same profile reuses the running model'
    finally:
        await manager.stop()
    assert manager.status()['mtp'] is None


@pytest.mark.asyncio
async def test_failed_mtp_start_never_reports_active_or_retries_silently(managed):
    manager, model, launches, observations = managed
    profile = manager.profile(model); profile['loading']['mtp_enabled'] = True
    manager.save_profile(profile)
    manager.guard.assign = lambda process: setattr(process, 'code', 1)
    with pytest.raises(RuntimeError, match='MTP'):
        await manager.start(model)
    assert len(launches) == 1 and not observations
    assert not manager.status()['running'] and manager.status()['mtp'] is None
    assert manager.log is None


@pytest.mark.asyncio
async def test_capability_endpoint_catalog_gate_profiles_and_schema(tmp_path):
    app = create_app(ROOT, tmp_path / 'data')
    manager = app['manager']
    model = tmp_path / 'test.gguf'; model.touch()
    manager.config = {**manager.config, 'model_roots': [str(tmp_path)]}
    calls = []
    manager.mtp_support.probe = lambda executable, model: (calls.append(model) or SUPPORT.copy())
    async with TestClient(TestServer(app)) as client:
        assert (await client.get('/api/admin/llm/mtp?model=not-in-catalog')).status == 400
        assert not calls
        result = await (await client.get('/api/admin/llm/mtp', params={'model': str(model.resolve())})).json()
        assert result['supported'] and calls == [str(model.resolve())]
        admin = await (await client.get('/api/admin/llm')).json()
        assert admin['loading_schema']['properties']['mtp_predictions']['default'] == 1
        profile = admin['profiles'][str(model.resolve())]
        assert profile['loading']['mtp_enabled'] is False
        profile['loading'].update(mtp_enabled=True, mtp_predictions=3)
        response = await client.post('/api/admin/llm', json=profile, headers={'X-H3-Slides': '1'})
        assert response.status == 200
        assert manager.profile(str(model.resolve()))['loading']['mtp_predictions'] == 3
        assert manager.process is None
        profile['loading']['mtp_predictions'] = 0
        assert (await client.post('/api/admin/llm', json=profile, headers={'X-H3-Slides': '1'})).status == 400


@pytest.mark.asyncio
async def test_remote_prepare_never_uses_local_mtp():
    client = LLM(Provider(mode='remote', model='remote-model', base_url='http://127.0.0.1:1234',
                          remote_consent=True), SimpleNamespace())
    client.runtime_callback = lambda _: pytest.fail('Remote provider must not access local MTP')
    await client.prepare()
    assert client.sampling == RemoteInferenceSettings().model_dump()
    assert not any('mtp' in key for key in client.sampling)
