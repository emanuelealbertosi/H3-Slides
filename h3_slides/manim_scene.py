"""Trusted Manim scene compiler. All input is validated data, not executable code."""
import math
import textwrap
import numpy as np
from manim import (VGroup, Text, RoundedRectangle, Rectangle, Ellipse, Polygon,
                   Line, Arrow, VMobject, Dot, Axes, ManimColor, interpolate_color)
from .diagram_spec import ManimSceneSpec
from .diagram_layout import bounds, route_connection


def point(x, y):
    return np.array([x-6, 4-y, 0.])


def mix(a, b, amount):
    return interpolate_color(ManimColor(a), ManimColor(b), amount).to_hex()


def palette(project):
    bases = {"ink": "#141b2c", "paper": "#ffffff", "forest": "#153e35"}
    bg = project.get("background_color") or bases.get(project.get("theme"), "#141b2c")
    components = [int(bg[i:i+2], 16)/255 for i in (1, 3, 5)]
    lum = sum((v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4)*w for v, w in zip(components, (.2126, .7152, .0722)))
    dark = lum < .179
    fg = "#f6f7fb" if dark else "#17243a"
    return {"bg": bg, "fg": fg, "muted": mix(bg, fg, .7),
            "accent": project.get("accent_color") or ("#75dbb6" if dark else "#15775b"),
            "blue": "#78b9fa" if dark else "#2261a6", "amber": "#f3c36a" if dark else "#936009",
            "red": "#f68b91" if dark else "#b33c48", "violet": "#bba2fa" if dark else "#7950b6",
            "neutral": mix(bg, fg, .65)}


def build_scene(value, project):
    spec = ManimSceneSpec.model_validate(value)
    colors = palette(project)
    font = project.get("font", "Arial")
    if font not in ("Arial", "Calibri", "Segoe UI", "Georgia", "Verdana", "Consolas"):
        font = "Arial"
    texts, shortened_texts = [], 0

    def copy(value, width, height, size=30, minimum=22, bold=False):
        nonlocal shortened_texts
        source = " ".join(value.split())
        limits = [len(source), 60, 48, 36, 28, 22, 16, 12, 8, 5, 2]
        tried = set()
        for limit in limits:
            if limit in tried or limit > len(source):
                continue
            tried.add(limit)
            candidate_text = source if limit == len(source) else _shorten_for_render(source, limit)
            for candidate in range(size, minimum-1, -2):
                wrap = max(4, int(width/(candidate/150)))
                wrapped = "\n".join(textwrap.fill(line, width=wrap, break_long_words=False)
                                    for line in candidate_text.splitlines())
                label = Text(wrapped, font=font, font_size=candidate, weight="BOLD" if bold else "NORMAL",
                             color=colors["fg"], line_spacing=.65)
                if label.width <= width and label.height <= height:
                    texts.append((label, candidate))
                    shortened_texts += candidate_text != source
                    return label
        raise ValueError("Testo non leggibile nello spazio assegnato: abbrevia le etichette o ingrandisci gli elementi")

    title = copy(spec.title, 11.1, .65, size=36, minimum=28, bold=True).move_to(point(6, .43))
    rule = Line(point(.35, .88), point(11.65, .88), color=colors["accent"], stroke_width=2)
    header = VGroup(title, rule)
    footer = VGroup()
    if spec.takeaway:
        label = copy(spec.takeaway, 10.8, .45, size=24, minimum=22)
        label.move_to(point(6, 7.68))
        footer.add(RoundedRectangle(width=11.4, height=.55, corner_radius=.1,
                   fill_color=mix(colors["bg"], colors["accent"], .13), fill_opacity=1, stroke_width=0).move_to(label), label)
    objects = {}
    for element in spec.elements:
        e, tone = element, colors[element.tone]
        w, h = e.width, e.height
        group = VGroup()
        if e.type in ("grid", "bars", "plot"):
            panel = RoundedRectangle(width=w, height=h, corner_radius=.13, stroke_width=1.5,
                color=mix(colors["bg"], tone, .55), fill_color=mix(colors["bg"], tone, .055), fill_opacity=1)
            group.add(panel)
            if e.text:
                label = copy(e.text, w-.35, .48, size=28, minimum=24, bold=True).move_to([0, h/2-.34, 0])
                group.add(label)
            if e.caption:
                label = copy(e.caption, w-.35, .43, size=22, minimum=20).move_to([0, -h/2+.27, 0])
                label.set_color(colors["muted"]); group.add(label)
            inner_w, inner_h = w-.75, h-1.4
            if inner_h < .9:
                raise ValueError(f"Grafico {e.id}: aumenta height almeno a 2.5")
            if e.type == "grid":
                rows = len(e.values)//e.columns
                size = min(inner_w/e.columns, inner_h/rows)
                for i, value in enumerate(e.values):
                    x = (i % e.columns-(e.columns-1)/2)*size
                    y = ((rows-1)/2-i//e.columns)*size-.05
                    cell = Rectangle(width=size*.96, height=size*.96, stroke_width=1,
                                     stroke_color=mix(colors["bg"], colors["fg"], .35),
                                     fill_color=mix(colors["bg"], tone, .12+.88*value), fill_opacity=1).move_to([x, y, 0])
                    group.add(cell)
                    if len(e.values) <= 16 and size >= .55:
                        digit = copy(f"{value:g}", size-.1, size-.1, size=22, minimum=20).move_to(cell)
                        group.add(digit)
            elif e.type == "bars":
                count, maximum = len(e.values), max(e.values)
                chart_h = inner_h-.5
                baseline = -inner_h/2+.2
                group.add(Line([-inner_w/2, baseline, 0], [inner_w/2, baseline, 0],
                               color=colors["muted"], stroke_width=2))
                for i, value in enumerate(e.values):
                    step = inner_w/count
                    x = -inner_w/2+(i+.5)*step
                    bh = max(.015, chart_h*value/maximum)
                    bar = Rectangle(width=step*.56, height=bh, stroke_width=0,
                                    fill_color=mix(colors["bg"], tone, .65+.3*i/max(1, count-1)), fill_opacity=1).move_to([x, baseline+bh/2, 0])
                    label = copy(e.labels[i], step-.1, .4, size=22, minimum=20).move_to([x, baseline-.28, 0])
                    number = copy(f"{value:g}", step-.05, .35, size=22, minimum=20).move_to([x, baseline+bh+.19, 0])
                    group.add(bar, label, number)
            else:
                lo, hi = min(0, min(e.values)), max(e.values)
                if hi <= lo:
                    hi = lo+1
                axes = Axes(x_range=[0, len(e.values)-1, max(1, len(e.values)//6)],
                            y_range=[lo, hi, max((hi-lo)/4, 1e-8)], x_length=inner_w-.3, y_length=inner_h-.15,
                            axis_config={"include_tip": False, "color": colors["muted"], "stroke_width": 2,
                                         "include_ticks": False}).move_to([0, -.08, 0])
                pts = [axes.c2p(i, v) for i, v in enumerate(e.values)]
                curve = VMobject(color=tone, stroke_width=4).set_points_as_corners(pts)
                dots = VGroup(*[Dot(p, radius=.038, color=tone) for p in pts])
                group.add(axes, curve, dots)
                for value in (lo, hi):
                    number = copy(f"{value:g}", .65, .3, size=20, minimum=20).next_to(axes.c2p(0, value), [-1, 0, 0], buff=.05)
                    group.add(number)
        else:
            fill = mix(colors["bg"], tone, .12)
            if e.type == "decision":
                shape = Polygon([0, h/2, 0], [w/2, 0, 0], [0, -h/2, 0], [-w/2, 0, 0])
            elif e.type == "circle":
                shape = Ellipse(width=w, height=h)
            elif e.type == "document":
                fold = min(.35, h*.2)
                shape = Polygon([-w/2, -h/2, 0], [w/2, -h/2, 0], [w/2, h/2-fold, 0],
                                [w/2-fold, h/2, 0], [-w/2, h/2, 0])
            else:
                shape = RoundedRectangle(width=w, height=h, corner_radius=min(.15, h*.15))
            if e.type != "text":
                shape.set_fill(fill, opacity=1).set_stroke(tone, width=2.5)
                group.add(shape)
                if e.type == "database":
                    group.add(Ellipse(width=w, height=min(.35, h*.25), color=tone,
                                      fill_color=mix(colors["bg"], tone, .2), fill_opacity=1, stroke_width=2).move_to([0, h/2-.12, 0]))
                if e.type == "document":
                    group.add(Line([w/2-fold, h/2, 0], [w/2-fold, h/2-fold, 0], color=tone, stroke_width=2),
                              Line([w/2-fold, h/2-fold, 0], [w/2, h/2-fold, 0], color=tone, stroke_width=2))
            inside_w = w*(.62 if e.type in ("decision", "circle") else .86)
            inside_h = h*(.53 if e.type == "decision" else .76)
            label = copy(e.text, inside_w, inside_h*(.6 if e.caption else 1), size=30, minimum=24, bold=e.type != "text")
            if e.caption:
                caption = copy(e.caption, inside_w, inside_h*.38, size=22, minimum=20)
                caption.set_color(colors["muted"])
                group.add(VGroup(label, caption).arrange([0, -1, 0], buff=.1))
            else:
                group.add(label)
        group.move_to(point(e.x, e.y))
        if group.width > w+.08 or group.height > h+.08:
            raise ValueError(f"Contenuto di {e.id} fuori dall'ingombro: aumenta width/height")
        objects[e.id] = group
    links, occupied = [], [bounds(e, .025) for e in spec.elements]
    by_id = {e.id: e for e in spec.elements}
    for edge in spec.connections:
        route = route_connection(by_id[edge.source], by_id[edge.target], spec.elements)
        tone = colors[edge.tone]
        pts = [point(*p) for p in route]
        line = VMobject(color=tone, stroke_width=3).set_points_as_corners(pts)
        arrow = Arrow(pts[-2], pts[-1], buff=0, color=tone, stroke_width=3,
                      tip_length=.13, max_tip_length_to_length_ratio=.5)
        visual = VGroup(line, arrow)
        if edge.label:
            label = copy(edge.label, 2.5, .7, size=22, minimum=20)
            placed = False
            for a, b in sorted(zip(route, route[1:]), key=lambda pair: -math.dist(*pair)):
                for t in (.5, .3, .7):
                    x, y = a[0]*(1-t)+b[0]*t, a[1]*(1-t)+b[1]*t
                    x += label.width/2+.13 if abs(a[0]-b[0]) < .001 else 0
                    y -= label.height/2+.12 if abs(a[1]-b[1]) < .001 else 0
                    box = x-label.width/2-.04, y-label.height/2-.04, x+label.width/2+.04, y+label.height/2+.04
                    if box[0] < .05 or box[2] > 11.95 or box[1] < .95 or box[3] > 7.35:
                        continue
                    if any(box[0] < other[2] and box[2] > other[0] and box[1] < other[3] and box[3] > other[1] for other in occupied):
                        continue
                    label.move_to(point(x, y)); occupied.append(box); placed = True; break
                if placed:
                    break
            if not placed:
                raise ValueError("Non c'è spazio per l'etichetta di una freccia: allontana gli elementi o abbrevia la relazione")
            backing = RoundedRectangle(width=label.width+.10, height=label.height+.08, corner_radius=.035,
                         fill_color=colors["bg"], fill_opacity=1, stroke_width=0).move_to(label)
            visual.add(backing, label)
        stage = max(by_id[edge.source].stage, by_id[edge.target].stage)
        links.append((stage, visual))
    root = VGroup(header, *[link for _, link in links], *objects.values(), footer)
    stages = [(stage, VGroup(*[objects[e.id] for e in spec.elements if e.stage == stage]),
               VGroup(*[link for when, link in links if when == stage])) for stage in sorted({e.stage for e in spec.elements})]
    for label, size in texts:
        if label.get_left()[0] < -5.97 or label.get_right()[0] > 5.97 or label.get_top()[1] > 3.99 or label.get_bottom()[1] < -3.99:
            raise ValueError("Testo fuori dal canvas Manim")
    report = {"engine": "manim", "elements": len(objects), "connections": len(links),
              "min_font_size": min(size for _, size in texts), "text_count": len(texts),
              "shortened_texts": shortened_texts, "bounds_checked": True,
              "types": sorted({e.type for e in spec.elements})}
    return root, header, footer, stages, report


def _shorten_for_render(value, limit):
    if len(value) <= limit:
        return value
    prefix = value[:limit-1].rstrip()
    if " " in prefix and len(prefix.rsplit(" ", 1)[0]) >= max(2, limit//2):
        prefix = prefix.rsplit(" ", 1)[0]
    return prefix.rstrip(" ,;:-") + "…"
