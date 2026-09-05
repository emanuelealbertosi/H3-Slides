"""Stable, filesystem-safe download names; internal export paths stay private."""
from datetime import datetime
import json
import re
import unicodedata
from urllib.parse import quote


EXPORT_FORMATS = {"presentazione.pdf": "pdf", "presentazione.pptx": "pptx",
                  "slidev.zip": "slidev", "manim-video-slides.zip": "manim"}
_SUFFIXES = {"pdf": ".pdf", "pptx": ".pptx", "slidev": "_Slidev.zip",
             "manim": "_Manim_video_slide.zip"}
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.I)


def _filename_character(char):
    return char.isalnum() or unicodedata.category(char).startswith("M") or char in "._-"


def safe_title(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = "".join(char if _filename_character(char) or char == " " else " " for char in text)
    text = re.sub(r"[\s_]+", "_", text).strip("._-")
    # Bound both Windows character counts and Unix UTF-8 byte counts.
    text = text[:100]
    while len(text.encode("utf-8")) > 160:
        text = text[:-1]
    text = text.rstrip("._-")
    if not text:
        return "H3-Slides"
    if _RESERVED.fullmatch(text.split(".", 1)[0]):
        text = "H3-" + text
    return text


def export_filename(project, fmt, exported_at=None):
    title = project.get("title") or ""
    if not str(title).strip() or str(title).strip().casefold() in {"nuova presentazione", "untitled"}:
        title = next((slide.get("content", {}).get("title") for slide in project.get("slides", [])
                      if slide.get("content", {}).get("layout") == "cover" and
                      str(slide.get("content", {}).get("title", "")).strip()), title)
    stamp = (exported_at or datetime.now().astimezone()).strftime("%Y-%m-%d_%H-%M-%S")
    return f"{safe_title(title)}_{stamp}{_SUFFIXES[fmt]}"


def save_download_name(output, project, fmt):
    name = export_filename(project, fmt)
    (output / "download.json").write_text(json.dumps({"format": fmt, "filename": name},
                                                    ensure_ascii=False), encoding="utf-8")
    return name


def download_filename(output, internal_name):
    fmt = EXPORT_FORMATS[internal_name]
    try:
        raw = (output / "download.json").read_text(encoding="utf-8")
        metadata = json.loads(raw) if len(raw) <= 4096 else {}
        name = metadata.get("filename", "")
        if (metadata.get("format") == fmt and isinstance(name, str) and
                name.endswith(_SUFFIXES[fmt]) and len(name) <= 160 and
                len(name.encode("utf-8")) <= 240 and name[0] not in "._-" and
                all(_filename_character(char) for char in name)):
            return name
    except (OSError, ValueError, AttributeError, TypeError, UnicodeError):
        pass
    # Old links remain valid. A snapshot gives them a useful, historical name;
    # never use the current project title, which may have been changed.
    try:
        snapshot = json.loads((output / "project.json").read_text(encoding="utf-8"))
        when = datetime.fromtimestamp((output / internal_name).stat().st_mtime).astimezone()
        return export_filename(snapshot, fmt, when)
    except (OSError, ValueError, AttributeError, TypeError, UnicodeError):
        return internal_name


def attachment_header(filename):
    fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", fallback)
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'
