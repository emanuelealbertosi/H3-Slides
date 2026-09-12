"""Read-only browsing of images in the document pages actually processed.

Selections remain the authority even if the brief has since changed. We never
expand a previous chapter to a whole book merely because a setting was edited.
The caller reads the current project on the event loop; this helper does not
touch SQLite and can safely run its bounded file I/O in a worker thread.
"""
import copy
import hashlib
import io
import json
import re
import threading
import time
import warnings
from pathlib import Path

from PIL import Image, ImageOps

from .source_images import ranked_source_images
from .storage import uid


_FORMATS = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_BYTES = 20 * 1024 * 1024
_EXPIRED = "Ricerca documentale scaduta o non disponibile: premi Cerca per ripeterla"
_CHANGED = "Le fonti o la porzione lavorata sono cambiate: ripeti la ricerca nel documento"


def _asset_path(store, pid, name, *, index=False):
    """Same containment rules as Store.asset_path, without DB calls or mkdir."""
    if not isinstance(pid, str) or not pid or Path(pid).name != pid or any(c in pid for c in "/\\:"):
        raise ValueError("Progetto non valido")
    if not isinstance(name, str) or not name or Path(name).name != name or any(c in name for c in "/\\:"):
        raise ValueError("Risorsa documentale non valida")
    if Path(name).suffix.lower() not in ({".json"} if index else _FORMATS):
        raise ValueError("Formato risorsa documentale non valido")
    assets = (Path(store.root) / "assets").resolve()
    root = (assets / pid).resolve()
    path = (root / name).resolve()
    if not root.is_relative_to(assets) or root == assets or not path.is_relative_to(root):
        raise ValueError("Percorso documentale non valido")
    return path


def _fingerprint(project):
    values = {"prompt": project.get("prompt", ""), "pdf_scope": project.get("pdf_scope", "auto"),
              "sources": project.get("sources", [])}
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _page_texts(store, project, source):
    name = source.get("page_index_file")
    if not name:
        return {}
    try:
        path = _asset_path(store, project["id"], name, index=True)
        if path.stat().st_size > 32 * 1024 * 1024:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        pages = value.get("pages", []) if isinstance(value, dict) else []
        return {p["pdf_page"]: str(p.get("text", ""))[:12000]
                for p in (pages if isinstance(pages, list) else [])[:1500]
                if isinstance(p, dict) and type(p.get("pdf_page")) is int}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _pdf_pages(source):
    selection = source.get("selection")
    if not isinstance(selection, dict):
        return None
    pages = selection.get("pdf_pages")
    count = source.get("page_count", 1500)
    if type(count) is not int or not 1 <= count <= 1500:
        return None
    if not isinstance(pages, list) or not pages or len(pages) > 1500:
        return None
    if any(type(page) is not int or not 1 <= page <= count for page in pages):
        return None
    return set(pages)


def _catalog(store, project, include_pages):
    result, messages, scopes, seen = [], [], [], set()
    fingerprint = hashlib.sha256(str(project.get("prompt", "")).encode()).hexdigest()
    missing = 0
    for source in project.get("sources", []):
        name = str(source.get("name") or "Documento")[:240]
        pdf = source.get("kind") == "pdf" or bool(source.get("pdf_file") or source.get("page_index_file"))
        selected = _pdf_pages(source) if pdf else None
        selection = source.get("selection") or {}
        if pdf and selected is None:
            messages.append(f"{name}: porzione non ancora individuata. Genera o rigenera per selezionare le pagine del documento.")
            scopes.append({"document": name, "source_id": source.get("id"), "status": "unprepared", "summary": "Porzione non ancora individuata"})
            continue
        if pdf:
            all_pages = len(selected) == source.get("page_count")
            summary = str(selection.get("summary") or
                          ("Documento completo" if all_pages else "Pagine PDF " + ", ".join(map(str, sorted(selected)))))[:700]
            messages.append(f"{name}: {summary}.")
            scopes.append({"document": name, "source_id": source.get("id"), "status": "ready",
                           "summary": summary, "whole": all_pages, "page_count": len(selected)})
            if ((selection.get("prompt_hash") and selection["prompt_hash"] != fingerprint) or
                    selection.get("scope_mode", "auto") != project.get("pdf_scope", "auto")):
                messages.append(f"{name}: mostro l'ultima porzione lavorata; le nuove istruzioni o l'opzione Documento intero non sono ancora state applicate.")
        pages = _page_texts(store, project, source)
        for item in source.get("images", []):
            image_id = item.get("id")
            if image_id in seen:
                continue
            label = str(item.get("label") or name)[:240]
            kind = item.get("kind") or "image"
            if kind == "image" and re.search(r"(?i)\bpagina\s+PDF\s+\d+", label):
                kind = "figure" if label.lstrip().lower().startswith("figura") else "page"
            page = item.get("pdf_page")
            if type(page) is not int:
                match = re.search(r"(?i)\bpagina\s+PDF\s+(\d+)\b", label)
                page = int(match[1]) if match else None
            if pdf and page not in selected:
                continue
            if kind == "page" and not include_pages:
                continue
            try:
                path = _asset_path(store, project["id"], image_id)
                if not path.is_file() or not 0 < path.stat().st_size <= _MAX_BYTES:
                    missing += 1
                    continue
            except (ValueError, OSError):
                missing += 1
                continue
            description = " ".join(str(item.get(key) or "")[:700] for key in ("caption", "description")).strip()
            context = (description + "\n" + pages.get(page, "")).strip()
            if not context:
                context = str(source.get("text") or "")[:12000]
            # Labels can rank standalone photos, while PDF context comes from
            # the literal page text. This is lexical retrieval, not vision.
            result.append({"image_id": image_id, "source_id": source.get("id"), "label": label,
                "document": name, "source": label, "pdf_page": page if pdf else None,
                "kind": kind, "context": context, "description": (description + " " + label).strip(),
                "image_provider": "Documento locale", "license": "", "author": ""})
            seen.add(image_id)
    if missing:
        messages.append(f"{missing} immagini non disponibili sul disco sono state escluse.")
    if not result and not messages:
        messages.append("Nessuna immagine disponibile nei documenti allegati.")
    if not include_pages and any(s.get("status") == "ready" for s in scopes):
        messages.append("Per scansioni o figure non estratte puoi includere anche le pagine intere.")
    return result, list(dict.fromkeys(messages)), scopes


class DocumentImageSearch:
    ttl = 15 * 60

    def __init__(self):
        self.searches = {}
        self._lock = threading.RLock()

    def prune(self):
        with self._lock:
            for key in list(self.searches):
                if self.searches[key]["expires"] < time.monotonic():
                    del self.searches[key]

    def _lookup(self, project, sid, ident):
        self.prune()
        state = self.searches.get(ident)
        if not state or state["scope"] != (project["id"], sid):
            raise ValueError(_EXPIRED)
        if state["fingerprint"] != _fingerprint(project):
            raise ValueError(_CHANGED)
        return state

    def search(self, store, project, sid, request):
        with self._lock:
            ident = request.search_id
            if not ident:
                if request.page:
                    raise ValueError("Inizia dalla prima pagina dei risultati")
                self.prune()
                rows, messages, scopes = _catalog(store, project, request.include_pages)
                query = " ".join(request.query.split())
                if query:
                    rows = ranked_source_images(rows, query, limit=len(rows))
                    messages.append("Ordinate per il testo della pagina e le etichette; non viene eseguito riconoscimento visivo.")
                # The textual evidence is only needed while ranking. Never
                # retain full page excerpts for every cached thumbnail.
                rows = [{**{key: value for key, value in row.items()
                            if key not in {"context", "description", "confident", "score"}},
                         "id": uid(), "query": query} for row in rows]
                while len(self.searches) >= 24:
                    del self.searches[next(iter(self.searches))]
                ident = "doc-" + uid()
                self.searches[ident] = {"scope": (project["id"], sid), "expires": time.monotonic()+self.ttl,
                    "fingerprint": _fingerprint(project), "rows": rows,
                    "results": {}, "pages": [], "message": " ".join(messages), "scopes": scopes}
            state = self._lookup(project, sid, ident)
            if request.page < len(state["pages"]):
                return copy.deepcopy(state["pages"][request.page])
            if request.page != len(state["pages"]):
                raise ValueError("Carica i risultati in ordine con Altro")
            start = request.page * 10
            rows = state["rows"][start:start+10]
            public = []
            for row in rows:
                state["results"][row["id"]] = row
                public.append({key: row[key] for key in
                    ("id", "label", "document", "pdf_page", "kind", "source", "image_provider", "license", "author")})
            page = {"search_id": ident, "page": request.page, "results": public,
                    "has_more": start+10 < len(state["rows"]),
                    "total": len(state["rows"]), "message": state["message"], "scopes": state["scopes"]}
            state["pages"].append(page)
            return copy.deepcopy(page)

    def result(self, store, project, sid, search_id, result_id):
        with self._lock:
            state = self._lookup(project, sid, search_id)
            row = state["results"].get(result_id)
            if row is None:
                raise KeyError("Immagine non presente nei risultati")
            path = _asset_path(store, project["id"], row["image_id"])
            try:
                if not path.is_file() or not 0 < path.stat().st_size <= _MAX_BYTES:
                    raise ValueError("Immagine del documento non più disponibile: ripeti la ricerca")
            except OSError as exc:
                raise ValueError("Immagine del documento non più disponibile: ripeti la ricerca") from exc
            return copy.deepcopy(row)

    def preview(self, store, project, sid, search_id, result_id):
        row = self.result(store, project, sid, search_id, result_id)
        path = _asset_path(store, project["id"], row["image_id"])
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as original:
                    if original.width * original.height > 40_000_000:
                        raise ValueError("Immagine del documento troppo grande")
                    image = ImageOps.exif_transpose(original).convert("RGB")
                    image.thumbnail((400, 300))
                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=84)
                    return output.getvalue()
        except (OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            raise ValueError("Anteprima del documento non disponibile") from exc
