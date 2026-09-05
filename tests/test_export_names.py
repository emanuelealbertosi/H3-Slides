from datetime import datetime, timezone
import json
import re
from urllib.parse import unquote

import pytest

from h3_slides.export_names import (attachment_header, download_filename, export_filename,
                                    safe_title, save_download_name)

WHEN = datetime(2026, 9, 5, 14, 30, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize("fmt,suffix", [
    ("pdf", ".pdf"), ("pptx", ".pptx"), ("slidev", "_Slidev.zip"),
    ("manim", "_Manim_video_slide.zip"),
])
def test_explicit_project_title_and_time_identify_all_export_formats(fmt, suffix):
    project = {"title": "La rivoluzione francese", "slides": [
        {"content": {"layout": "cover", "title": "Un titolo indipendente"}}]}
    assert export_filename(project, fmt, WHEN) == "La_rivoluzione_francese_2026-09-05_14-30-09" + suffix


@pytest.mark.parametrize("title", ["", "  ", None, "Nuova presentazione", "Untitled"])
def test_cover_title_only_fills_an_unnamed_project(title):
    project = {"title": title, "slides": [{"content": {"layout": "cover", "title": "Le città del futuro"}}]}
    assert export_filename(project, "pdf", WHEN).startswith("Le_città_del_futuro_")


@pytest.mark.parametrize("title", [
    ".././\\::**?<>|", "\r\n\t\u202e\u200b", "", "NUL", "con", "COM1", "LPT9",
    "CON.foo", "  Titolo / con: caratteri \"vietati\"? \n", "字" * 500, "è" * 500,
])
def test_titles_are_safe_bounded_filename_components(title):
    stem = safe_title(title)
    assert stem and stem[0] not in "._-" and stem[-1] not in "._-"
    assert all(char.isalnum() or char in "._-" for char in stem)
    assert not re.fullmatch(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", stem.split(".")[0], re.I)
    assert len(stem) <= 103 and len(stem.encode("utf-8")) <= 163
    name = export_filename({"title": title}, "manim", WHEN)
    assert len(name) <= 160 and len(name.encode("utf-8")) <= 240


def test_unicode_download_header_has_ascii_fallback_and_utf8_name():
    name = export_filename({"title": "Caffè e città 中文"}, "pdf", WHEN)
    header = attachment_header(name)
    assert header.isascii() and "\r" not in header and "\n" not in header
    assert 'filename="Caffe_e_citta_' in header
    assert unquote(header.split("filename*=UTF-8''")[1]) == name
    assert "\r" not in attachment_header('Bad"\r\nX-Test: yes.pdf')


def test_non_latin_combining_marks_are_preserved(tmp_path):
    name = save_download_name(tmp_path, {"title": "गणित और विज्ञान"}, "pdf")
    assert name.startswith("गणित_और_विज्ञान_")
    assert download_filename(tmp_path, "presentazione.pdf") == name


def test_saved_name_is_stable_even_if_project_is_renamed(tmp_path):
    project = {"title": "Nome iniziale"}
    name = save_download_name(tmp_path, project, "pdf")
    assert name.startswith("Nome_iniziale_") and name.endswith(".pdf")
    project["title"] = "Nome cambiato"
    assert download_filename(tmp_path, "presentazione.pdf") == name


@pytest.mark.parametrize("metadata", [
    {}, [], {"format": "pdf", "filename": "../../private.pdf"},
    {"format": "pdf", "filename": 'Titolo\r\nX-Test: injected.pdf'},
    {"format": "pdf", "filename": "Titolo.exe"}, {"format": "pdf", "filename": []},
    {"format": "pptx", "filename": "Titolo.pdf"},
])
def test_invalid_metadata_keeps_legacy_download_safe(tmp_path, metadata):
    (tmp_path / "download.json").write_text(json.dumps(metadata), encoding="utf-8")
    assert download_filename(tmp_path, "presentazione.pdf") == "presentazione.pdf"


def test_legacy_snapshot_uses_historical_title_and_missing_snapshot_keeps_old_link(tmp_path):
    (tmp_path / "presentazione.pdf").write_bytes(b"unchanged-test-bytes")
    (tmp_path / "project.json").write_text(json.dumps({"title": "Titolo storico"}), encoding="utf-8")
    assert download_filename(tmp_path, "presentazione.pdf").startswith("Titolo_storico_")
    assert download_filename(tmp_path, "slidev.zip") == "slidev.zip"


def test_export_seconds_distinguish_versions():
    later = WHEN.replace(second=10)
    assert export_filename({"title": "Versioni"}, "pdf", WHEN) != export_filename({"title": "Versioni"}, "pdf", later)
