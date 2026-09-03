import json
import shutil
import subprocess
from pathlib import Path


def write_slidev(project, assets, output, strict=False):
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    for n, slide in enumerate(project["slides"]):
        c = slide["content"]
        diagram = project.get("use_manim_diagrams") and c.get("diagram", {}).get("kind", "none") != "none"
        if c["image_id"] and project.get("use_source_images", True) and not diagram:
            (output / "assets").mkdir(exist_ok=True)
            src, dst = assets / c["image_id"], output / "assets" / c["image_id"]
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
