"""Safe parsing and deterministic sampling for mathematical function plots."""
from __future__ import annotations

import ast
import math


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


def _source(value: str) -> str:
    source = value.strip().replace("^", "**")
    if source.lower().startswith(("y=", "y =")):
        source = source.split("=", 1)[1].strip()
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
        except (ArithmeticError, OverflowError, ValueError):
            return math.nan
        return result if math.isfinite(result) else math.nan

    return function


def validate_expression(value: str) -> str:
    compile_expression(value)
    return _source(value)


def sample_expression(value: str, x_min: float, x_max: float, y_min: float, y_max: float,
                      asymptotes=(), samples: int = 401) -> list[list[tuple[float, float]]]:
    """Sample a function into disconnected visible segments."""
    if not x_min < x_max or not y_min < y_max:
        raise ValueError("Gli intervalli degli assi devono essere crescenti")
    function = compile_expression(value)
    samples = max(81, min(int(samples), 1201))
    step = (x_max - x_min) / (samples - 1)
    cuts = sorted(float(a) for a in asymptotes if x_min < float(a) < x_max)
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
