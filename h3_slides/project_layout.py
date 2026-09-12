"""Atomic, geometry-only project format updates; no storage or rendering I/O."""
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field

from .models import FreePlacement, SlideEdit


class _LayoutUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, strict=True)
    revision: int = Field(ge=0, strict=True)
    canvas_height: int = Field(ge=720, le=1008, strict=True)
    freeform: dict[str, FreePlacement] = Field(max_length=12)


def apply_layout_updates(project, updates, canvas_mode=None):
    """Validate every change before mutating the in-memory project.

    Rows contain only id, revision, canvas_height and freeform. Saved text,
    diagrams, media and layout choices remain untouched; only changed slide
    geometry increments its revision. With an explicit canvas_mode, untouched
    slides are checked too, and fixed format resets their height to 720.
    Legacy freeform coordinates retained under automatic layouts are inactive.
    The project mode is changed only when canvas_mode is explicitly supplied.
    The caller owns persistence and must not save until this function succeeds.
    """
    if not isinstance(updates, list) or len(updates) > 30:
        raise ValueError("Le geometrie delle slide devono essere un elenco di massimo 30 elementi")
    target_mode = canvas_mode if canvas_mode is not None else project.get("canvas_mode", "fixed")
    if target_mode not in ("fixed", "adaptive"):
        raise ValueError("Formato slide non valido: scegli fixed oppure adaptive")

    rows = [_LayoutUpdate.model_validate(row) for row in updates]
    by_id = {slide["id"]: slide for slide in project.get("slides", [])}
    changes = {}
    for row in rows:
        if row.id in changes:
            raise ValueError(f"Slide {row.id}: geometria presente più di una volta")
        if row.id not in by_id:
            raise ValueError(f"Slide {row.id}: non appartiene a questo progetto")
        slide = by_id[row.id]
        if slide.get("revision", 0) != row.revision:
            raise ValueError(f"Slide {row.id} aggiornata altrove: ricarica prima di cambiare formato")
        if target_mode == "fixed" and row.canvas_height != 720:
            raise ValueError(f"Slide {row.id}: il formato fisso 16:9 richiede un'altezza di 720 px")
        content = deepcopy(slide["content"])
        content.update(canvas_height=row.canvas_height,
                       freeform={key: value.model_dump() for key, value in row.freeform.items()})
        SlideEdit.model_validate({"revision": row.revision, "content": content})
        changes[row.id] = content

    if canvas_mode is not None:
        for sid, slide in by_id.items():
            if sid in changes:
                continue
            content = deepcopy(slide["content"])
            if target_mode == "fixed":
                content["canvas_height"] = 720
            try:
                SlideEdit.model_validate({"revision": slide.get("revision", 0), "content": content})
            except ValueError as exc:
                raise ValueError(f"Slide {sid}: adatta il layout prima di cambiare formato. {exc}") from exc
            changes[sid] = content

    # No project or nested slide state has been mutated before this point.
    for sid, content in changes.items():
        slide = by_id[sid]
        if content != slide["content"]:
            slide["content"] = content
            slide["revision"] = slide.get("revision", 0) + 1
    if canvas_mode is not None:
        project["canvas_mode"] = target_mode
    return project
