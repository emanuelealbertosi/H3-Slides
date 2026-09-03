"""Serializable, validated themes; no executable CSS, URLs or machine paths."""
import json
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

COLOR = r"^(#[0-9a-fA-F]{6})?$"


class ThemeDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text_color: str = Field(default="", pattern=COLOR)
    title_color: str = Field(default="", pattern=COLOR)
    box_text_color: str = Field(default="", pattern=COLOR)
    explanation_color: str = Field(default="", pattern=COLOR)
    example_color: str = Field(default="", pattern=COLOR)
    key_color: str = Field(default="", pattern=COLOR)
    quote_color: str = Field(default="", pattern=COLOR)
    border_color: str = Field(default="", pattern=COLOR)
    border_width: int = Field(default=0, ge=0, le=5)
    box_radius: int = Field(default=18, ge=0, le=32)
    title_size: int = Field(default=0, ge=0, le=76)
    body_size: int = Field(default=0, ge=0, le=32)

    @field_validator("title_size", "body_size")
    @classmethod
    def readable_size(cls, value, info):
        if value and value < (32 if info.field_name == "title_size" else 16):
            raise ValueError("Usa 0 per automatico oppure una dimensione leggibile")
        return value


class ThemeValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: Literal["ink", "paper", "forest"] = "paper"
    font: Literal["Arial", "Calibri", "Segoe UI", "Georgia", "Verdana", "Consolas"] = "Arial"
    template: Literal["auto", "editorial", "cards", "steps", "split", "minimal"] = "auto"
    background_color: str = Field(default="#ffffff", pattern=COLOR)
    accent_color: str = Field(default="#2563eb", pattern=COLOR)
    theme_design: ThemeDesign = Field(default_factory=ThemeDesign)


class ThemePreset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    values: ThemeValues

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Scrivi un nome per il tema")
        return value.strip()


class ThemeLibrary:
    def __init__(self, root):
        self.path = root / "themes.json"

    def list(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def save(self, data):
        preset = ThemePreset.model_validate(data).model_dump()
        saved = self.list()
        existing = next((i for i, p in enumerate(saved) if p["name"].casefold() == preset["name"].casefold()), None)
        if existing is not None:
            saved[existing] = preset
        else:
            if len(saved) >= 30:
                raise ValueError("Massimo 30 temi personali; aggiorna un tema esistente")
            saved.append(preset)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
        return preset
