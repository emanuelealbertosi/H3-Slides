"""Trusted renderer. Reads JSON data, never executes LLM-generated Python."""
import json
import os
import textwrap
from pathlib import Path
from manim import Text, FadeIn, FadeOut, VGroup, Group, ImageMobject, ManimColor, UP, DOWN, LEFT, RIGHT
from manim_slides import Slide


class H3Deck(Slide):
    def construct(self):
        project = json.loads(Path(os.environ["H3_SLIDES_SNAPSHOT"]).read_text(encoding="utf-8"))
        for slide in project["slides"]:
            content = slide["content"]
            theme = {"ink": ("#141B2C", "#F6F7FB", "#B1F1CE"),
                     "paper": ("#FFFFFF", "#17243A", "#18794E"),
                     "forest": ("#153E35", "#F6FAF5", "#E2EDB0")}[project["theme"]]
            self.camera.background_color = ManimColor(theme[0])
            title = Text(content["title"], font="Arial", font_size=38, color=theme[2])
            if title.width > 12:
                title.scale_to_fit_width(12)
            title.to_edge(UP, buff=.55)
            points = VGroup()
            width = 6.5 if content["image_id"] else 11.8
            for point in ([content["subtitle"]] if content["subtitle"] else []) + content["bullets"]:
                text = Text(textwrap.fill(point, width=42 if content["image_id"] else 72),
                            font="Arial", font_size=24, color=theme[1])
                if text.width > width:
                    text.scale_to_fit_width(width)
                points.add(text)
            if len(points):
                points.arrange(DOWN, aligned_edge=LEFT, buff=.28)
                if points.height > 5:
                    points.scale_to_fit_height(5)
                points.next_to(title, DOWN, buff=.4).to_edge(LEFT, buff=.65)
            elements = Group(title, points)
            self.play(FadeIn(title), run_time=.4)
            if content["image_id"]:
                image = ImageMobject(str(Path(os.environ["H3_SLIDES_ASSETS"]) / content["image_id"]))
                image.scale_to_fit_width(5)
                if image.height > 4.8:
                    image.scale_to_fit_height(4.8)
                image.to_edge(RIGHT, buff=.55).shift(DOWN * .35)
                elements.add(image)
                self.play(FadeIn(image), run_time=.35)
            for text in points:
                self.play(FadeIn(text), run_time=.35)
                if content["animation"] == "reveal":
                    self.wait(.15)
                    self.next_slide()
            self.wait(.6)
            self.next_slide()
            self.play(FadeOut(elements), run_time=.25)
