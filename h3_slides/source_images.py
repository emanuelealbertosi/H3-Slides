"""Select source illustrations by slide/page context, without another model call.

Full PDF page previews are retrieval material, not interchangeable with figures.
The model gets a ranked, bounded catalogue; a deterministic selection is allowed
only with concrete lexical evidence in a figure's page or supplied description.
"""
import json
import math
from collections import Counter

from .retrieval import evidence_tokens, rank_evidence

_PRESENTATION_WORDS = set(
    "spiega spiegare descrivi descrizione mostra mostrare presentazione slide slides "
    "confronto esempio esempi introduzione conclusione figura figure documento "
    "manuale pagina pagine pdf panoramica funzionamento funzione funzioni".split()
)


def _tokens(text):
    return [word for word in evidence_tokens(text) if word not in _PRESENTATION_WORDS]


def source_image_catalog(store, project, available):
    """Read only already-selected source assets; no extraction, network or writes."""
    allowed = {item["image_id"] for item in available}
    result, seen = [], set()
    for source in project.get("sources", []):
        pages = {}
        if source.get("page_index_file"):
            try:
                path = store.asset_path(project["id"], source["page_index_file"])
                if path.stat().st_size <= 32 * 1024 * 1024:
                    index = json.loads(path.read_text(encoding="utf-8"))
                    records = index.get("pages", []) if isinstance(index, dict) else []
                    pages = {page["pdf_page"]: str(page.get("text", ""))[:12000]
                             for page in (records if isinstance(records, list) else [])[:1500]
                             if isinstance(page, dict)}
            except (OSError, ValueError, KeyError, TypeError):
                pages = {}
        for item in source.get("images", []):
            image_id = item.get("id")
            if image_id not in allowed or image_id in seen:
                continue
            label = str(item.get("label") or source.get("name", ""))[:240]
            kind = item.get("kind", "")
            legacy_page = ("pagina PDF" in label and not label.startswith("Figura") and not kind)
            if kind == "page" or legacy_page:
                continue
            description = " ".join(str(item.get(key) or "")[:700] for key in ("caption", "description"))
            page_text = pages.get(item.get("pdf_page"), "")
            # Plain image attachments can use their own description or source text.
            context = (description + "\n" + page_text).strip()
            if not context:
                context = str(source.get("text") or "")[:12000]
            result.append({
                "image_id": image_id, "source": label, "kind": kind or "image",
                "pdf_page": item.get("pdf_page"), "context": context,
                "description": description.strip(),
            })
            seen.add(image_id)
    return result


def ranked_source_images(catalog, query, limit=12):
    """Rank the whole illustration catalogue before limiting model context."""
    query_terms = set(_tokens(query))
    counts = [Counter(_tokens(item["context"] + " " + item["description"])) for item in catalog]
    frequencies = Counter(word for words in counts for word in words)
    average = sum(sum(words.values()) for words in counts) / max(1, len(counts)) or 1
    ranked = []
    for index, (item, words) in enumerate(zip(catalog, counts)):
        matched = query_terms & words.keys()
        length = sum(words.values())
        score = sum(
            math.log(1 + (len(catalog) - frequencies[word] + .5) / (frequencies[word] + .5)) *
            (words[word] * 2.5) / (words[word] + 1.5 * (.25 + .75 * length / average))
            for word in matched
        )
        # A lone generic match must not silently attach an unrelated illustration.
        distinctive_single = len(query_terms) == 1 and bool(matched)
        confident = bool(item["context"].strip()) and (len(matched) >= 2 or distinctive_single)
        ranked.append({**item, "score": score, "confident": confident, "_order": index})
    ranked.sort(key=lambda item: (-item["score"], item["_order"]))
    return [{key: value for key, value in item.items() if key != "_order"} for item in ranked[:limit]]


def image_prompt_catalog(ranked, query):
    """Page context is sent only to the consented LLM, never to an image search engine."""
    # Rank every figure, but keep the extra prompt bounded also on 8K providers.
    excerpt_limit = min(700, 3200 // max(1, len(ranked)))
    return [{
        "image_id": item["image_id"], "source": item["source"], "kind": item["kind"],
        "page_excerpt": (rank_evidence([{"label": item["source"], "text": item["context"]}],
                                       query, limit=excerpt_limit) or item["description"])[:excerpt_limit],
    } for item in ranked]


def automatic_source_image(ranked):
    return next((item for item in ranked if item["confident"] and item["score"] > 0), None)
