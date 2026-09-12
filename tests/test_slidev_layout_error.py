import json
import subprocess
from types import SimpleNamespace

import pytest

from h3_slides.app import errors
from h3_slides.models import ProjectInput
from h3_slides.slidev import SlidevLayoutError, write_slidev
from h3_slides.storage import Store


@pytest.fixture
def project():
    return {"slides": [{"content": {"title": "Test"}} for _ in range(3)]}


def failed_process(monkeypatch, stderr):
    monkeypatch.setattr("h3_slides.slidev.shutil.copytree", lambda *a, **k: None)
    monkeypatch.setattr("h3_slides.slidev.subprocess.run", lambda *a, **k:
                        subprocess.CompletedProcess(["node", "private-path"], 1, "", stderr))


def test_layout_error_exposes_only_valid_slide_numbers(tmp_path, monkeypatch, project):
    failed_process(monkeypatch, "PRIVATE PATH\nthrow new Error('PRIVATE CODE');\n"
                   "Error: Testo fuori dallo spazio nelle slide 1, 3, 1. Dividi o modifica il contenuto.\n"
                   "    at file:///PRIVATE/SECRET.js:27")
    with pytest.raises(SlidevLayoutError) as caught:
        write_slidev(project, tmp_path, tmp_path / "output")
    assert str(caught.value) == "Testo fuori dallo spazio nelle slide 1, 3. Dividi o modifica il contenuto prima di esportare."
    assert isinstance(caught.value, ValueError) and isinstance(caught.value, subprocess.SubprocessError)
    assert "PRIVATE" not in str(caught.value) and "SECRET" not in str(caught.value)


@pytest.mark.parametrize("stderr", ["Error: Some other failure PRIVATE", "Error: Testo fuori dallo spazio nelle slide 99.",
                                   "Error: Testo fuori dallo spazio nelle slide 0.",
                                   "throw new Error('Testo fuori dallo spazio nelle slide 1.');"])
def test_other_subprocess_errors_keep_existing_behavior(tmp_path, monkeypatch, project, stderr):
    failed_process(monkeypatch, stderr)
    with pytest.raises(subprocess.CalledProcessError):
        write_slidev(project, tmp_path, tmp_path / "output")


def test_background_layout_error_does_not_abort_project_save(tmp_path, caplog):
    store = Store(tmp_path / "isolated-store")
    try:
        def synchronize(project):
            raise SlidevLayoutError("Testo fuori dallo spazio nelle slide 1.")
        store.on_project_saved = synchronize
        saved = store.create(ProjectInput(title="Progetto salvato").model_dump())
        assert store.project(saved["id"])["title"] == "Progetto salvato"
        assert "Sincronizzazione Slidev non riuscita" in caplog.text
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_layout_error_is_a_public_http_400():
    async def handler(request):
        raise SlidevLayoutError("Testo fuori dallo spazio nelle slide 2. Dividi o modifica il contenuto prima di esportare.")
    response = await errors(SimpleNamespace(method="GET"), handler)
    assert response.status == 400
    assert json.loads(response.text)["error"].startswith("Testo fuori dallo spazio nelle slide 2.")
