import json
import re
import shutil
import subprocess
from pathlib import Path
from PIL import Image


class SlidevLayoutError(ValueError, subprocess.SubprocessError):
    """Public layout error; background synchronization must not abort a save."""


def write_slidev(project, assets, output, strict=False):
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    media_dimensions = {}
    katex_fonts = root / "static" / "vendor" / "katex" / "fonts"
    if katex_fonts.exists():
        shutil.copytree(katex_fonts, output / "fonts", dirs_exist_ok=True)
    for n, slide in enumerate(project["slides"]):
        c = slide["content"]
        rendered = slide.get("diagram_render", {})
        diagram = (project.get("use_manim_diagrams") and c.get("diagram", {}).get("kind", "none") != "none"
                   and rendered.get("engine") == "manim" and rendered.get("asset"))
        record = next((a for a in project.get("visual_assets", []) if a["id"] == c.get("image_id")), {})
        origin = record.get("origin", c.get("image_origin", "source"))
        photo = c.get("image_id", "") if origin != "source" or project.get("use_source_images", True) else ""
        images = {image for image in (rendered.get("asset") if diagram else "", photo) if image}
        for image in images:
            (output / "assets").mkdir(exist_ok=True)
            src, dst = assets / image, output / "assets" / image
            if image not in media_dimensions:
                with Image.open(src) as decoded:
                    media_dimensions[image] = {"width": decoded.width, "height": decoded.height}
            if not dst.exists():
                shutil.copy2(src, dst)
    result = subprocess.run([str(root / "runtime/node/node.exe"), str(root / "scripts/slidev_source.mjs")],
                            input=json.dumps({**project, "_media_dimensions": media_dimensions}),
                            capture_output=True, text=True, encoding="utf-8",
                            timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        # Parse only our fixed diagnostic line. Never expose stderr, source
        # snippets, local paths or a provider's text through the public API.
        message = re.search(r"(?m)^Error: Testo fuori dallo spazio nelle slide ([1-9]\d*(?:,\s*[1-9]\d*)*)\.",
                            (result.stderr or "")[:65536])
        if message and len(message[1]) <= 200:
            indices = list(dict.fromkeys(int(value.strip()) for value in message[1].split(",")))
            if all(1 <= index <= len(project["slides"]) for index in indices):
                raise SlidevLayoutError("Testo fuori dallo spazio nelle slide " + ", ".join(map(str, indices)) +
                                        ". Dividi o modifica il contenuto prima di esportare.") from None
    result.check_returncode()
    rendered = json.loads(result.stdout)
    if strict and rendered.get("overflow"):
        raise SlidevLayoutError("Testo fuori dallo spazio nelle slide " + ", ".join(map(str, rendered["overflow"])) +
                         ". Dividi o modifica il contenuto prima di esportare.")
    text = rendered["markdown"]
    css_target = output / "style.css"
    if not css_target.exists() or css_target.read_text(encoding="utf-8") != rendered["css"]:
        css_temp = output / "style.tmp"
        css_temp.write_text(rendered["css"], encoding="utf-8")
        css_temp.replace(css_target)
    target = output / "slides.md"
    if not target.exists() or target.read_text(encoding="utf-8") != text:
        temp = output / "slides.tmp"
        temp.write_text(text, encoding="utf-8")
        temp.replace(target)
    return target
