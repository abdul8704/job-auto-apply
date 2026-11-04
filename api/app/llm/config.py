"""Loads config/llm.yaml: which provider and model serves each role."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    type: str  # gemini | fake  (add anthropic, openai, ollama adapters later)
    api_key_env: str | None = None
    options: dict = Field(default_factory=dict)


class Target(BaseModel):
    provider: str
    model: str


class RoleConfig(Target):
    temperature: float = 0.2
    max_tokens: int = 4096
    fallback: list[Target] = Field(default_factory=list)


class LLMConfig(BaseModel):
    providers: dict[str, ProviderConfig]
    roles: dict[str, RoleConfig]
    max_retries: int = 3
    schema_retries: int = 1

    @classmethod
    def load(cls, path: Path) -> "LLMConfig":
        cfg = cls.model_validate(yaml.safe_load(path.read_text()))
        for role, rc in cfg.roles.items():
            for target in [rc, *rc.fallback]:
                if target.provider not in cfg.providers:
                    raise ValueError(f"role {role!r} uses unknown provider {target.provider!r}")
        return cfg
