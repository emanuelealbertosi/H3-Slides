"""Deterministic pagination, preserving literal text and citations."""
from copy import deepcopy
import re
from .models import SlideContent


def split_content(raw):
    content = SlideContent.model_validate(raw).model_dump()
    pieces = []
    if content["blocks"]:
        for block in content["blocks"]:
            text = block["text"]
            while text:
                if len(text) <= 600:
                    cut = len(text)
                else:
                    ends = [m.end() for m in re.finditer(r'[.!?][\"»”)]*\s+', text[:601]) if m.end() >= 200]
                    spaces = [m.end() for m in re.finditer(r"\s+", text[:601])]
                    later = re.search(r"\s+", text[600:])
                    cut = ends[-1] if ends else spaces[-1] if spaces else 600+later.end() if later else len(text)
                part = deepcopy(content)
                part.update(blocks=[{**block, "text": text[:cut]}], layout="content", layout_variant=0)
                pieces.append(part)
                text = text[cut:]
    elif len(content["bullets"]) > 1:
        middle = (len(content["bullets"])+1)//2
        for bullets in (content["bullets"][:middle], content["bullets"][middle:]):
            part = deepcopy(content)
            part.update(bullets=bullets, layout="content", layout_variant=0)
            pieces.append(part)
    if len(pieces) < 2:
        raise ValueError("Non ci sono più paragrafi o abbastanza testo da dividere. Modifica la slide.")
    return pieces
