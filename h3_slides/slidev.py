import json
import shutil
import subprocess
from pathlib import Path


def write_slidev(project, assets, output, strict=False):
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
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
            if not dst.exists():
                shutil.copy2(src, dst)
    result = subprocess.run([str(root / "runtime/node/node.exe"), str(root / "scripts/slidev_source.mjs")],
                            input=json.dumps(project), capture_output=True, text=True, encoding="utf-8",
                            timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    result.check_returncode()
    rendered = json.loads(result.stdout)
    if strict and rendered.get("overflow"):
        raise ValueError("Testo fuori dallo spazio nelle slide " + ", ".join(map(str, rendered["overflow"])) +
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
