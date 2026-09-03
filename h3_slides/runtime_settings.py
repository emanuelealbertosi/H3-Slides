from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


class LoadingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context_size: int = Field(default=16384, ge=512, le=131072)
    gpu_layers: int = Field(default=-1, ge=-1, le=999)
    threads: int = Field(default=6, ge=1, le=128)
    batch_size: int = Field(default=2048, ge=32, le=4096)
    ubatch_size: int = Field(default=512, ge=16, le=2048)
    flash_attention: Literal["auto", "on", "off"] = "auto"
    cache_type_k: Literal["f16", "q8_0", "q4_0"] = "f16"
    cache_type_v: Literal["f16", "q8_0", "q4_0"] = "f16"
    load_mode: Literal["auto", "mmap", "none"] = "auto"
    cpu_moe_layers: int = Field(default=0, ge=0, le=999)
    @model_validator(mode="after")
    def consistent_batches(self):
        if self.ubatch_size > self.batch_size:
            raise ValueError("Il micro-batch non può superare il batch")
        return self


class InferenceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature: float = Field(default=.35, ge=0, le=2)
    top_p: float = Field(default=.95, gt=0, le=1)
    top_k: int = Field(default=40, ge=0, le=200)
    min_p: float = Field(default=.05, ge=0, le=1)
    repeat_penalty: float = Field(default=1, ge=.5, le=2)
    max_tokens: int = Field(default=3500, ge=128, le=16384)
    seed: int = Field(default=-1, ge=-1, le=2147483647)
    thinking: bool = False


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    loading: LoadingSettings = Field(default_factory=LoadingSettings)
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
