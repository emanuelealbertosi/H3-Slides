"""Measured, lossless labels and aligned node reflow on the trusted Manim canvas."""
import math
import textwrap
from functools import lru_cache
from manim import Text
from .diagram_spec import ManimSceneSpec


@lru_cache(maxsize=256)
def _label(text, font, color, size, bold):
    return Text(text, font=font, font_size=size, weight="BOLD" if bold else "NORMAL",
                color=color, line_spacing=.7)


def fit_text(value, width, height, *, font, color, size=30, minimum=20, bold=False):
    source = str(value).strip()
    sizes = list(dict.fromkeys([*range(size, minimum-1, -2), minimum]))
    for candidate in sizes:
        single = _label(source, font, color, candidate, bold)
        if single.width <= width and single.height <= height:
            return single.copy(), candidate
        if single.height > height:
            continue
        # Estimate from the actual font, then try progressively shorter lines.
        longest = max((len(line) for line in source.splitlines()), default=1)
        budget = max(1, min(longest, int(longest*width/max(single.width, .001))))
        seen = {source}
        for factor in (1, .85, .7, .55):
            wrapped = "\n".join(textwrap.fill(line, width=max(1, int(budget*factor)),
                                break_long_words=False, break_on_hyphens=False)
                                for line in source.splitlines())
            if wrapped in seen:
                continue
            seen.add(wrapped)
            # A conservative line-height lower bound avoids compiling dozens
            # of wraps that cannot possibly fit into a short node.
            if len(source.splitlines()) == 1 and len(wrapped.splitlines())*single.height > height*1.1:
                continue
            label = _label(wrapped, font, color, candidate, bold)
            if label.width <= width and label.height <= height:
                return label.copy(), candidate
    raise ValueError("Testo completo non leggibile nello spazio assegnato: ingrandisci e riallinea gli elementi; "
                     "non abbreviare né eliminare etichette")


ATOMIC = {"box", "decision", "circle", "database", "document", "text"}


def node_text_layout(e, width, height, measure):
    """Give captions the space left by the measured title, not a fixed 38%."""
    inner_w = width*(.62 if e.type in ("decision", "circle") else .86)
    inner_h = height*(.53 if e.type == "decision" else .76)
    if not e.caption:
        return measure(e.text, inner_w, inner_h, 30, 20, e.type != "text"), None
    error = None
    for fraction in (.6, .4, .25):
        try:
            title = measure(e.text, inner_w, inner_h*fraction, 30, 20, e.type != "text")
            caption = measure(e.caption, inner_w, inner_h-title[0].height-.1, 22, 20, False)
            return title, caption
        except ValueError as exc:
            error = exc
    raise error


def reflow_text_nodes(spec, measure):
    """Only reflow when full text cannot fit. Preserve IDs, shapes, edges and order."""
    def fits(e, width, height):
        try:
            node_text_layout(e, width, height, measure)
            return True
        except ValueError:
            return False

    atomic = [e for e in spec.elements if e.type in ATOMIC]
    failed = [e for e in atomic if not fits(e, e.width, e.height)]
    if not failed:
        return spec, False
    # First enlarge in place: common rows stay perfectly aligned and unrelated
    # charts retain their geometry. Strict validation checks every candidate.
    grown = spec.model_copy(deep=True)
    for original in failed:
        node = next(e for e in grown.elements if e.id == original.id)
        possibilities = sorted({(min(11, node.width*wf), min(6, node.height*hf))
                                for wf in (1, 1.25, 1.6, 2) for hf in (1, 1.3, 1.7, 2.3)},
                               key=lambda pair: pair[0]*pair[1])
        for w, h in possibilities:
            candidate = grown.model_copy(deep=True)
            target = next(e for e in candidate.elements if e.id == node.id)
            target.width, target.height = w, h
            try:
                candidate = ManimSceneSpec.model_validate(candidate.model_dump())
            except ValueError:
                continue
            if fits(target, w, h):
                grown = candidate
                break
    if all(fits(e, e.width, e.height) for e in grown.elements if e.type in ATOMIC):
        return grown, True
    if len(atomic) != len(spec.elements):
        # A mixed chart needs a meaningful redesign, not arbitrary squeezing.
        return grown, True
    ordered = sorted(spec.elements, key=lambda e: (round(e.y, 1), e.x))
    for columns in (2, 1, 3, 4):
        if columns > len(ordered):
            continue
        width = min(11, (11.4-.45*(columns-1))/columns)
        rows = math.ceil(len(ordered)/columns)
        max_height = min(6, (6.05-.5*(rows-1))/rows)
        if max_height <= 0:
            continue
        if not all(fits(e, width, max_height) for e in ordered):
            continue
        candidate = spec.model_copy(deep=True)
        by_id = {e.id: e for e in candidate.elements}
        for i, original in enumerate(ordered):
            row, column = divmod(i, columns)
            count = min(columns, len(ordered)-row*columns)
            element = by_id[original.id]
            element.width, element.height = width, max_height
            element.x = 6+(column-(count-1)/2)*(width+.45)
            element.y = 1.1+max_height/2+row*(max_height+.5)
        return ManimSceneSpec.model_validate(candidate.model_dump()), True
    raise ValueError("Testi completi troppo densi: riprogetta i nodi e le righe con spazio sufficiente; "
                     "nessuna etichetta è stata tagliata")
