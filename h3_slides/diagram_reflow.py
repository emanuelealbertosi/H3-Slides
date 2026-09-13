"""Bounded geometry alternatives for an existing graph; never infer its edges."""
from .diagram_spec import ManimSceneSpec

ATOMIC = {"box", "circle", "decision", "database", "document", "text"}


def graph_layout_candidates(spec):
    if (not spec.connections or not 2 <= len(spec.elements) <= 14 or
            any(e.type not in ATOMIC for e in spec.elements)):
        return
    # Prefer a small expansion of the existing composition before changing
    # its orientation. Labels often miss a corridor by only a few hundredths.
    expanded = spec.model_copy(deep=True)
    for e in expanded.elements:
        e.x = min(11.84-e.width/2, max(.16+e.width/2, 6+(e.x-6)*1.15))
        e.y = min(7.24-e.height/2, max(1.06+e.height/2, 4.15+(e.y-4.15)*1.15))
    try:
        yield ManimSceneSpec.model_validate(expanded.model_dump())
    except ValueError:
        pass
    by_id = {e.id: e for e in spec.elements}
    incoming = {key: 0 for key in by_id}
    children = {key: [] for key in by_id}
    for edge in spec.connections:
        if edge.source not in by_id or edge.target not in by_id:
            return  # Invalid endpoints require a data correction, not layout.
        incoming[edge.target] += 1
        children[edge.source].append(edge.target)
    order = {e.id: i for i, e in enumerate(spec.elements)}
    levels, pending = {}, [(key, 0) for key in by_id if not incoming[key]]
    while len(levels) < len(by_id):
        if not pending:
            # A cycle has no root. Use its existing visual order; keep every
            # back edge. Disconnected components remain disconnected.
            pending = [(next(key for key in by_id if key not in levels), 0)]
        while pending:
            key, depth = pending.pop(0)
            if key in levels:
                continue
            levels[key] = depth
            pending.extend((child, depth+1) for child in children[key] if child not in levels)
    groups = [[key for key in sorted(by_id, key=order.get) if levels[key] == depth]
              for depth in range(max(levels.values())+1)]
    # Both orientations preserve dependency layers. Splitting broad layers
    # leaves legible slots instead of shrinking six concepts into one row.
    for horizontal, breadth in ((False, 3), (True, 3)):
        bands = [group[i:i+breadth] for group in groups for i in range(0, len(group), breadth)]
        primary, secondary = (11.4, 6.0) if horizontal else (6.0, 11.4)
        gap = .65
        length = (primary-gap*(len(bands)-1))/len(bands)
        if length < (.8 if horizontal else .6):
            continue
        candidate = spec.model_copy(deep=True)
        targets = {e.id: e for e in candidate.elements}
        for band, members in enumerate(bands):
            cross = (secondary-gap*(len(members)-1))/len(members)
            for slot, key in enumerate(members):
                e = targets[key]
                p = length/2 + band*(length+gap)
                q = cross/2 + slot*(cross+gap)
                e.x, e.y = (.3+p, 1.15+q) if horizontal else (.3+q, 1.15+p)
                e.width, e.height = ((min(length, e.width), min(cross, e.height)) if horizontal
                                     else (min(cross, e.width), min(length, e.height)))
        try:
            candidate = ManimSceneSpec.model_validate(candidate.model_dump())
        except ValueError:
            continue
        yield candidate
