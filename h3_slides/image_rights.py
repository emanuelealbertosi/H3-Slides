"""Conservative Openverse candidates and work-specific source-page evidence.

Adapted from H3-Documentary's MIT-licensed image_search/image_rights helpers.
No network requests, execution of page content, or inference of missing rights.
DNS and redirect validation remain the downloader's responsibility.
"""
import hashlib
import html
from html.parser import HTMLParser
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from .web_research import public_url

MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 12
MAX_ITEMS = 100
_VERSIONS = {"1.0", "2.0", "2.5", "3.0", "4.0"}
_STOP_WORDS = set(
    "a an the of in on at for with and or to from by "
    "di del della delle degli dei dell da dal dalla nel nella nelle sul sulla "
    "un una uno il lo la le gli i e o per con al alla "
    "photo photograph photography image picture illustration foto fotografia immagine".split()
)


def _plain(value, limit=500):
    if not isinstance(value, str) or len(value) > 5000:
        return ""
    if re.search(r"<\s*(?:script|style|iframe|object)\b", value, re.I):
        return ""
    value = html.unescape(re.sub(r"<[^>]*>", " ", value))
    if any(ord(c) < 32 and c not in "\t\r\n" for c in value):
        return ""
    return " ".join(value.split())[:limit]


def _normal(value):
    # Do not truncate identity comparisons: titles differing after 500
    # characters still identify different works.
    value = unicodedata.normalize("NFKD", _plain(value, 5000)).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", value).replace("_", " ").split())


def _https_url(value):
    if not isinstance(value, str) or any(ord(c) <= 32 for c in value):
        return None
    try:
        safe = public_url(value)
        return safe if urlsplit(safe).scheme == "https" else None
    except (ValueError, TypeError):
        return None


def _license_url(value):
    """Recognize only explicit, unported reuse grants with no NC/ND terms."""
    safe = _https_url(value)
    if not safe:
        return None
    parsed = urlsplit(safe)
    if (parsed.hostname not in {"creativecommons.org", "www.creativecommons.org"}
            or parsed.port not in (None, 443) or parsed.query or urlsplit(value).fragment):
        return None
    path = parsed.path.lower().strip("/")
    suffix = r"(?:/(?:legalcode|deed)(?:\.[a-z]{2,3}(?:[-_][a-z]{2,4})?)?)?"
    grant = re.fullmatch(r"licenses/(by|by-sa)/(1\.0|2\.0|2\.5|3\.0|4\.0)" + suffix, path)
    if grant:
        code, version = grant.groups()
        return code, version, f"https://creativecommons.org/licenses/{code}/{version}/"
    grant = re.fullmatch(r"publicdomain/(zero|mark)/(1\.0)" + suffix, path)
    if grant:
        kind, version = grant.groups()
        return ("cc0" if kind == "zero" else "pdm"), version, (
            f"https://creativecommons.org/publicdomain/{kind}/{version}/")
    return None


def _license_details(code, version, link):
    if not isinstance(code, str) or not isinstance(version, str):
        return None
    if code not in {"cc0", "pdm", "by", "by-sa"}:
        return None
    if version not in ({"1.0"} if code in {"cc0", "pdm"} else _VERSIONS):
        return None
    grant = _license_url(link)
    if not grant or grant[:2] != (code, version):
        return None
    label = ("Public domain" if code == "pdm" else "CC0 1.0" if code == "cc0"
             else f"CC {code.upper()} {version}")
    return {"license": code, "license_version": version,
            "license_label": label, "license_url": grant[2]}


def _relevant(title, query):
    """Keep the query's meaningful terms; never broaden or translate its topic."""
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 180:
        return False
    words = [word for word in _normal(query).split() if word not in _STOP_WORDS]
    title_words = set(_normal(title).split())
    if not words or len(words) > 12 or not set(words).issubset(title_words):
        return False
    # A numbered successor is a different subject, not a harmless title suffix.
    roman = {"ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}
    return not ((title_words & roman) - set(words))


def openverse_candidate(row, query):
    """Return a normalized candidate, retaining Openverse's original license code."""
    if not isinstance(row, dict):
        return None
    if any(row.get(flag) is not None and row.get(flag) is not False
           for flag in ("mature", "removed_from_source", "watermarked")):
        return None
    if not isinstance(row.get("title"), str) or len(row["title"]) > 500:
        return None
    if not isinstance(row.get("id"), str) or len(row["id"]) > 200:
        return None
    title, author, ident = (_plain(row.get("title")), _plain(row.get("creator")),
                            _plain(row.get("id"), 200))
    if not title or not author or not ident or not _relevant(title, query):
        return None
    image_url = _https_url(row.get("url"))
    source_url = _https_url(row.get("foreign_landing_url"))
    policy = _license_details(row.get("license"), row.get("license_version"),
                              row.get("license_url"))
    if not image_url or not source_url or not policy:
        return None
    return {**row, **policy, "id": ident, "title": title, "author": author,
            "url": image_url, "foreign_landing_url": source_url}


class _RightsPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.head = False
        self.seen_head = False
        self.body_started = False
        self.json_script = None
        self.structured = []
        self.meta = {}
        self.licenses = []
        self.items = 0

    def _count(self):
        self.items += 1
        if self.items > MAX_ITEMS:
            raise ValueError("Too many rights metadata items")

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "head":
            self.head = not self.seen_head and not self.body_started
            self.seen_head = True
        elif tag == "body" or (not self.head and tag != "html"):
            self.body_started = True
            self.head = False
        if tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self._count()
            self.json_script = []
        if self.head and tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key in {"og:image", "og:title"}:
                self._count()
                self.meta.setdefault(key, []).append(attrs.get("content") or "")
        if self.head and tag == "link" and "license" in (attrs.get("rel") or "").lower().split():
            self._count()
            self.licenses.append(attrs.get("href") or "")

    def handle_data(self, data):
        if self.json_script is not None:
            self.json_script.append(data)

    def handle_endtag(self, tag):
        if tag == "head":
            self.head = False
        if tag == "script" and self.json_script is not None:
            try:
                self.structured.append(json.loads("".join(self.json_script)))
            except (ValueError, RecursionError):
                pass
            self.json_script = None


def _objects(value):
    """Walk bounded structured metadata; exceeding a limit invalidates the proof."""
    stack, seen = [(value, 0)], 0
    while stack:
        current, depth = stack.pop()
        if not isinstance(current, (dict, list)):
            continue
        seen += 1
        if depth > MAX_DEPTH or seen > MAX_ITEMS or len(current) > MAX_ITEMS:
            raise ValueError("Structured metadata exceeds limits")
        if isinstance(current, dict):
            yield current
            children = current.values()
        else:
            children = current
        stack.extend((child, depth + 1) for child in children)


def source_license_evidence(raw, final_source_url, candidate):
    """Confirm the exact bitmap, title and grant on the downloaded source page."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_PAGE_BYTES:
        return None
    source_url = _https_url(final_source_url)
    if not source_url or not isinstance(candidate, dict):
        return None
    image_url = _https_url(candidate.get("url"))
    title = _normal(candidate.get("title"))
    policy = _license_details(candidate.get("license"), candidate.get("license_version"),
                              candidate.get("license_url"))
    if not image_url or not title or not policy:
        return None
    try:
        page = _RightsPage()
        page.feed(raw.decode("utf-8", "replace"))
        page.close()
        found = []
        accepted_types = {"ImageObject", "Photograph", "https://schema.org/ImageObject",
                          "http://schema.org/ImageObject", "https://schema.org/Photograph",
                          "http://schema.org/Photograph"}
        # One traversal budget for the entire page, not a fresh budget per script.
        for item in _objects(page.structured):
            types = item.get("@type")
            types = [types] if isinstance(types, str) else types
            if (not isinstance(types, list) or not all(isinstance(t, str) for t in types)
                    or not accepted_types.intersection(types)):
                continue
            if (item.get("contentUrl", item.get("url")) != image_url
                    or _normal(item.get("name")) != title):
                continue
            link = item.get("license")
            if isinstance(link, dict):
                link = link.get("@id", link.get("url"))
            if link is not None:
                found.append((link, "jsonld_imageobject"))
        # The actual HTML head must identify one exact work. Footer/global
        # licenses and metadata describing a different image cannot grant reuse.
        if (page.meta.get("og:image") and page.meta.get("og:title")
                and all(value == image_url for value in page.meta["og:image"])
                and all(_normal(value) == title for value in page.meta["og:title"])):
            found.extend((urljoin(source_url, link), "head_rel_license") for link in page.licenses)
        if not found:
            return None
        for link, _ in found:
            grant = _license_url(link)
            if not grant or grant != (policy["license"], policy["license_version"], policy["license_url"]):
                return None
        return {"url": source_url, "method": found[0][1], "license": policy["license"],
                "license_label": policy["license_label"], "license_url": policy["license_url"],
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "page_sha256": hashlib.sha256(raw).hexdigest()}
    except (ValueError, TypeError, RecursionError):
        return None
