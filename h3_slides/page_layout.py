"""Measured, bounded page layout and lossless overflow recovery for V2."""
import asyncio
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from .llm import ChildGuard
from .page_v2 import PAGE_SYSTEM, PageSpec

HEIGHTS = {"16:9": 720, "4:3": 960, "16:10": 800, "1:1": 1280}


def format_brief(project):
    name = project.get("slide_format", "16:9")
    height = HEIGHTS.get(name, 720)
    maximum = math.ceil(height*1.15) if project.get("canvas_mode") == "adaptive" else height
    budget = round((height-180)*2.6)
    return (f"Formato {name}: larghezza 1280 px, altezza nominale {height} px, massimo {maximum} px. "
            f"Obiettivo indicativo: {budget} caratteri visibili complessivi, meno se inserisci immagini, codice o diagrammi. "
            "Non è un limite da riempire: usa paragrafi veri ma proporzionati alla singola slide. "
            "Font corpo 22–28 px (minimo 20), titolo 36–48, codice minimo 18. "
            "Testi/diagrammi devono essere leggibili entro il formato; niente lunghe colonne verticali. "
            "Distribuisci gli approfondimenti nella sequenza, non in una sola pagina lunga.")


class PageMeasurer:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store

    async def measure(self, project, page):
        dimensions = {}
        for node in page.nodes:
            if not node.asset_id:
                continue
            path = self.store.asset_path(project["id"], node.asset_id)
            if not path.is_file():
                raise ValueError("Immagine della pagina non trovata: ripristinala prima di verificarne l'impaginazione")
            try:
                with Image.open(path) as image:
                    dimensions[node.asset_id] = {"width": image.width, "height": image.height}
            except (OSError, ValueError):
                raise ValueError("Immagine della pagina non leggibile: sostituiscila prima di verificarne l'impaginazione") from None
        keys = ("id", "title", "engine", "theme", "font", "canvas_mode", "slide_format",
                "background_color", "accent_color", "theme_design", "graphic_style", "use_manim_diagrams")
        payload = {"project": {key: project[key] for key in keys if key in project},
                   "page": page.model_dump(), "_media_dimensions": dimensions}
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(self.root/"runtime/browsers")}
        node = self.root/"runtime/node/node.exe"
        if not node.is_file():
            raise ValueError("Controllo impaginazione non disponibile: verifica l'installazione di Node e del browser")
        guard = ChildGuard()
        process = None
        try:
            process = subprocess.Popen([str(node), str(self.root/"scripts/measure_page.mjs")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.root, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=os.name != "nt")
            guard.assign(process)
            stdout, _ = await asyncio.to_thread(process.communicate,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=30)
            if process.returncode:
                raise ValueError("Controllo impaginazione non riuscito. La bozza è conservata; verifica i componenti dell'app.")
            report = json.loads(stdout)
            if not isinstance(report, dict) or type(report.get("overflow")) is not bool:
                raise ValueError("Esito del controllo impaginazione non valido")
            return report
        except subprocess.TimeoutExpired:
            raise ValueError("Controllo impaginazione troppo lento. Bozza conservata: riprova.") from None
        finally:
            # The dedicated job owns only this probe and Chromium, never the LLM.
            guard.close()
            if process and process.poll() is None:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                await asyncio.to_thread(process.wait)


class PageReflow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pages: list[PageSpec] = Field(min_length=1, max_length=3)


def ordered_leaves(page):
    result = []
    def walk(parent):
        for node in page.nodes:
            if node.parent != parent:
                continue
            if node.kind == "group":
                walk(node.id)
            else:
                result.append(node)
    walk("root")
    return result


def main_heading(page):
    leaves = ordered_leaves(page)
    return next((n for n in leaves if n.kind == "heading" and n.role == "title"),
                next((n for n in leaves if n.kind == "heading"), None))


def preserves_content(original, pages):
    """A layout repair cannot paraphrase, omit, invent or replace any content."""
    expected = {n.id: n for n in ordered_leaves(original)}
    title = main_heading(original)
    seen = {}
    order = []
    for page in pages:
        for node in ordered_leaves(page):
            old = expected.get(node.id)
            if old is None or any(getattr(node, key) != getattr(old, key) for key in
                                  ("kind", "text", "language", "asset_id", "query", "source")):
                return False
            seen[node.id] = seen.get(node.id, 0)+1
            if not title or node.id != title.id:
                order.append(node.id)
    expected_order = [key for key in expected if not title or key != title.id]
    return order == expected_order and set(seen) == set(expected) and all(
        value == 1 or (title and key == title.id and value <= len(pages)) for key, value in seen.items())


def _weight(node):
    if node.kind in ("image", "diagram"):
        return 650
    if node.kind == "code":
        return max(len(node.text), len(node.text.splitlines())*65)
    return max(80, len(node.text))


def _text_units(text):
    # Math and inline/fenced code must remain intact even if a single unit is
    # too large: a visible overflow is safer than an invalid half-formula.
    protected = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]|\$\$.*?\$\$|(?<!\\)\$(?!\$)[^\n]*?(?<!\\)\$|\x60+[^\x60]*\x60+", re.DOTALL)
    end = 0
    for match in protected.finditer(text):
        yield from re.findall(r"\S+\s*|\s+", text[end:match.start()])
        yield match.group()
        end = match.end()
    yield from re.findall(r"\S+\s*|\s+", text[end:])


def _parts(node, budget, used):
    if node.kind not in ("text", "code") or _weight(node) <= budget:
        return [node.model_copy(deep=True)]
    units = node.text.splitlines(keepends=True) if node.kind == "code" else _text_units(node.text)
    chunks, current, weight = [], "", 0
    for unit in units:
        cost = max(65, len(unit)) if node.kind == "code" else len(unit)
        if current and weight+cost > budget:
            chunks.append(current)
            current = ""
            weight = 0
        current += unit
        weight += cost
    if current:
        chunks.append(current)
    result = []
    for i, text in enumerate(chunks):
        item = node.model_copy(deep=True)
        if i:
            number = i+1
            item.id = node.id[:35]+f"_part{number}"
            while item.id in used:
                number += 1
                item.id = node.id[:35]+f"_part{number}"
            used.add(item.id)
        item.text = text
        result.append(item)
    return result


def _compact_split_columns(original, result, origins):
    """Pruned fragments must not retain tracks belonging to removed content."""
    original_styles = {"root": original.style, **{n.id: n.style for n in original.nodes if n.kind == "group"}}
    containers = [("root", result.style), *[(n.id, n.style) for n in result.nodes if n.kind == "group"]]
    for parent, style in containers:
        if style.flow != "columns":
            continue
        children = [n for n in result.nodes if n.parent == parent]
        tracks = original_styles[parent].columns
        columns = len(tracks)
        needed = sum(min(columns, node.style.span) for node in children)
        if not 0 < needed < columns:
            continue
        kept = {origins.get(node.id, node.id) for node in children}
        occupied, position = set(), 0
        for node in original.nodes:
            if node.parent != parent:
                continue
            span = min(columns, node.style.span)
            if position+span > columns:
                position = 0
            if node.id in kept:
                occupied.update(range(position, position+span))
            position = (position+span) % columns
        # Retain surviving proportions when they map unambiguously to tracks.
        indices = sorted(occupied) if len(occupied) == needed else list(range(needed))
        style.columns = [tracks[index] for index in indices]
        for node in children:
            node.style.span = min(node.style.span, needed)


def split_page(page, count):
    """Balanced lossless fallback, keeping hierarchy and every original asset."""
    heading = main_heading(page)
    original = [n for n in ordered_leaves(page) if not heading or n.id != heading.id]
    if not original:
        return [page.model_copy(deep=True)]
    used = {n.id for n in page.nodes}
    budget = max(400, math.ceil(sum(_weight(n) for n in original)/count))
    leaves = [(node.id, part) for node in original for part in _parts(node, budget, used)]
    count = min(count, len(leaves))
    buckets, bucket, remaining = [], [], sum(_weight(n) for _, n in leaves)
    for origin, node in leaves:
        target = remaining/max(1, count-len(buckets))
        weight = sum(_weight(n) for _, n in bucket)
        if bucket and len(buckets)<count-1 and weight+_weight(node)/2>target:
            buckets.append(bucket)
            remaining -= weight
            bucket = []
        bucket.append((origin, node))
    if bucket:
        buckets.append(bucket)
    by_id = {n.id: n for n in page.nodes}
    results = []
    for bucket in buckets:
        selected = {heading.id: [heading.model_copy(deep=True)]} if heading else {}
        for origin, node in bucket:
            selected.setdefault(origin, []).append(node)
        ancestors = set()
        for parts in selected.values():
            for node in parts:
                parent = node.parent
                while parent != "root":
                    ancestors.add(parent)
                    parent = by_id[parent].parent
        nodes = []
        for node in page.nodes:
            if node.id in ancestors:
                nodes.append(node.model_copy(deep=True))
            else:
                nodes.extend(selected.get(node.id, []))
        # Preserve original tree/root order, not just the order within each group.
        result = PageSpec(style=page.style.model_copy(deep=True), nodes=nodes,
                          notes=page.notes, sources=list(page.sources))
        _compact_split_columns(page, result, {node.id: origin for origin, parts in selected.items() for node in parts})
        results.append(result)
    return results


async def fit_pages(worker, client, jid, project, page, extra):
    """One measured reflow, then bounded lossless split; no silent clipping."""
    probe = worker.page_measurer
    if probe is None:
        return [page], [{}]
    async def measure(pages):
        reports = []
        for item in pages:
            await worker.checkpoint(jid)
            reports.append(await probe.measure(project, item))
        return reports
    reports = await measure([page])
    if not reports[0]["overflow"]:
        return [page], reports
    maximum = min(3, max(1, extra+1))
    report = reports[0]
    worker.store.event(jid, "V2 · contenuto oltre il formato: riprogettazione dell'impaginazione, senza tagliare testi")
    worker.store.event(jid, f"V2 · controllo formato: altezza richiesta {report.get('neededHeight', 'n.d.')} px, "
                       f"massimo {report.get('maxHeight', 'n.d.')} px · slide aggiuntive ancora disponibili: {maximum-1}")
    geometry = {key: report.get(key) for key in ("height", "neededHeight", "baseHeight", "maxHeight", "nodes")}
    prompt = (format_brief(project)+f"\nRIPROGETTA questa pagina in 1 fino a {maximum} pagine. "
              "Preferisci una singola slide, ma dividila se serve. Non ridurre o riscrivere testi. "
              "Conserva esattamente id, kind, text, language, asset_id, query e source di ogni elemento non group, "
              "una sola volta in totale. Puoi ripetere solo il titolo principale sulle continuazioni. "
              "Cambia gruppi, parent, colonne, spazi, font e ruoli, preservando l'ordine di lettura. "
              "Non aggiungere immagini o diagrammi.\n"
              "MISURE:\n"+json.dumps(geometry, ensure_ascii=False)+"\nPAGINA ORIGINALE (dati):\n"+
              page.model_dump_json())
    try:
        result = PageReflow.model_validate(await client.json(prompt, schema=PageReflow.model_json_schema(), system=PAGE_SYSTEM))
        pages = result.pages
        if len(pages) <= maximum and preserves_content(page, pages):
            for item in pages:
                item.notes, item.sources = page.notes, list(page.sources)
            reports = await measure(pages)
            if not any(r["overflow"] for r in reports):
                return pages, reports
            worker.store.event(jid, "V2 · la riprogettazione supera ancora il formato; provo una divisione conservativa")
        elif len(pages) > maximum:
            worker.store.event(jid, "V2 · riprogettazione oltre il numero di slide consentito; conservo i contenuti originali")
        else:
            worker.store.event(jid, "V2 · la riprogettazione ha cambiato contenuti o ordine; uso la bozza originale senza perdite")
    except (ValueError, TimeoutError):
        await worker.checkpoint(jid)
        worker.store.event(jid, "V2 · riprogettazione non utilizzabile: provo una divisione conservativa dei contenuti")
    for count in range(2, maximum+1):
        pages = split_page(page, count)
        if len(pages) < 2:
            continue
        reports = await measure(pages)
        sizes = ", ".join(str(r.get("neededHeight", "n.d."))+" px" for r in reports)
        worker.store.event(jid, f"V2 · verifica divisione in {len(pages)} slide: {sizes}")
        if not any(r["overflow"] for r in reports):
            worker.store.event(jid, f"V2 · contenuti distribuiti su {len(pages)} slide, testi e immagini conservati")
            return pages, reports
    raise ValueError("Il contenuto non entra nel formato scelto con caratteri leggibili e al massimo due slide aggiuntive. "
                     "Bozza conservata: aumenta il numero obiettivo di slide o riduci il contenuto richiesto.")
