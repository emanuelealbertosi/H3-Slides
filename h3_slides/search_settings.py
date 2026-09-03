"""Machine-local search settings. No service discovery or process ownership."""
import json
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, field_validator


class SearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    searxng_url: str = "http://127.0.0.1:8080"

    @field_validator("searxng_url")
    @classmethod
    def local_endpoint(cls, value):
        p = urlsplit(value)
        if (p.scheme not in ("http", "https") or p.hostname not in ("127.0.0.1", "localhost", "::1")
                or p.username is not None or p.password is not None or p.path not in ("", "/")
                or p.query or p.fragment or p.port == 0 or "\\" in value
                or any(ord(c) < 33 for c in value)):
            raise ValueError("SearXNG: usa un indirizzo locale, per esempio http://127.0.0.1:8080, senza percorsi o credenziali")
        return value.rstrip("/")


class SearchConfig:
    def __init__(self, root):
        self.path = root / "search_settings.json"

    def read(self):
        value = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        return SearchSettings.model_validate(value).model_dump()

    def save(self, data):
        value = SearchSettings.model_validate(data).model_dump()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temp.replace(self.path)
        return value
