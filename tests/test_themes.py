import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from pydantic import ValidationError

from h3_slides.app import create_app
from h3_slides.models import ProjectInput
from h3_slides.themes import ThemeDesign, ThemeLibrary, ThemePreset

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}


def test_presets_validate_and_old_projects_have_automatic_theme():
    for preset in json.loads((ROOT / "static/theme-presets.json").read_text(encoding="utf-8")):
        ThemePreset.model_validate(preset)
    assert ProjectInput(title="Vecchio progetto").theme_design.text_color == ""


@pytest.mark.parametrize("values", [
    {"text_color": "url(https://evil.invalid)"}, {"text_color": "#fff"},
    {"font": "untrusted"}, {"body_size": 1}, {"title_size": 90},
    {"border_width": -1}, {"box_radius": 100},
])
def test_themes_reject_unsafe_or_unreadable_values(values):
    with pytest.raises(ValidationError):
        ThemeDesign.model_validate(values)


def test_theme_library_persists_and_updates_without_duplicates(tmp_path):
    library = ThemeLibrary(tmp_path)
    preset = {"name": "Tema mio", "values": {"theme_design": {"box_radius": 0}}}
    library.save(preset)
    assert ThemeLibrary(tmp_path).list()[0]["values"]["theme_design"]["box_radius"] == 0
    preset["name"] = "TEMA MIO"
    preset["values"]["theme_design"]["box_radius"] = 20
    library.save(preset)
    assert len(library.list()) == 1
    assert library.list()[0]["values"]["theme_design"]["box_radius"] == 20


@pytest.mark.asyncio
async def test_theme_and_search_configuration_api(tmp_path):
    app = create_app(ROOT, tmp_path / "data")
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/api/themes")).status == 200
        preset = {"name": "Contrasto", "values": {"background_color": "#121212", "theme_design": {"title_color": "#ffffff"}}}
        assert (await client.post("/api/themes", json=preset)).status == 403
        assert (await client.post("/api/themes", json=preset, headers=HEADERS)).status == 200
        saved = await (await client.get("/api/themes")).json()
        assert saved[0]["values"]["theme_design"]["title_color"] == "#ffffff"
        response = await client.post("/api/projects", json={"title": "Tema", **saved[0]["values"]}, headers=HEADERS)
        project = await response.json()
        assert project["theme_design"]["title_color"] == "#ffffff"
        assert (await client.post("/api/admin/search", json={"searxng_url": "https://example.com"}, headers=HEADERS)).status == 400
        assert (await client.post("/api/admin/search", json={"searxng_url": "http://127.0.0.1:8888"}, headers=HEADERS)).status == 200
        config = await (await client.get("/api/admin/search")).json()
        assert config["searxng_url"] == "http://127.0.0.1:8888"
