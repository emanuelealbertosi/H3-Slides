"""Conservative adaptation of common JSON spellings, never guessed chart data."""
import copy
import math
import re


_ALIASES = {
    "rectangle": "box", "rect": "box", "diamond": "decision",
    "bar_chart": "bars", "barchart": "bars", "hist": "histogram",
    "scatter_plot": "scatter", "scatterplot": "scatter",
    "line_chart": "plot", "line_plot": "plot", "function": "function_plot",
    "directed_graph": "network",
}
_EDGES = {"arrow", "edge", "connection", "connector"}


def _number(value):
    if isinstance(value, str) and re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d+)?|\.\d+)(?:[eE][+-]?\d+)?", value.strip()):
        value = float(value.replace(",", "."))
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            abs(value) > 1e9 or not math.isfinite(value)):
        raise ValueError("Dati numerici non validi: non sostituire valori mancanti con numeri inventati")
    return value


def _alias(item, source, target):
    if source not in item:
        return
    if target in item and not _equivalent(item[target], item[source]):
        raise ValueError("Struttura ambigua: campi equivalenti contengono dati diversi")
    item[target] = item.pop(source)


def _equivalent(left, right):
    """JSON booleans are never interchangeable with numeric zero or one."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equivalent(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equivalent(left[key], right[key]) for key in left)
    return left == right


def _pair(edge):
    if isinstance(edge, (list, tuple)) and len(edge) == 2:
        return edge
    if isinstance(edge, dict):
        value = dict(edge)
        _alias(value, "from", "source")
        _alias(value, "to", "target")
        if set(value) == {"source", "target"}:
            return value["source"], value["target"]
    raise ValueError("Rete: usa coppie di indici o nomi di nodi dichiarati, senza archi incompleti")


def _network(item):
    lookup = None
    if "nodes" in item:
        nodes = item["nodes"]
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("Rete: nodes deve contenere nodi dichiarati")
        ids, labels = [], []
        for node in nodes:
            if isinstance(node, str):
                ids.append(node)
                labels.append(node)
            elif isinstance(node, dict) and set(node) <= {"id", "label"} and isinstance(node.get("id"), str):
                ids.append(node["id"])
                labels.append(node.get("label", node["id"]))
            else:
                raise ValueError("Rete: nodi non validi; servono id ed etichette espliciti")
        if len(ids) != len(set(ids)) or not all(isinstance(label, str) for label in labels):
            raise ValueError("Rete: identificatori ambigui o etichette non valide")
        if "labels" in item and item["labels"] != labels:
            raise ValueError("Rete: nodes e labels contengono dati diversi")
        item["labels"] = labels
        lookup = {name: index for index, name in enumerate(ids)}
        del item["nodes"]
    if "edges" not in item:
        return
    edges, labels = item["edges"], item.get("labels")
    if not isinstance(edges, list) or not isinstance(labels, list):
        raise ValueError("Rete: edges richiede la lista dei nodi in labels")
    if lookup is None:
        lookup = {name: index for index, name in enumerate(labels) if isinstance(name, str)}
        if len(lookup) != len(labels):
            raise ValueError("Rete: etichette ambigue per gli archi nominativi")
    def index_of(endpoint):
        if isinstance(endpoint, str) and endpoint in lookup:
            return lookup[endpoint]
        if isinstance(endpoint, (int, float)) and not isinstance(endpoint, bool):
            if 0 <= endpoint < len(labels) and math.isfinite(endpoint) and int(endpoint) == endpoint:
                return int(endpoint)
        raise ValueError("Rete: un arco usa un nodo non dichiarato o un indice fuori intervallo")
    values = []
    for edge in edges:
        values.extend(index_of(endpoint) for endpoint in _pair(edge))
    if "values" in item and not _equivalent(item["values"], values):
        raise ValueError("Rete: edges e values indicano collegamenti diversi")
    item["values"] = values
    del item["edges"]


def _chart(item):
    kind = item.get("type")
    if kind == "network":
        _network(item)
    if kind in {"plot", "scatter"} and "points" in item:
        points = item["points"]
        if not isinstance(points, list):
            raise ValueError("Grafico: points deve contenere coppie numeriche x,y")
        pairs = []
        for point in points:
            if isinstance(point, dict) and set(point) == {"x", "y"}:
                pair = [point["x"], point["y"]]
            elif isinstance(point, (list, tuple)) and len(point) == 2:
                pair = point
            else:
                raise ValueError("Grafico: points richiede coppie numeriche x,y")
            pairs.append([_number(value) for value in pair])
        for key, axis in (("x_values", 0), ("values", 1)):
            numbers = [point[axis] for point in pairs]
            if key in item and not _equivalent(item[key], numbers):
                raise ValueError("Grafico: points e valori degli assi non corrispondono")
            item[key] = numbers
        del item["points"]
    if kind == "histogram":
        if "data" in item:
            if not isinstance(item["data"], list):
                raise ValueError("Istogramma: data deve contenere i campioni numerici originali")
            item["data"] = [_number(value) for value in item["data"]]
            _alias(item, "data", "samples")
        if "bins" in item:
            if not isinstance(item["bins"], list):
                raise ValueError("Istogramma: bin_edges richiede limiti numerici espliciti, non conteggi inventati")
            _alias(item, "bins", "bin_edges")
    if kind == "bars" and "data" in item:
        rows = item["data"]
        if not isinstance(rows, list) or not all(isinstance(row, dict) and set(row) == {"label", "value"} for row in rows):
            raise ValueError("Barre: data richiede coppie esplicite label,value")
        for key, values in (("labels", [row["label"] for row in rows]),
                            ("values", [_number(row["value"]) for row in rows])):
            if key in item and not _equivalent(item[key], values):
                raise ValueError("Barre: data e labels/values non corrispondono")
            item[key] = values
        del item["data"]
    if kind == "function_plot":
        _alias(item, "formula", "expression")
        for key, low, high in (("domain", "x_min", "x_max"), ("range", "y_min", "y_max")):
            if key not in item:
                continue
            values = item[key]
            if not isinstance(values, list) or len(values) != 2:
                raise ValueError("Funzione: intervalli degli assi ambigui, servono due estremi")
            for name, value in zip((low, high), values):
                value = _number(value)
                if name in item and _number(item[name]) != value:
                    raise ValueError("Funzione: gli intervalli degli assi non corrispondono")
                item[name] = value
            del item[key]


def normalize_scene_input(value):
    """Convert only supplied, unambiguous aliases and explicit relationships."""
    result = copy.deepcopy(value)
    if isinstance(result, dict) and set(result) == {"scene"}:
        result = result["scene"]
    if not isinstance(result, dict) or not isinstance(result.get("elements"), list):
        return result, result != value
    original_elements = result["elements"]
    ids = [item.get("id") for item in original_elements
           if isinstance(item, dict) and
           (not isinstance(item.get("type"), str) or item["type"] not in _EDGES)]
    known_ids = {name for name in ids if isinstance(name, str) and ids.count(name) == 1}
    kept, extracted = [], []
    for item in original_elements:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        kind = item.get("type")
        if not isinstance(kind, str):
            kept.append(item)
            continue
        if kind in _EDGES:
            edge = copy.deepcopy(item)
            _alias(edge, "from", "source")
            _alias(edge, "to", "target")
            _alias(edge, "text", "label")
            if (not set(edge) <= {"id", "type", "source", "target", "label", "tone"} or
                    not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str) or
                    edge.get("source") not in known_ids or edge.get("target") not in known_ids or
                    edge["source"] == edge["target"]):
                raise ValueError("Collegamento non valido: specifica source e target di elementi dichiarati in connections")
            extracted.append({key: entry for key, entry in edge.items() if key not in {"id", "type"}})
            continue
        item["type"] = _ALIASES.get(kind, kind)
        if kind == "graph" and ("nodes" in item or "edges" in item):
            item["type"] = "network"
        if kind == "directed_graph":
            if "directed" in item and item["directed"] is not True:
                raise ValueError("Rete: directed_graph e directed=false sono contraddittori")
            item["directed"] = True
        if "position" in item:
            position = item["position"]
            if not isinstance(position, dict) or set(position) != {"x", "y"}:
                raise ValueError("Geometria: position richiede x e y espliciti")
            for name, coordinate in position.items():
                if name in item and not _equivalent(item[name], coordinate):
                    raise ValueError("Geometria: coordinate position e x/y contraddittorie")
                item[name] = coordinate
            del item["position"]
        _chart(item)
        kept.append(item)
    if extracted:
        connections = result.get("connections", [])
        if not isinstance(connections, list):
            raise ValueError("Struttura: connections deve essere una lista")
        result["connections"] = list(connections)
        for edge in extracted:
            if edge not in result["connections"]:
                result["connections"].append(edge)
        result["elements"] = kept
    return result, result != value
