import math

import pytest

from h3_slides.math_expression import compile_expression, sample_expression, validate_expression


def assert_separated(segments, poles):
    assert segments
    for pole in poles:
        assert any(segment[-1][0] < pole for segment in segments)
        assert any(segment[0][0] > pole for segment in segments)
        assert all(not (segment[0][0] <= pole <= segment[-1][0]) for segment in segments)
    assert all(math.isfinite(y) for segment in segments for _, y in segment)


@pytest.mark.parametrize("expression,poles", [
    ("1/(x-0.123)", [.123]),
    ("1/(x-.123)^2", [.123]),
    ("1/((x-.123)*(x-.123))", [.123]),
    ("1/(x*x-1)", [-1, 1]),
    ("1/x", [0]),
    ("x^-1", [0]),
    ("1/(x^12-1)", [-1, 1]),
])
def test_undeclared_polynomial_poles_split_even_on_wide_vertical_domain(expression, poles):
    segments = sample_expression(expression, -2, 2, -1e9, 1e9)
    assert_separated(segments, poles)
    assert len(segments) == len(poles)+1


def test_removable_rational_hole_is_not_connected():
    segments = sample_expression("(x*x-1)/(x-1)", -2, 2, -1e9, 1e9)
    assert_separated(segments, [1])
    assert len(segments) == 2


@pytest.mark.parametrize("expression,offset,slope", [
    ("tan(x)", 0, 1), ("tan(2*x+.3)", .3, 2), ("tan(-2*x+.3)", .3, -2),
])
def test_affine_tangent_poles_are_split_without_user_supplied_asymptotes(expression, offset, slope):
    poles = sorted((math.pi/2+k*math.pi-offset)/slope for k in range(-5, 6)
                   if -2 < (math.pi/2+k*math.pi-offset)/slope < 2)
    segments = sample_expression(expression, -2, 2, -1e9, 1e9)
    assert_separated(segments, poles)
    assert len(segments) == len(poles)+1


@pytest.mark.parametrize("expression", ["x^3", "sin(x)", "1/(x*x+1)"])
def test_continuous_curves_keep_one_segment(expression):
    segments = sample_expression(expression, -2, 2, -1e9, 1e9)
    assert len(segments) == 1
    assert len(segments[0]) == 401


def test_small_complex_denominator_roots_are_not_mislabeled_real_poles():
    # The roots are +/-1e-10j. A tolerance on the imaginary part would invent
    # a discontinuity at zero even though the function is continuous there.
    segments = sample_expression("1/(x*x+1e-20)", -2, 2, -1e22, 1e22)
    assert len(segments) == 1 and len(segments[0]) == 401


def test_declared_and_detected_cuts_are_combined_without_duplicate_segments():
    automatic = sample_expression("1/(x-.123)", -1, 1, -1000, 1000)
    declared = sample_expression("1/(x-.123)", -1, 1, -1000, 1000, [.123])
    assert declared == automatic
    assert_separated(automatic, [.123])


def test_dense_tangent_domain_has_a_bounded_failure():
    with pytest.raises(ValueError, match="Troppe discontinuità"):
        sample_expression("tan(100000*x)", -1, 1, -1e9, 1e9)


@pytest.mark.parametrize("source", ["f(x)=x^3", "f ( x ) = x^3", " y = x^3 "])
def test_explicit_function_assignment_alias_preserves_expression(source):
    assert validate_expression(source) == "x**3"
    assert compile_expression(source)(2) == 8


@pytest.mark.parametrize("source", ["f(x)=__import__('os')", "f(x).__class__=x", "f(x,y)=x", "f(x)=x; print(x)"])
def test_function_alias_does_not_expand_allowed_syntax(source):
    with pytest.raises(ValueError):
        sample_expression(source, -2, 2, -1e9, 1e9)
