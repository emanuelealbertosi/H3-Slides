import pytest

from h3_slides.page_layout import _parts
from h3_slides.page_v2 import PageNode


@pytest.mark.parametrize("formula", [
    r"\(f(x) = \frac{1}{x} + \sqrt{x}\)",
    "\\[\\begin{aligned}\ny &= 1/x \\\\\nz &= x + 2\n\\end{aligned}\\]",
    "$$f(x) = x + 1$$", "$x + y = z$", chr(96) + "long_function(x, y)" + chr(96),
    chr(96)*3 + "python\nx = 1\nprint(x)\n" + chr(96)*3,
])
def test_continuation_keeps_formula_or_code_markup_together(formula):
    original = "Prima " * 16 + formula + " Dopo" * 40
    node = PageNode(id="body", kind="text", text=original)
    parts = _parts(node, 110, {"body"})
    assert len(parts) > 1
    assert "".join(part.text for part in parts) == original
    assert sum(formula in part.text for part in parts) == 1
