"""Download naming over HTTP, using fake artifacts and an isolated app root.

No PDF/PowerPoint authoring, Manim rendering, subprocesses, models, personal
configuration, or real project data are involved in this suite.
"""
import io
import json
from pathlib import Path
import re
import shutil
from urllib.parse import quote, unquote, urlsplit
import zipfile

from aiohttp.test_utils import TestClient, TestServer
import pytest
from yarl import URL

import h3_slides.app as app_module
from h3_slides.models import ProjectInput, SlideContent
from h3_slides.storage import uid


ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"X-H3-Slides": "1"}
FORMATS = {
    "pdf": ("presentazione.pdf", ".pdf"),
    "pptx": ("presentazione.pptx", ".pptx"),
    "slidev": ("slidev.zip", "_Slidev.zip"),
    "manim": ("manim-video-slides.zip", "_Manim_video_slide.zip"),
}
FAKE_BYTES = {"pdf": b"FAKE-PDF: HTTP transport only\x00\xff",
              "pptx": b"FAKE-PPTX: HTTP transport only\x00\xff"}
FAKE_MARKDOWN = b"# Synthetic Slidev fixture\n"
FAKE_CSS = b"/* Synthetic fixture; no rendering. */\n"
FAKE_HTML = b"<html>Fake Manim export fixture</html>"
FAKE_VIDEO = b"FAKE-MP4: HTTP transport only\x00\xff"
STAMP = r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}"


@pytest.fixture
def isolated_export_app(tmp_path, monkeypatch):
    root = tmp_path / "application"
    root.mkdir()
    (root / "static").mkdir()
    shutil.copyfile(ROOT / "config.example.json", root / "config.example.json")
    app = app_module.create_app(root, tmp_path / "data")

    async def fake_run_child(_app, args, cwd, log_path, env=None, timeout=1200):
        args = list(map(str, args))
        cwd = Path(cwd)
        assert cwd.is_relative_to(tmp_path)
        assert Path(log_path).is_relative_to(tmp_path)
        if Path(args[1]).name == "export.mjs":
            output, fmt = Path(args[-2]), args[-1]
            (output / FORMATS[fmt][0]).write_bytes(FAKE_BYTES[fmt])
        elif args[1:3] == ["-m", "manim"]:
            video = cwd / "media" / "videos" / "fixture" / "H3Deck.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(FAKE_VIDEO)
        elif args[1] == "convert":
            (cwd / "presentazione.html").write_bytes(FAKE_HTML)
        else:
            pytest.fail("Unexpected export subprocess request: " + repr(args))

    def fake_write_slidev(project, assets, output, strict=False):
        assert strict is True
        assert output.is_relative_to(tmp_path)
        (output / "slides.md").write_bytes(FAKE_MARKDOWN)
        (output / "style.css").write_bytes(FAKE_CSS)
        return output / "slides.md"

    async def forbidden_render(*args, **kwargs):
        pytest.fail("HTTP download-name tests must never render a diagram")

    monkeypatch.setattr(app_module, "run_child", fake_run_child)
    monkeypatch.setattr(app_module, "write_slidev", fake_write_slidev)
    monkeypatch.setattr(app["worker"].renderer, "render", forbidden_render)
    return app


def seed_project(app, title="Ottica È | luce 東京"):
    project = app["store"].create(ProjectInput(
        title=title, use_manim_diagrams=False).model_dump())
    project["slides"] = [{"id": "synthetic-slide", "status": "ready", "revision": 1,
                          "content": SlideContent(
                              title="Copertina diversa dal nome del progetto",
                              layout="cover").model_dump()}]
    return app["store"].save_project(project)


async def export(client, project, fmt):
    response = await client.post(f"/api/projects/{project['id']}/export/{fmt}",
                                 headers=HEADERS, json={})
    assert response.status == 200, await response.text()
    payload = await response.json()
    parts = urlsplit(payload["url"])
    assert parts.query == parts.fragment == ""
    assert parts.path.split("/")[-1] == FORMATS[fmt][0]
    assert parts.path.startswith(f"/api/exports/{project['id']}/")
    assert payload["filename"] not in payload["url"]
    return payload


def assert_attachment(response, filename):
    header = response.headers["Content-Disposition"]
    assert header.startswith("attachment; ")
    fallback = re.search(r'filename="([^"]+)"', header)
    assert fallback and fallback.group(1).isascii()
    assert "/" not in fallback.group(1) and "\\" not in fallback.group(1)
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == filename
    assert response.content_disposition.filename == filename
    assert "\r" not in header and "\n" not in header
    return header


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", FORMATS)
async def test_named_downloads_keep_internal_paths_and_survive_project_rename(isolated_export_app, fmt):
    app = isolated_export_app
    project = seed_project(app)
    async with TestClient(TestServer(app)) as client:
        payload = await export(client, project, fmt)
        assert re.fullmatch(r"Ottica_È_luce_東京_" + STAMP + re.escape(FORMATS[fmt][1]),
                            payload["filename"])
        response = await client.get(payload["url"])
        assert response.status == 200
        header = assert_attachment(response, payload["filename"])
        raw = await response.read()
        output = app["root"] / "outputs" / project["id"] / payload["url"].split("/")[-2]
        assert raw == (output / FORMATS[fmt][0]).read_bytes()
        metadata = (output / "download.json").read_bytes()
        assert json.loads(metadata)["filename"] == payload["filename"]
        if fmt in FAKE_BYTES:
            assert raw == FAKE_BYTES[fmt]
        else:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                expected = ({"slides.md": FAKE_MARKDOWN, "style.css": FAKE_CSS}
                            if fmt == "slidev" else
                            {"presentazione.html": FAKE_HTML, "presentazione.mp4": FAKE_VIDEO})
                assert set(archive.namelist()) == set(expected)
                for name, value in expected.items():
                    assert archive.read(name) == value

        renamed = await client.patch(f"/api/projects/{project['id']}", headers=HEADERS,
                                     json={"title": "Nuovo nome del progetto"})
        assert renamed.status == 200, await renamed.text()
        old_download = await client.get(payload["url"])
        assert old_download.status == 200
        assert assert_attachment(old_download, payload["filename"]) == header
        assert await old_download.read() == raw
        assert (output / "download.json").read_bytes() == metadata

        new_payload = await export(client, project, fmt)
        assert new_payload["url"] != payload["url"]
        assert re.fullmatch(r"Nuovo_nome_del_progetto_" + STAMP + re.escape(FORMATS[fmt][1]),
                            new_payload["filename"])
        new_download = await client.get(new_payload["url"])
        assert new_download.status == 200
        assert_attachment(new_download, new_payload["filename"])
        await new_download.read()


@pytest.mark.asyncio
async def test_download_allowlist_hides_metadata_and_rejects_traversal(isolated_export_app):
    app = isolated_export_app
    project = seed_project(app)
    async with TestClient(TestServer(app)) as client:
        payload = await export(client, project, "pdf")
        prefix = payload["url"].rsplit("/", 1)[0]
        for name in ("download.json", "project.json", "export.log", quote(payload["filename"], safe=""),
                     "..%2Fdownload.json", "..%5Cdownload.json",
                     "presentazione.pdf%2F..%2Fdownload.json"):
            response = await client.get(URL(prefix + "/" + name, encoded=True))
            assert response.status == 404, (name, await response.text())
            assert "Content-Disposition" not in response.headers
        for eid in ("not-a-uuid", "g" * 36, "..%2F..%2Fconfig.example.json"):
            response = await client.get(URL(
                f"/api/exports/{project['id']}/{eid}/presentazione.pdf", encoded=True))
            assert response.status == 404, (eid, await response.text())
        missing = await client.get(f"/api/exports/{project['id']}/{uid()}/presentazione.pdf")
        assert missing.status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("has_snapshot", [False, True])
async def test_legacy_downloads_use_historical_snapshot_or_internal_fallback(
        isolated_export_app, fmt, has_snapshot):
    app = isolated_export_app
    project = seed_project(app, "Nome attuale da non usare")
    eid = uid()
    output = app["root"] / "outputs" / project["id"] / eid
    output.mkdir(parents=True)
    internal_name, suffix = FORMATS[fmt]
    raw = b"Legacy synthetic artifact: no real document authoring\x00\xff"
    (output / internal_name).write_bytes(raw)
    if has_snapshot:
        (output / "project.json").write_text(json.dumps(
            {"title": "Nome storico", "slides": []}), encoding="utf-8")
    assert not (output / "download.json").exists()
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    async with TestClient(TestServer(app)) as client:
        response = await client.get(f"/api/exports/{project['id']}/{eid}/{internal_name}")
        assert response.status == 200
        filename = response.content_disposition.filename
        if has_snapshot:
            assert re.fullmatch(r"Nome_storico_" + STAMP + re.escape(suffix), filename)
        else:
            assert filename == internal_name
        assert_attachment(response, filename)
        assert await response.read() == raw
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
