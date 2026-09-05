"""Safe parsing and deterministic sampling for mathematical function plots."""
from __future__ import annotations

import ast
import math
import re

import numpy as np


_FUNCTIONS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "sqrt": math.sqrt, "log": math.log10, "ln": math.log,
    "exp": math.exp, "abs": abs,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}
_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a ** b,
}
_UNARY = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}
_MAX_POLYNOMIAL_DEGREE = 12
_MAX_DISCONTINUITIES = 128


def _source(value: str) -> str:
    source = value.strip().replace("^", "**")
    source = re.sub(r"^(?:y|f\s*\(\s*x\s*\))\s*=\s*", "", source, count=1,
                    flags=re.IGNORECASE).strip()
    if not source or len(source) > 120:
        raise ValueError("Espressione matematica mancante o troppo lunga")
    return source


def _validate(node: ast.AST, depth: int = 0) -> None:
    if depth > 16:
        raise ValueError("Espressione matematica troppo complessa")
    if isinstance(node, ast.Expression):
        _validate(node.body, depth + 1)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Sono consentite soltanto costanti numeriche")
        if not math.isfinite(float(node.value)) or abs(float(node.value)) > 1e9:
            raise ValueError("Costante numerica fuori limite")
    elif isinstance(node, ast.Name):
        if node.id not in {"x", *_CONSTANTS}:
            raise ValueError(f"Nome matematico non consentito: {node.id}")
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
            if abs(float(node.right.value)) > 12:
                raise ValueError("Esponente fuori limite")
        _validate(node.left, depth + 1)
        _validate(node.right, depth + 1)
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        _validate(node.operand, depth + 1)
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
          and node.func.id in _FUNCTIONS and len(node.args) == 1 and not node.keywords):
        _validate(node.args[0], depth + 1)
    else:
        raise ValueError("Costrutto non consentito nell'espressione matematica")


def compile_expression(value: str):
    """Return a safe callable f(x), without eval or executable user code."""
    try:
        tree = ast.parse(_source(value), mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise ValueError("Espressione matematica non valida") from exc
    _validate(tree)

    def calculate(node: ast.AST, x: float) -> float:
        if isinstance(node, ast.Expression):
            return calculate(node.body, x)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return x if node.id == "x" else _CONSTANTS[node.id]
        if isinstance(node, ast.UnaryOp):
            return _UNARY[type(node.op)](calculate(node.operand, x))
        if isinstance(node, ast.BinOp):
            return _BINOPS[type(node.op)](calculate(node.left, x), calculate(node.right, x))
        return _FUNCTIONS[node.func.id](calculate(node.args[0], x))

    def function(x: float) -> float:
        try:
            result = float(calculate(tree, float(x)))
        except (ArithmeticError, OverflowError, ValueError, TypeError):
            return math.nan
        return result if math.isfinite(result) else math.nan

    return function


def validate_expression(value: str) -> str:
    compile_expression(value)
    return _source(value)


def function_line(value: str, at: float, other: float | None = None):
    """Compute a secant or a numerically checked tangent from the actual curve."""
    function = compile_expression(value)
    y = function(at)
    if other is not None:
        if other == at:
            raise ValueError("Secante: scegli due ascisse distinte")
        slope = (function(other)-y)/(other-at)
    else:
        step = 1e-4*max(1, abs(at))
        left = (y-function(at-step))/step
        right = (function(at+step)-y)/step
        slope = (function(at+step/2)-function(at-step/2))/step
        if not all(math.isfinite(v) for v in (left, right, slope)) or abs(left-right) > .01*max(1, abs(slope)):
            raise ValueError("Tangente: derivata non finita o non regolare nel punto; scegli un punto derivabile")
    intercept = y-slope*at
    if not all(math.isfinite(v) and abs(v) <= 1e9 for v in (y, slope, intercept)):
        raise ValueError("Retta: la funzione deve essere definita nei punti scelti")
    return slope, intercept


def _polynomial_coefficients(node: ast.AST):
    """Return bounded ascending coefficients, or None for unsupported forms.

    The input is an already-validated expression AST. No symbolic parser or
    executable source is involved, and every multiplication has degree <=12.
    """
    def finish(values):
        if any(not math.isfinite(value) for value in values):
            return None
        while len(values) > 1 and values[-1] == 0:
            values.pop()
        return values

    def multiply(left, right):
        if len(left) + len(right) - 2 > _MAX_POLYNOMIAL_DEGREE:
            return None
        values = [0.0] * (len(left) + len(right) - 1)
        for i, a in enumerate(left):
            for j, b in enumerate(right):
                values[i+j] += a*b
        return finish(values)

    if isinstance(node, ast.Expression):
        return _polynomial_coefficients(node.body)
    if isinstance(node, ast.Constant):
        return [float(node.value)]
    if isinstance(node, ast.Name):
        return [0.0, 1.0] if node.id == "x" else [_CONSTANTS[node.id]]
    if isinstance(node, ast.UnaryOp):
        value = _polynomial_coefficients(node.operand)
        if value is None:
            return None
        return [-item for item in value] if isinstance(node.op, ast.USub) else value
    if not isinstance(node, ast.BinOp):
        return None
    left = _polynomial_coefficients(node.left)
    right = _polynomial_coefficients(node.right)
    if left is None or right is None:
        return None
    if isinstance(node.op, (ast.Add, ast.Sub)):
        sign = -1 if isinstance(node.op, ast.Sub) else 1
        values = [(left[i] if i < len(left) else 0.0) +
                  sign*(right[i] if i < len(right) else 0.0)
                  for i in range(max(len(left), len(right)))]
        return finish(values)
    if isinstance(node.op, ast.Mult):
        return multiply(left, right)
    if isinstance(node.op, ast.Div) and len(right) == 1 and right[0] != 0:
        return finish([value/right[0] for value in left])
    if (isinstance(node.op, ast.Pow) and len(right) == 1 and right[0].is_integer()
            and 0 <= right[0] <= _MAX_POLYNOMIAL_DEGREE):
        value = [1.0]
        for _ in range(int(right[0])):
            value = multiply(value, left)
            if value is None:
                return None
        return value
    return None


def _polynomial_zeros(node: ast.AST):
    coefficients = _polynomial_coefficients(node)
    if coefficients is None or len(coefficients) <= 1:
        return []
    # Preserve supplied factors to avoid the poor conditioning of repeated
    # roots, notably (x-a)^2 and products of the same linear factor.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        return _polynomial_zeros(node.left)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _polynomial_zeros(node.left) + _polynomial_zeros(node.right)
    scale = max(abs(value) for value in coefficients)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            roots = np.polynomial.polynomial.polyroots([value/scale for value in coefficients])
    except (ValueError, FloatingPointError, np.linalg.LinAlgError):
        return []
    return [float(root.real) for root in roots
            if math.isfinite(root.real) and math.isfinite(root.imag)
            and root.imag == 0]


def _known_discontinuities(value: str, x_min: float, x_max: float):
    """Find cuts for polynomial divisors and tan(ax+b), with bounded work.

    This deliberately does not claim to locate every singularity of arbitrary
    supported compositions. Declared asymptotes and finite/jump checks remain.
    """
    tree = ast.parse(_source(value), mode="eval")
    _validate(tree)
    cuts = set()

    def add(values):
        cuts.update(point for point in values if math.isfinite(point) and x_min <= point <= x_max)
        if len(cuts) > _MAX_DISCONTINUITIES:
            raise ValueError("Troppe discontinuità nel dominio: restringi l'intervallo della funzione")

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            add(_polynomial_zeros(node.right))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = _polynomial_coefficients(node.right)
            if exponent is not None and len(exponent) == 1 and exponent[0] < 0:
                add(_polynomial_zeros(node.left))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tan":
            argument = _polynomial_coefficients(node.args[0])
            if argument is None or len(argument) != 2 or argument[1] == 0:
                continue
            offset, slope = argument
            low, high = sorted((slope*x_min+offset, slope*x_max+offset))
            if not math.isfinite(low) or not math.isfinite(high):
                raise ValueError("Dominio troppo esteso per localizzare le discontinuità")
            first = math.ceil((low-math.pi/2)/math.pi)
            last = math.floor((high-math.pi/2)/math.pi)
            if last-first+1 > _MAX_DISCONTINUITIES:
                raise ValueError("Troppe discontinuità nel dominio: restringi l'intervallo della funzione")
            add((math.pi/2+k*math.pi-offset)/slope for k in range(first, last+1))
    return cuts


def sample_expression(value: str, x_min: float, x_max: float, y_min: float, y_max: float,
                      asymptotes=(), samples: int = 401) -> list[list[tuple[float, float]]]:
    """Sample a function into disconnected visible segments."""
    if not x_min < x_max or not y_min < y_max:
        raise ValueError("Gli intervalli degli assi devono essere crescenti")
    function = compile_expression(value)
    samples = max(81, min(int(samples), 1201))
    step = (x_max - x_min) / (samples - 1)
    cuts = sorted({float(a) for a in asymptotes if x_min < float(a) < x_max} |
                  _known_discontinuities(value, x_min, x_max))
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous_x = None
    span = y_max - y_min
    for index in range(samples):
        x = x_min + index * step
        crosses = previous_x is not None and any(previous_x < cut <= x for cut in cuts)
        near_cut = any(abs(x - cut) <= step * .55 for cut in cuts)
        y = function(x)
        invalid = near_cut or not math.isfinite(y) or y < y_min or y > y_max
        jumps = current and abs(y - current[-1][1]) > span * .55
        if crosses or invalid or jumps:
            if len(current) >= 2:
                segments.append(current)
            current = []
        if not invalid:
            current.append((x, y))
        previous_x = x
    if len(current) >= 2:
        segments.append(current)
    return segments
