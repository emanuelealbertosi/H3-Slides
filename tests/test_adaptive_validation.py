"""New writes use the actual canvas; legacy slide reads remain recoverable."""
import copy

import pytest
from pydantic import ValidationError

from h3_slides.models import FreePlacement, SlideContent, SlideEdit


def free_content(*, height=720, y=600, h=80, layout="freeform"):
    return {
        "title": "Una slide adattiva",
        "canvas_height": height,
        "layout": layout,
        "blocks": [{"text": "Testo conservato senza modifiche."}],
        "freeform": {"block-0": {"x": 48, "y": y, "w": 500, "h": h}},
    }


def test_new_slide_edit_rejects_position_beyond_its_canvas():
    raw = free_content(height=720, y=900, h=60)
    with pytest.raises(ValidationError, match=r"block-0.*canvas utile.*680 px"):
        SlideEdit.model_validate({"revision": 1, "content": raw})


@pytest.mark.parametrize("height", [720, 792, 864, 936, 1008, 1152, 1296, 1440])
def test_new_slide_edit_accepts_exact_useful_bottom(height):
    edit = SlideEdit.model_validate({
        "revision": 1,
        "content": free_content(height=height, y=height - 120, h=80),
    })
    assert edit.content.freeform["block-0"].y + edit.content.freeform["block-0"].h == height - 40


@pytest.mark.parametrize("height", [720, 792, 864, 936, 1152, 1296])
def test_footer_reserve_applies_to_every_canvas_height(height):
    with pytest.raises(ValidationError, match="canvas utile"):
        SlideEdit.model_validate({
            "revision": 1,
            "content": free_content(height=height, y=height - 119, h=80),
        })


def test_adaptive_936_geometry_can_be_saved_but_not_reused_on_fixed_720():
    raw = free_content(height=936, y=800, h=96)
    SlideEdit.model_validate({"revision": 2, "content": raw})
    raw["canvas_height"] = 720
    with pytest.raises(ValidationError, match="canvas utile"):
        SlideEdit.model_validate({"revision": 2, "content": raw})


@pytest.mark.parametrize("layout", ["content", "editorial", "cards", "visual-bottom"])
def test_inactive_freeform_stash_does_not_block_automatic_layout_edit(layout):
    raw = free_content(height=720, y=900, h=60, layout=layout)
    edit = SlideEdit.model_validate({"revision": 1, "content": raw})
    assert edit.content.freeform["block-0"].y == 900


def test_legacy_read_does_not_reject_or_silently_reposition_saved_content():
    raw = free_content(height=720, y=900, h=60)
    before = copy.deepcopy(raw)
    content = SlideContent.model_validate(raw)
    assert raw == before
    assert content.freeform["block-0"].y == 900
    assert content.canvas_height == 720
    with pytest.raises(ValueError, match="canvas utile"):
        content.validate_canvas_geometry()


def test_geometry_validation_returns_same_content_without_mutation():
    content = SlideContent.model_validate(free_content(height=936, y=800, h=96))
    before = content.model_dump()
    assert content.validate_canvas_geometry() is content
    assert content.model_dump() == before


def test_legacy_slide_can_be_repaired_and_saved():
    content = SlideContent.model_validate(free_content(height=720, y=900, h=60))
    content.freeform["block-0"].y = 620
    edit = SlideEdit(revision=4, content=content)
    assert edit.content.freeform["block-0"].y == 620


@pytest.mark.parametrize("geometry", [
    {"x": 1200, "y": 200, "w": 100, "h": 100},
    {"x": 48, "y": 1332, "w": 500, "h": 69},
    {"x": -1, "y": 200, "w": 500, "h": 80},
    {"x": 48, "y": -1, "w": 500, "h": 80},
    {"x": 48, "y": 200, "w": 79, "h": 80},
    {"x": 48, "y": 200, "w": 500, "h": 43},
])
def test_absolute_freeplacement_safety_limits(geometry):
    with pytest.raises(ValidationError):
        FreePlacement.model_validate(geometry)


@pytest.mark.parametrize("height", [719, 1441])
def test_canvas_height_safety_limits(height):
    with pytest.raises(ValidationError):
        SlideContent.model_validate(free_content(height=height))


def test_empty_freeform_layout_remains_valid_for_editor_to_initialize():
    edit = SlideEdit(revision=0, content={"title": "Da posizionare", "layout": "freeform"})
    assert edit.content.freeform == {}
