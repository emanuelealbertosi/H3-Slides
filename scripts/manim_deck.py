"""Trusted renderer. Reads JSON data, never executes LLM-generated Python."""
import json
import os
import sys
import textwrap
import math
from pathlib import Path
from manim import Text, FadeIn, FadeOut, VGroup, Group, ImageMobject, ManimColor, UP, DOWN, LEFT, RIGHT, RoundedRectangle, Arrow, Create
from manim_slides import Slide

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from h3_slides.diagram_spec import legacy_scene
from h3_slides.manim_scene import build_scene


def luminance(color):
    rgb = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
    return sum((v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4)*w
               for v, w in zip(rgb, [.2126, .7152, .0722]))


def contrast(a, b):
    return (max(luminance(a), luminance(b))+.05)/(min(luminance(a), luminance(b))+.05)


def auto_text(bg):
    dark, light = "#17243a", "#ffffff"
    a, b = contrast(bg, dark), contrast(bg, light)
    return dark if a >= 4.5 and a >= b else light if b >= 4.5 else "#000000"


def mix(a, b, ratio):
    return "#" + "".join(f"{int(int(a[i:i+2],16)*(1-ratio)+int(b[i:i+2],16)*ratio+.5):02x}" for i in (1,3,5))


class H3Deck(Slide):
    def diagram(self, spec, theme, font):
        labels = spec.get("labels", [])[:5]
        if spec.get("kind") not in ("flow", "cycle", "comparison") or len(labels) < 2:
            return VGroup(), VGroup()
        n = len(labels)
        nodes, arrows = VGroup(), VGroup()
        for i, label in enumerate(labels):
            if spec["kind"] == "flow":
                x, y, w, h = 0, 1.6-i*3.2/(n-1), 4.2, .58
            elif spec["kind"] == "cycle":
                angle = math.pi/2 - 2*math.pi*i/n
                x, y, w, h = 1.8*math.cos(angle), 1.36*math.sin(angle), 1.72, .58
            else:
                x, y, w, h = (0 if n == 2 else -1.35+(i%2)*2.7), (1-i*1.9 if n == 2 else 1.35-(i//2)*1.3), (4.5 if n == 2 else 2.45), 1.04
            box = RoundedRectangle(width=w, height=h, corner_radius=.1, color=theme[2], fill_color=theme[0], fill_opacity=1, stroke_width=2).move_to([x, y, 0])
            text = Text(textwrap.fill(label, width=16 if spec["kind"] == "cycle" else 25), font=font, font_size=19, color=theme[1])
            if text.width > w-.18:
                text.scale_to_fit_width(w-.18)
            if text.height > h-.14:
                text.scale_to_fit_height(h-.14)
            text.move_to(box)
            nodes.add(VGroup(box, text))
        if spec["kind"] != "comparison":
            for i in range(n if spec["kind"] == "cycle" else n-1):
                a, b = nodes[i][0], nodes[(i+1)%n][0]
                delta = b.get_center()-a.get_center()
                start = a.get_center()+delta/max(abs(delta[0])/(a.width/2+.04), abs(delta[1])/(a.height/2+.04))
                end = b.get_center()-delta/max(abs(delta[0])/(b.width/2+.04), abs(delta[1])/(b.height/2+.04))
                arrows.add(Arrow(start, end, buff=0, color=theme[2], stroke_width=2, max_tip_length_to_length_ratio=.2))
        group = VGroup(arrows, nodes).move_to([3.6, -.35, 0])
        return nodes, arrows

    def construct(self):
        project = json.loads(Path(os.environ["H3_SLIDES_SNAPSHOT"]).read_text(encoding="utf-8"))
        for slide in project["slides"]:
            content = slide["content"]
            base = {"ink": ("#141B2C", "#F6F7FB", "#B1F1CE"),
                     "paper": ("#FFFFFF", "#17243A", "#18794E"),
                     "forest": ("#153E35", "#F6FAF5", "#E2EDB0")}[project["theme"]]
            bg = project.get("background_color") or base[0]
            design = project.get("theme_design", {})
            theme = (bg, design.get("text_color") or auto_text(bg), project.get("accent_color") or base[2])
            font = project.get("font", "Arial")
            diagram = content.get("diagram", {})
            has_diagram = project.get("use_manim_diagrams") and (
                diagram.get("kind") == "manim" and bool(diagram.get("scene"))
                or diagram.get("kind") in ("flow", "cycle", "comparison") and len(diagram.get("labels", [])) >= 2
            )
            image_record = next((a for a in project.get("visual_assets", [])
                                 if a["id"] == content.get("image_id")), {})
            image_origin = image_record.get("origin", content.get("image_origin", "source"))
            image_id = content.get("image_id", "") if (
                image_origin != "source" or project.get("use_source_images", True)) and not has_diagram else ""
            placeholder = bool(content.get("image_placeholder") and not image_id and not has_diagram)
            has_visual = bool(image_id or has_diagram or placeholder)
            self.camera.background_color = ManimColor(theme[0])
            blocks = content.get("blocks", [])
            title = Text(content["title"], font=font, font_size=(design.get("title_size") or 46)*38/46,
                         weight="BOLD", color=design.get("title_color") or theme[1])
            if title.width > 12:
                title.scale_to_fit_width(12)
            title.to_edge(UP, buff=.55)
            points = VGroup()
            width = 6.1 if has_visual else 11.8
            for point in ([] if blocks else ([content["subtitle"]] if content["subtitle"] else []) + content["bullets"]):
                text = Text(textwrap.fill(point, width=38 if has_visual else 72),
                            font=font, font_size=(design.get("body_size") or 26)*24/26, color=theme[1])
                if text.width > width:
                    text.scale_to_fit_width(width)
                points.add(text)
            if blocks:
                columns = 1 if len(blocks) == 1 else 2
                rows = math.ceil(len(blocks)/columns)
                area_width = 9 if has_visual else 12.4
                box_width = (area_width-.22*(columns-1))/columns
                box_height = (4.8-.22*(rows-1))/rows
                colors = {"explanation": "#E0F2E8", "example": "#DCEEFF", "key": "#FFF0C2", "quote": "#EEE2FF"}
                for i, block in enumerate(blocks):
                    tint = .9 if i % 2 else .78
                    accent_tint = mix(theme[2], "#ffffff", tint)
                    fill = design.get(block["kind"]+"_color") or (accent_tint if block["kind"] == "explanation" else colors.get(block["kind"], "#E0F2E8"))
                    foreground = design.get("box_text_color") or auto_text(fill)
                    border = design.get("border_color") or mix(fill, foreground, .3)
                    box = RoundedRectangle(width=box_width, height=box_height, corner_radius=design.get("box_radius",18)/120,
                        fill_color=fill, color=border, fill_opacity=1, stroke_width=design.get("border_width",0))
                    copy = VGroup()
                    for value, size, weight in [(block["heading"], 21, "BOLD"), (block["text"], (design.get("body_size") or 22)*19/22, "NORMAL"),
                                                 (block.get("source", ""), 11, "NORMAL")]:
                        if not value:
                            continue
                        wrapped = "\n".join(textwrap.fill(p, width=max(24, int(box_width*9))) for p in value.splitlines())
                        text = Text(wrapped, font=font, font_size=size, weight=weight, color=foreground)
                        if text.width > box_width-.45:
                            text.scale_to_fit_width(box_width-.45)
                        copy.add(text)
                    copy.arrange(DOWN, aligned_edge=LEFT, buff=.18)
                    if copy.height > box_height-.42:
                        raise ValueError("Il testo supera un box Manim: dividi il paragrafo prima di esportare")
                    copy.move_to(box.get_corner(UP+LEFT)+RIGHT*.23+DOWN*.23, aligned_edge=UP+LEFT)
                    group = VGroup(box, copy).move_to([-6.2+box_width/2+(i%columns)*(box_width+.22),
                                                      1.8-box_height/2-(i//columns)*(box_height+.22), 0])
                    points.add(group)
                if content["subtitle"]:
                    subtitle = Text(content["subtitle"], font=font, font_size=20, color=theme[1])
                    if subtitle.width > 12:
                        subtitle.scale_to_fit_width(12)
                    subtitle.move_to([0, 2.15, 0])
                    title = VGroup(title, subtitle)
            elif len(points):
                points.arrange(DOWN, aligned_edge=LEFT, buff=.28)
                if points.height > 5:
                    points.scale_to_fit_height(5)
                points.next_to(title, DOWN, buff=.4).to_edge(LEFT, buff=.65)
            elements = Group(title, points)
            self.play(FadeIn(title), run_time=.4)
            if image_id:
                image = ImageMobject(str(Path(os.environ["H3_SLIDES_ASSETS"]) / image_id))
                image.scale_to_fit_width(3.2 if blocks else 5)
                if image.height > 4.8:
                    image.scale_to_fit_height(4.8)
                image.to_edge(RIGHT, buff=.55).shift(DOWN * .35)
                elements.add(image)
                self.play(FadeIn(image), run_time=.35)
                if image_record.get("origin") == "web":
                    attribution = " · ".join(filter(None, [image_record.get("author", ""),
                        image_record.get("license", ""), "Wikimedia Commons"]))
                    credit = Text(textwrap.fill(attribution, width=64), font=font, font_size=11, color=theme[1])
                    if credit.width > 5:
                        credit.scale_to_fit_width(5)
                    credit.next_to(image, DOWN, buff=.10)
                    if credit.get_bottom()[1] < -3.6:
                        credit.shift(UP * (-3.6-credit.get_bottom()[1]))
                    elements.add(credit)
                    self.add(credit)
            if placeholder:
                box = RoundedRectangle(width=3.2 if blocks else 5, height=3.4, corner_radius=.15,
                    color=theme[2], fill_color=theme[0], fill_opacity=1).to_edge(RIGHT, buff=.55).shift(DOWN*.35)
                label = Text(textwrap.fill("Immagine da inserire\n"+content.get("image_query", ""), width=25),
                             font=font, font_size=20, color=theme[1])
                if label.width > box.width-.4:
                    label.scale_to_fit_width(box.width-.4)
                if label.height > box.height-.4:
                    label.scale_to_fit_height(box.height-.4)
                label.move_to(box)
                visual = VGroup(box, label)
                elements.add(visual)
                self.play(FadeIn(visual), run_time=.35)
            if has_diagram:
                scene = diagram.get("scene") if diagram.get("kind") == "manim" else legacy_scene(diagram).model_dump()
                diagram_root, diagram_header, diagram_footer, stages, _ = build_scene(scene, project)
                diagram_root.scale(.47).move_to([3.55, -.32, 0])
                elements.add(diagram_root)
                self.play(FadeIn(diagram_header), run_time=.3)
                for _, nodes, links in stages:
                    if len(nodes):
                        self.play(*[FadeIn(node) for node in nodes], run_time=.32)
                    if len(links):
                        self.play(*[Create(link) for link in links], run_time=.28)
                if len(diagram_footer):
                    self.play(FadeIn(diagram_footer), run_time=.25)
            for text in points:
                self.play(FadeIn(text), run_time=.35)
                if content["animation"] == "reveal":
                    self.wait(.15)
                    self.next_slide()
            self.wait(.6)
            self.next_slide()
            self.play(FadeOut(elements), run_time=.25)
