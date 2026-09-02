import html
import json
import shutil
from pathlib import Path


def write_slidev(project, assets, output):
    output.mkdir(parents=True, exist_ok=True)
    lines = ["---", "theme: default", "mcp: false", "title: " + json.dumps(project["title"]),
             "fonts:", "  sans: Arial", "  provider: none", "drawings:", "  enabled: false", "---", ""]
    for n, slide in enumerate(project["slides"]):
        c = slide["content"]
        if n:
            lines += ["", "---", ""]
        # Literal content: source text must never be compiled as a Vue expression.
        lines += ['<div v-pre>', "<h1>" + html.escape(c["title"]) + "</h1>",
                  "<p>" + html.escape(c["subtitle"]) + "</p>", "<ul>"]
        lines += ["<li>" + html.escape(b) + "</li>" for b in c["bullets"]]
        lines += ["</ul>"]
        if c["image_id"]:
            (output / "assets").mkdir(exist_ok=True)
            src, dst = assets / c["image_id"], output / "assets" / c["image_id"]
            if not dst.exists():
                shutil.copy2(src, dst)
            lines += ['<img src="./assets/' + c["image_id"] +
                      '" style="max-height:280px;max-width:45%;object-fit:contain" />']
        lines += ["</div>"]
    if not project["slides"]:
        lines += ["# La presentazione è in preparazione"]
    text = "\n".join(lines)
    target = output / "slides.md"
    if not target.exists() or target.read_text(encoding="utf-8") != text:
        temp = output / "slides.tmp"
        temp.write_text(text, encoding="utf-8")
        temp.replace(target)
    return target
