"""Display-only source code normalization. Code is never executed."""
import re

LANGUAGES = {"python", "c", "cpp", "javascript", "java", "sql", "text"}


def normalize_code_block(value):
    if not isinstance(value, dict):
        return value
    text = value.get("text", "")
    if not isinstance(text, str):
        return value
    fence = re.fullmatch(r"\s*`{3}(\w+|c\+\+)?[^\S\n]*\n([\s\S]*?)\n`{3}\s*", text)
    if fence:
        language = (fence[1] or value.get("language") or "text").lower()
        language = {"py": "python", "c++": "cpp", "js": "javascript"}.get(language, language)
        return {**value, "kind": "code", "language": language if language in LANGUAGES else "text", "text": fence[2]}
    return value
