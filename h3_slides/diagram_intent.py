"""Recognize diagram requests and validate visual intent without rendering.

Only local scene instructions belong here. Mentions in a whole-deck brief are
not requirements for every slide; the caller selects the appropriate scope.
"""
import re


_PATTERNS = (
    ("histogram", (r"\b(?:istogramm[ai]|histograms?)\b",)),
    ("bars", (r"\bgrafic[oi]\s+(?:a\s+|di\s+)?(?:barre|colonne)\b",
              r"\b(?:bar|column)[ -]+(?:charts?|graphs?|plots?)\b", r"\bbars\b")),
    ("scatter", (r"\bscatter(?:[ -]+(?:plots?|charts?|graphs?))?\b",
                 r"\b(?:grafic[oi]|diagramm[ai])\s+(?:a|di)\s+dispersione\b",
                 r"\bnuvol[ae]\s+di\s+punti\b")),
    ("function_plot", (r"\bfunction_plot\b", r"\b(?:y|[a-z]\s*\(\s*x\s*\))\s*=",
                       r"\b(?:grafic[oi]|plot)\s+(?:(?:di|della|delle)\s+)?(?:una\s+)?funzion[ei]\b",
                       r"\b(?:functions?[ -]+(?:plots?|graphs?)|(?:plot|graph)\s+(?:a\s+|the\s+)?functions?)\b",
                       r"\bfunzion[ei]\s+matematic(?:a|o|he|i)\b",
                       r"\b(?:sin|cos|tan|sqrt|log|ln|exp|abs)\s*\(\s*x\b")),
    ("plot", (r"\bgrafic[oi]\s+(?:a\s+linee|(?:del|dei)\s+(?:segnal[ei]|campioni))\b",
              r"\bline[ -]+(?:charts?|graphs?|plots?)\b",
              r"\b(?:un|a|sampled)\s+plots?\b", r"\bplots?\s+(?:di|del|dei)\b",
              r"^plots?$", r"\bplots?\s*(?=,|\band\b|\be\b)")),
    ("gantt", (r"\bgantt\b",)),
    ("venn", (r"\bvenn\b",)),
    ("timeline", (r"\btimelines?\b", r"\bline[ae]\s+del\s+tempo\b")),
    ("tree", (r"\bdiagramm[ai]\s+ad?\s+alber[oi]\b", r"\balber[oi]\s+(?:decisional[ei]|gerarchic[oi])\b",
              r"\b(?:decision|family)[ -]+trees?\b", r"\btrees?[ -]+(?:diagrams?|structures?)\b",
              r"\b(?:hierarchy|hierarchies|gerarchi[ae])\b", r"^trees?$",
              r"\b(?:draw|show|build|create)\s+(?:(?:a|the)\s+)?trees?\b")),
    ("network", (r"\b(?:graf[oi]|networks?)\b", r"\bdiagramm[ai]\s+di\s+rete\b",
                 r"\b(?:directed|undirected)[ -]+graphs?\b",
                 r"\bgraphs?\s+(?:theory|with\s+(?:nodes|vertices)|of\s+(?:nodes|vertices))\b")),
    ("flowchart", (r"\bflow[ -]?charts?\b", r"\bdiagramm[ai]\s+di\s+flusso\b")),
    ("comparison", (r"\b(?:confronto|confronti|confronta|confrontare|comparazion[ei]|comparisons?|comparative)\b",
                    # `compare` is also an Italian verb meaning 'appears'. An
                    # English request needs English syntax, not this token alone.
                    r"\bcompare\s+(?:the|these|those|both|two|three|four|our)\b",
                    r"\bcompare\b[^.!?\n]{0,120}\b(?:and|with|versus|vs)\b",
                    r"\b(?:please|can\s+you|could\s+you)\s+compare\b")),
)


def _explicitly_excluded(text, position):
    """Honor simple local prohibitions, not full natural-language inference.

    A prohibition covers a short clause/list until a contrast or a new
    affirmative command. `Non solo` / `not only` (also `non usare solo`) are
    additive requests, so they must not erase a mentioned diagram family.
    """
    prefix = re.split(r"[;.!?\n]", text[:position])[-1]
    resets = list(re.finditer(
        r"\b(?:ma|invece|but|instead)\b|(?:,|\b(?:e|and)\b)\s*"
        r"(?:usa|mostra|disegna|crea|inserisci|aggiungi|use|show|draw|create|include|add)\b", prefix))
    if resets:
        prefix = prefix[resets[-1].end():]
    negation = r"\b(?:do\s+not|don't|non|not|no|senza|without|evita(?:re|te)?|avoid|escludi|exclude)\b"
    weak = (r"(?:do\s+not|don't|non|not|no)(?:\s+(?:usare|utilizzare|mostrare|use|show|draw|include))?"
            r"\s+(?:solo|soltanto|only|just|necessariamente|necessarily|meno|more|less|fewer)\b")
    for match in re.finditer(negation, prefix):
        if re.match(weak, prefix[match.start():]):
            continue
        tail = prefix[match.end():]
        # A direct prohibition may name one family or a short list of them.
        # Leave other words intact: "evita sovrapposizioni nel grafico" and
        # "non superare 5 nodi nel network" constrain layout, not chart use.
        for _family, patterns in _PATTERNS:
            for pattern in patterns:
                tail = re.sub(pattern, " ", tail)
        tail = re.sub(
            r"\b(?:usare|utilizzare|mostrare|disegnare|creare|inserire|aggiungere|includere|fare|"
            r"voglio|volere|use|show|draw|create|include|add|build|make|want|need|di|to|"
            r"un|uno|una|il|lo|la|i|gli|le|dei|degli|delle|alcun|alcuno|alcuna|nessun|nessuno|nessuna|"
            r"a|an|the|any|e|o|oppure|ne|né|and|or|nor)\b", " ", tail)
        if not re.sub(r"[\s,:\"'()\[\]-]+", "", tail):
            return True
    return False


def _family_mentions(value):
    """Keep local positive/negative mentions so callers can apply precedence."""
    text = (value or "").casefold().replace("’", "'")
    matches = [(match.start(), match.end(), family)
               for family, patterns in _PATTERNS for pattern in patterns
               for match in re.finditer(pattern, text)]
    # A line/scatter/function *plot* is one specific request, not a second
    # request inferred from a generic noun within the same phrase.
    matches = [match for match in matches if not (
        match[2] == "plot" and any(other[2] in ("scatter", "function_plot", "bars") and
                                  other[0] < match[1] and other[1] > match[0]
                                  for other in matches))]
    return [(family, _explicitly_excluded(text, start)) for start, _end, family in
            sorted(matches, key=lambda item: (item[0], -(item[1]-item[0])))]


def requested_families(value):
    """Return distinct requested families in mention order, with exact words."""
    result = []
    for family, excluded in _family_mentions(value):
        if not excluded and family not in result:
            result.append(family)
    return result


def requested_scene_families(title: str, brief: str, instructions: str):
    """Apply explicit local corrections over an older scene title/brief.

    Scope is supplied by the caller: instructions must concern this scene,
    not a whole-deck checklist. Later explicit mentions win for their family;
    unmentioned families are retained and no universal language parsing is
    attempted. A later affirmative request can restore a prohibited family.
    """
    order, active = [], {}
    for value in (title, brief, instructions):
        for family, excluded in _family_mentions(value):
            if family not in active:
                order.append(family)
            active[family] = not excluded
    return [family for family in order if active[family]]


def requested_family(value):
    """Compatibility API: prefer a concrete form over generic comparison."""
    families = requested_families(value)
    return next((family for family in families if family != "comparison"),
                "comparison" if families else "")


def _components(scene):
    """External relationships define groups; isolated text is an annotation."""
    by_id = {element.id: element for element in scene.elements}
    neighbours = {key: set() for key in by_id}
    for edge in scene.connections:
        if edge.source in by_id and edge.target in by_id:
            neighbours[edge.source].add(edge.target)
            neighbours[edge.target].add(edge.source)
    groups, seen = [], set()
    for key in by_id:
        if key in seen:
            continue
        pending, members = [key], []
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            members.append(by_id[current])
            pending.extend(neighbours[current]-seen)
        if any(element.type != "text" for element in members):
            groups.append(members)
    return groups


def _separate_panels(groups):
    if len(groups) < 2:
        return False
    boxes = [(min(element.x-element.width/2 for element in group),
              min(element.y-element.height/2 for element in group),
              max(element.x+element.width/2 for element in group),
              max(element.y+element.height/2 for element in group)) for group in groups]
    # Components may be side by side or stacked. Interleaved components do
    # not form readable comparison panels merely because their IDs differ.
    return all(a[2]+.08 <= b[0] or b[2]+.08 <= a[0] or a[3]+.08 <= b[1] or b[3]+.08 <= a[1]
               for index, a in enumerate(boxes) for b in boxes[index+1:])


def _quantitative_comparison(element):
    kind = element.type
    values = getattr(element, "values", ())
    labels = getattr(element, "labels", ())
    if kind == "bars":
        return len(values) >= 2 and len(labels) == len(values)
    if kind == "histogram":
        return bool(getattr(element, "samples", ())) and len(getattr(element, "bin_edges", ())) >= 3
    if kind == "scatter":
        return len(values) >= 2 and len(getattr(element, "x_values", ())) == len(values)
    if kind in ("plot", "grid"):
        return len(values) >= 2
    if kind == "function_plot":
        return bool(getattr(element, "series", ()) or getattr(element, "secant_x", ())) or \
               getattr(element, "tangent_at", None) is not None
    if kind == "gantt":
        return len(labels) >= 2 and len(values) == 2*len(labels)
    if kind == "venn":
        return len(labels) >= 2
    return False


def validate_designed_scene(scene, required=""):
    """Check newly designed scene intent; stored scenes keep their own schema.

    Geometry/data validity is checked by ManimSceneSpec before this editorial
    pass. A generic comparison can use quantitative charts or separate groups
    with internal relationships; it never requires all concrete chart types.
    """
    families = [required] if isinstance(required, str) and required else list(required or [])
    groups = _components(scene)
    if (len(scene.elements) >= 3 and scene.connections and len(groups) == 1 and
            all(element.type == "box" for element in scene.elements)):
        raise ValueError("Un flusso non può essere composto solo da rettangoli: usa forme semantiche pertinenti")
    for family in dict.fromkeys(families):
        if family == "comparison":
            if not (_separate_panels(groups) or any(_quantitative_comparison(element) for element in scene.elements)):
                raise ValueError("È richiesto un confronto: usa almeno due pannelli o gruppi distinti leggibili, anche con frecce interne, oppure dati confrontabili")
        elif family == "flowchart":
            if not scene.connections or not any(element.type in {"circle", "decision", "database", "document"}
                                                for element in scene.elements):
                raise ValueError("È richiesto un vero diagramma di flusso con frecce e forme semantiche")
        elif family and not any(element.type == family for element in scene.elements):
            raise ValueError(f"È richiesto un diagramma {family}, non una sua approssimazione")
