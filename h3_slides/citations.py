"""Resolve complete citation forms against already acquired web sources only."""

import re
from datetime import date


class SourceCitationError(ValueError):
    """The slide did not identify any source that the app actually acquired."""


_ID = re.compile(r"(?:W[1-9]\d*|\[W[1-9]\d*\])")
_ID_TITLE = re.compile(r"(W[1-9]\d*|\[W[1-9]\d*\])\s*[·—–]\s*(.+)", re.DOTALL)
_CANONICAL = re.compile(r"(.+?)\s+—\s+(\S+)\s+\(consultato (\d{4}-\d{2}-\d{2})\)", re.DOTALL)
_DATED_LINK = re.compile(r"(.+)\s+\(consultato (\d{4}-\d{2}-\d{2})\)", re.DOTALL)


def _title(value):
    # Line wrapping is cosmetic; words, case, and punctuation identify the title.
    return " ".join(value.split())


def _unique(sources):
    return sources[0] if len(sources) == 1 else None


def _valid_date(value):
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def resolve_web_source(ref: str, research: dict) -> dict | None:
    """Accept known IDs, URLs and complete app/Markdown citation forms.

    This is normalization, not evidence discovery: no network, fuzzy matches,
    URL rewriting, substring ID extraction, or default choice of a source.
    Formatted titles guard against IDs being reassigned on a later web search.
    """
    if not isinstance(ref, str) or not isinstance(research, dict):
        return None
    raw_sources = research.get("sources", [])
    if not isinstance(raw_sources, list):
        return None
    sources = [source for source in raw_sources if isinstance(source, dict)
               and all(isinstance(source.get(key), str) and source[key].strip()
                       for key in ("id", "title", "url"))]
    ref = ref.strip()
    if not ref:
        return None
    if _ID.fullmatch(ref):
        return _unique([source for source in sources if source["id"] == ref.strip("[]")])
    by_url = [source for source in sources if source["url"] == ref]
    if by_url:
        return _unique(by_url)

    formatted = _ID_TITLE.fullmatch(ref)
    if formatted:
        source_id, title = formatted.groups()
        matching = [source for source in sources if _title(source["title"]) == _title(title)]
        # The worker's readable block source is exactly ID + " · " + title[:170].
        # Accept that one historical abbreviation, never an arbitrary prefix.
        # Truncation can erase the part that distinguishes two sources, so even
        # the apparent current ID cannot resolve a collision safely.
        abbreviated = [source for source in sources if len(source["title"]) > 170
                       and _title(source["title"][:170]) == _title(title)
                       and source not in matching]
        if abbreviated:
            return _unique(matching + abbreviated)
        same_id = [source for source in matching if source["id"] == source_id.strip("[]")]
        return _unique(same_id) if same_id else _unique(matching)

    canonical = _CANONICAL.fullmatch(ref)
    if canonical:
        title, url, consulted = canonical.groups()
        if not _valid_date(consulted):
            return None
        return _unique([source for source in sources if source["url"] == url
                        and _title(source["title"]) == _title(title)])

    # Keep the complete-link boundary. A known URL buried in unsupported prose
    # must not make an otherwise ungrounded citation appear to be valid.
    dated = _DATED_LINK.fullmatch(ref)
    if dated:
        ref, consulted = dated.groups()
        if not _valid_date(consulted):
            return None
    if not ref.startswith("["):
        return None
    matching = []
    for source in sources:
        for target in (source["url"], "<" + source["url"] + ">"):
            ending = "](" + target + ")"
            if not ref.endswith(ending):
                continue
            label = ref[1:-len(ending)].strip()
            # A link's exact URL is stable even if a historical ID was remapped.
            valid_label = (_title(label) == _title(source["title"])
                           or label == source["url"] or _ID.fullmatch(label))
            titled = _ID_TITLE.fullmatch(label)
            if titled:
                valid_label = (_title(titled.group(2)) == _title(source["title"])
                               or resolve_web_source(label, research) is source)
            full = _CANONICAL.fullmatch(label)
            if full:
                valid_label = (full.group(2) == source["url"] and _valid_date(full.group(3))
                               and _title(full.group(1)) == _title(source["title"]))
            if valid_label:
                matching.append(source)
                break
    return _unique(matching)
