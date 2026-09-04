"""Deterministic orthogonal routing around the model-designed scene."""
import heapq
import math


def bounds(element, padding=0):
    return (element.x-element.width/2-padding, element.y-element.height/2-padding,
            element.x+element.width/2+padding, element.y+element.height/2+padding)


def crosses(a, b, box):
    left, top, right, bottom = box
    if abs(a[0]-b[0]) < 1e-6:
        return left+1e-6 < a[0] < right-1e-6 and max(min(a[1], b[1]), top) < min(max(a[1], b[1]), bottom)-1e-6
    return top+1e-6 < a[1] < bottom-1e-6 and max(min(a[0], b[0]), left) < min(max(a[0], b[0]), right)-1e-6


def route_connection(source, target, elements):
    horizontal = abs(target.x-source.x) >= abs(target.y-source.y)
    sign = 1 if (target.x-source.x if horizontal else target.y-source.y) > 0 else -1
    if horizontal:
        start = (source.x+sign*(source.width/2+.16), source.y)
        end = (target.x-sign*(target.width/2+.16), target.y)
    else:
        start = (source.x, source.y+sign*(source.height/2+.16))
        end = (target.x, target.y-sign*(target.height/2+.16))
    # Scene validation already guarantees separation between elements.  A
    # tenth of a unit on both sides made otherwise valid narrow corridors
    # impossible to route; four hundredths still keeps the stroke clear.
    boxes = [bounds(element, .04) for element in elements]
    xs = sorted(set([start[0], end[0], .08, 11.92] + [round(v, 6) for box in boxes for v in (box[0]-.02, box[2]+.02) if .06 < v < 11.94]))
    ys = sorted(set([start[1], end[1], .94, 7.34] + [round(v, 6) for box in boxes for v in (box[1]-.02, box[3]+.02) if .92 < v < 7.36]))
    origin, goal = (xs.index(start[0]), ys.index(start[1])), (xs.index(end[0]), ys.index(end[1]))
    queue, distance, previous = [(0, origin, 0)], {(origin, 0): 0}, {}
    found = None
    while queue:
        cost, at, direction = heapq.heappop(queue)
        if cost != distance.get((at, direction)):
            continue
        if at == goal:
            found = (at, direction)
            break
        a = xs[at[0]], ys[at[1]]
        for dx, dy, way in ((1, 0, 1), (-1, 0, 1), (0, 1, 2), (0, -1, 2)):
            nxt = at[0]+dx, at[1]+dy
            if not (0 <= nxt[0] < len(xs) and 0 <= nxt[1] < len(ys)):
                continue
            b = xs[nxt[0]], ys[nxt[1]]
            if any(crosses(a, b, box) for box in boxes):
                continue
            new_cost = cost+math.dist(a, b)+(.22 if direction and direction != way else 0)
            state = nxt, way
            if new_cost < distance.get(state, math.inf):
                distance[state], previous[state] = new_cost, (at, direction)
                heapq.heappush(queue, (new_cost, nxt, way))
    if found is None:
        raise ValueError(f"Nessun percorso leggibile tra {source.id} e {target.id}: aumenta gli spazi")
    path = []
    while found in previous:
        at = found[0]
        path.append((xs[at[0]], ys[at[1]]))
        found = previous[found]
    path.append(start)
    path.reverse()
    simple = [path[0]]
    for i in range(1, len(path)-1):
        a, b, c = simple[-1], path[i], path[i+1]
        if abs((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])) > 1e-8:
            simple.append(b)
    return simple+[path[-1]]
