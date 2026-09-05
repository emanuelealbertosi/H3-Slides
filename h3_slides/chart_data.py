"""Deterministic numerical chart preparation; no generated measurements."""
import bisect
import math


def histogram_data(samples, bin_edges):
    """Count [left, right) intervals, including the right edge of the last bin."""
    if not 1 <= len(samples) <= 512:
        raise ValueError("Istogramma: servono da 1 a 512 campioni numerici in samples")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in [*samples, *bin_edges]):
        raise ValueError("Istogramma: campioni ed estremi devono essere numeri finiti")
    if not 2 <= len(bin_edges) <= 13 or any(a >= b for a, b in zip(bin_edges, bin_edges[1:])):
        raise ValueError("Istogramma: bin_edges richiede da 2 a 13 estremi strettamente crescenti")
    if any(not bin_edges[0] <= value <= bin_edges[-1] for value in samples):
        raise ValueError("Istogramma: bin_edges deve comprendere tutti i campioni, senza scartarli")
    counts = [0] * (len(bin_edges)-1)
    for value in samples:
        index = min(len(counts)-1, bisect.bisect_right(bin_edges, value)-1)
        counts[index] += 1
    widths = [b-a for a, b in zip(bin_edges, bin_edges[1:])]
    density = any(not math.isclose(width, widths[0], rel_tol=1e-8, abs_tol=0) for width in widths[1:])
    heights = [count/width if density else count for count, width in zip(counts, widths)]
    if not all(math.isfinite(value) for value in heights):
        raise ValueError("Istogramma: ampiezze non rappresentabili; cambia unità senza alterare i campioni")
    return {"counts": counts, "heights": heights,
            "density": density, "bin_edges": list(bin_edges), "sample_count": len(samples)}


def nice_axis(values, include_zero=False, padding=.06, integer=False):
    """Return a data-driven finite range and at most a handful of readable ticks."""
    lo, hi = min(values), max(values)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Asse numerico: servono valori finiti")
    if include_zero:
        lo, hi = min(0, lo), max(0, hi)
    if hi == lo:
        delta = max(1, abs(lo)*.1)
        lo, hi = (0, delta) if include_zero and lo == 0 else (lo-delta, hi+delta)
    elif padding:
        span = hi-lo
        lo -= 0 if include_zero and lo == 0 else span*padding
        hi += 0 if include_zero and hi == 0 else span*padding
    target = (hi-lo)/4
    if not math.isfinite(target) or target <= 0:
        raise ValueError("Asse numerico: intervallo non rappresentabile, cambia unità")
    exponent = 10**math.floor(math.log10(target))
    # A finite subnormal target can have a decimal decade that rounds to zero.
    # Even a nonzero rounded decade may leave no candidate at the requested
    # scale; report this as data/range feedback instead of leaking StopIteration.
    if not math.isfinite(exponent) or exponent <= 0:
        raise ValueError("Asse numerico: intervallo non rappresentabile, cambia unità")
    step = next((value*exponent for value in (1, 2, 2.5, 5, 10) if value*exponent >= target), None)
    if step is None or not math.isfinite(step) or step <= 0:
        raise ValueError("Asse numerico: intervallo non rappresentabile, cambia unità")
    if integer:
        step = max(1, math.ceil(step))
    lo, hi = math.floor(lo/step)*step, math.ceil(hi/step)*step
    count = round((hi-lo)/step)
    return {"min": lo, "max": hi, "step": step,
            "ticks": [lo+index*step for index in range(count+1)]}


def format_tick(value, step):
    if not math.isfinite(value) or not math.isfinite(step) or step == 0:
        raise ValueError("Tacche numeriche: intervallo non rappresentabile, cambia unità")
    if value == 0 or abs(value) < abs(step)*1e-9:
        return "0"
    if abs(value) >= 1e5 or abs(value) < .001:
        ratio = abs(value)/abs(step)
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError("Tacche numeriche: intervallo non rappresentabile, cambia unità")
        precision = min(16, max(4, 2+math.ceil(math.log10(ratio))))
        return f"{value:.{precision}g}"
    for decimals in range(13):
        if math.isclose(step, round(step, decimals), rel_tol=1e-8, abs_tol=0):
            return f"{value:.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{value:.0f}"
    return f"{value:.6g}"
