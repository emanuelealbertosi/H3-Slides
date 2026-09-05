"""Shared generation contract for readable, editable prose boxes."""
import re
from .models import SlideContent


def paragraph_budget(project):
    visual = project.get("use_manim_diagrams", False) or project.get("use_web_images", False) or (
        project.get("use_source_images", True) and any(s.get("images") for s in project.get("sources", [])))
    return (480 if visual else 800) if project.get("text_density") == "complete" else (370 if visual else 650)


def mathematical_block(text):
    markers = re.findall(r"\\(?:\(|\[|frac\b|sqrt\b|int\b|sum\b|lim\b|sin\b|cos\b|tan\b)", text)
    return len(markers) >= 2 or (len(markers) >= 1 and len(re.findall(r"[=+\-*/^_]", text)) >= 2)


def content_contract(project, block_count=None):
    density = project.get("text_density", "detailed")
    schema = SlideContent.model_json_schema()
    for key in ("image_origin", "image_placeholder"):
        schema["properties"].pop(key, None)  # Resolved by the app after acquisition.
    schema["properties"].pop("freeform", None)  # Geometry belongs to the deterministic editor, never to the LLM.
    schema["properties"].pop("freeform_base", None)
    schema["properties"].pop("freeform_compact", None)
    schema["$defs"].pop("FreePlacement", None)
    schema["properties"]["layout"]["enum"] = [
        value for value in schema["properties"]["layout"]["enum"] if value != "freeform"
    ]
    schema["$defs"]["DiagramSpec"]["properties"]["scene"] = {"type": "null"}
    # The first LLM stage can only request a diagram brief; geometry is
    # designed later with its dedicated schema. Remove now-unreachable Manim
    # definitions so smaller remote context windows are not wasted.
    for name in ("Connection", "Element", "ManimSceneSpec"):
        schema["$defs"].pop(name, None)
    schema["properties"]["layout_variant"]["const"] = 0  # Variants are a deterministic editor control.
    if density == "brief":
        schema["properties"]["bullets"].update(maxItems=3, items={"type": "string", "maxLength": 90})
        schema["properties"]["blocks"].update(maxItems=0)
        return schema, "ACCENNI: bullets con massimo 3 punti di 90 caratteri; blocks=[]."
    # Divide the aggregate budget before generation, so small models need not count totals.
    base = paragraph_budget(project)
    total = base*2
    count = block_count if isinstance(block_count, int) and 1 <= block_count <= 4 else None
    max_chars = min(base, total//count) if count else base
    minimum = 140 if density == "complete" else 100
    schema["properties"]["bullets"].update(maxItems=0)
    schema["properties"]["blocks"].update(minItems=count or 1, maxItems=count or 4)
    # Grammar needs headroom: a hard stop at the editorial limit can cut a sentence.
    schema["$defs"]["TextBlock"]["properties"]["text"].update(minLength=minimum, maxLength=max_chars+120)
    schema["$defs"]["TextBlock"]["properties"]["heading"].update(maxLength=45)
    schema["properties"]["title"].update(maxLength=75)
    schema["properties"]["subtitle"].update(maxLength=110)
    schema["required"] = list(dict.fromkeys(schema.get("required", []) + ["blocks", "bullets", "layout"]))
    rules = (
        f"{density.upper()}: bullets=[]; " +
        (f"scrivi {count} blocks, " if count else "scegli da 1 a 4 blocks secondo il contenuto, ") +
        "ciascuno con un titolo "
        f"breve (massimo 45 caratteri) e un paragrafo di {minimum}–{max_chars} caratteri. "
        f"Per rientrare, punta a circa {max(12, max_chars//10)}–{max_chars//8} parole per paragrafo, "
        "con frasi brevi ma complete. Evita periodi molto lunghi. "
        f"Budget COMPLESSIVO dei paragrafi: massimo {total} caratteri. "
        "Con 1–2 box sviluppa paragrafi ampi; con 3–4 distribuisci il budget tra tutti. "
        "Copertina: un solo paragrafo introduttivo, niente inventario di dettagli. "
        "Concludi ogni paragrafo con una frase completa e un punto: non interrompere parole o periodi. "
        "Usa frasi complete collegate tra loro: definizione, spiegazione, conseguenza o esempio concreto. "
        "NON riassumere tutto in punti elenco. Il testo deve essere visibile nella slide, non relegato alle note. "
        "Varia kind secondo la funzione: explanation per spiegare, example per un caso concreto, key per "
        "una conclusione, quote per un brano originale del documento allegato. "
        "Puoi riportare un intero paragrafo recuperato dalla fonte se rientra nel box; "
        "altrimenti scegli un passaggio autonomo più breve o rielabora fedelmente. "
        "Quote: copia esattamente dal PASSAGGIO ORIGINALE, indica source; non citare una sintesi LLM. "
        "Non inventare contenuti per raggiungere la lunghezza: spiega relazioni ed esempi pertinenti. "
        "Titolo massimo 75 caratteri; sottotitolo facoltativo massimo 110. "
    )
    if density == "complete":
        rules += "COMPLETO: sviluppa anche il perché e le conseguenze, con esempi e dettagli operativi."
    return schema, rules


def validate_content(content, project, evidence):
    schema, _ = content_contract(project, len(content.blocks))
    if project.get("text_density", "detailed") == "brief":
        if content.blocks or len(content.bullets) > 3 or any(len(p) > 90 for p in content.bullets):
            raise ValueError("Accenni richiede massimo 3 punti di 90 caratteri")
        return
    limits = schema["$defs"]["TextBlock"]["properties"]["text"]
    if content.bullets or not 1 <= len(content.blocks) <= 4:
        raise ValueError("Approfondito/Completo richiede da 1 a 4 paragrafi in box, non un elenco puntato")
    budget = paragraph_budget(project)*2
    if sum(len(b.text) for b in content.blocks) > budget:
        raise ValueError(f"Budget complessivo superato: massimo {budget} caratteri tra tutti i paragrafi")
    for index, block in enumerate(content.blocks):
        math_content = mathematical_block(block.text)
        minimum = 24 if math_content else limits["minLength"]
        if not minimum <= len(block.text) <= limits["maxLength"]-120:
            raise ValueError(f"Box {index+1}: {len(block.text)} caratteri; servono {minimum}–{limits['maxLength']-120}. "
                             "Riduci le frasi, non tagliare parole")
        if block.kind != "quote" and not math_content and not re.search(r'[.!?][\"»”)\]]*$', block.text.strip()):
            raise ValueError("Il paragrafo termina con una frase incompleta: chiudi il periodo senza tagliare parole")
        if len(block.heading) > 45:
            raise ValueError("Titolo del box troppo lungo")
        if block.kind == "quote":
            normalize = lambda value: re.sub(r"\s+", " ", value).strip()
            parts = re.split(r"(?m)^\[([^\n]+)\]\n", evidence)
            matches = [(parts[i], parts[i+1]) for i in range(1, len(parts)-1, 2)
                       if normalize(block.text) in normalize(parts[i+1]) and
                       any(parts[i].startswith(s["name"]) and s["name"] in block.source
                           for s in project.get("sources", []))]
            if not matches:
                raise ValueError("Citazione non verificabile nei passaggi originali: usa un brano esatto o una rielaborazione")
            # Source and page come from the matching literal passage, not model guesses.
            original = block.source
            block.source = matches[0][0][:220]
            content.sources = [block.source if s == original else s for s in content.sources]
            if block.source not in content.sources:
                content.sources.append(block.source)
    if len(content.title) > 75 or len(content.subtitle) > 110:
        raise ValueError("Titolo o sottotitolo troppo lungo per il layout a paragrafi")


def fit_complete_sentences(content, project):
    """Last-resort editorial fit, never applied to quotations; retain the draft."""
    if project.get("text_density", "detailed") == "brief":
        return False
    schema, _ = content_contract(project, len(content.blocks))
    limits = schema["$defs"]["TextBlock"]["properties"]["text"]
    maximum, minimum = limits["maxLength"]-120, limits["minLength"]
    originals = []
    for block in content.blocks:
        text = block.text.strip()
        if block.kind == "quote" or (len(text) <= maximum and re.search(r'[.!?]["»”)\]]*$', text)):
            continue
        ends = [m.end() for m in re.finditer(r'[.!?]["»”)\]]*(?=\s|$)', text)
                if minimum <= m.end() <= maximum]
        if not ends:
            continue
        originals.append(block.heading + "\n" + block.text)
        block.text = text[:ends[-1]]
    if originals:
        appendix = "\n\n[Adattamento al box: versione estesa dei paragrafi generati]\n" + "\n\n".join(originals)
        content.notes = content.notes[:max(0, 6000-len(appendix))] + appendix
    return bool(originals)
