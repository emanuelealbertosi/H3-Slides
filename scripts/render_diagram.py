"""Render one validated scene with the installed Manim; no model-generated code."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manim import Scene, tempconfig
from h3_slides.manim_scene import build_scene, palette


def main():
    source, output = map(Path, sys.argv[1:3])
    payload = json.loads(source.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    report = {}

    class DiagramPoster(Scene):
        def construct(self):
            root, _, _, _, layout = build_scene(payload["scene"], payload["style"])
            self.add(root)
            report.update(layout)

    try:
        with tempconfig({"pixel_width": 1800, "pixel_height": 1200, "frame_width": 12, "frame_height": 8,
                         "background_color": palette(payload["style"])["bg"], "renderer": "cairo",
                         "save_last_frame": True, "write_to_movie": False, "disable_caching": True,
                         "media_dir": str(output), "output_file": "poster", "verbosity": "ERROR",
                         "text_dir": str(output / "texts")}):
            DiagramPoster().render()
        report.update(width=1800, height=1200, ok=True)
    except ValueError as exc:
        report = {"ok": False, "error": str(exc)[:400]}
    (output / "report.json").write_text(json.dumps(report), encoding="utf-8")
    if not report["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
