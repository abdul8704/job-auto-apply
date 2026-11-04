"""LLMClient: the one entry point for every LLM call in the app.

Adds what every provider needs: role -> model routing, retries with backoff, fallback providers,
structured output validated with pydantic (and one repair retry), and token logging.
"""

import asyncio
import json
import logging
import os
import re
from collections.abc import Callable
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.base import LLMError, LLMProvider, LLMRequest, LLMResponse, Message, RetriableLLMError, Tool
from app.llm.config import LLMConfig, ProviderConfig
from app.settings import get_settings

log = logging.getLogger("app.llm")
T = TypeVar("T", bound=BaseModel)

ProviderFactory = Callable[[str, ProviderConfig], LLMProvider]


def _gemini_factory(name: str, cfg: ProviderConfig) -> LLMProvider:
    from app.llm.providers.gemini import GeminiProvider

    key = os.environ.get(cfg.api_key_env or "GEMINI_API_KEY", "")
    return GeminiProvider(api_key=key, name=name)


def _fake_factory(name: str, cfg: ProviderConfig) -> LLMProvider:
    from app.llm.providers.fake import FakeProvider

    return FakeProvider(name=name)


PROVIDER_FACTORIES: dict[str, ProviderFactory] = {"gemini": _gemini_factory, "fake": _fake_factory}


def extract_json(text: str) -> str:
    """Models sometimes wrap JSON in ```json fences; strip them."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


class LLMClient:
    def __init__(self, config: LLMConfig, providers: dict[str, LLMProvider] | None = None):
        self.config = config
        self._providers: dict[str, LLMProvider] = dict(providers or {})
        self.backoff_seconds = 1.0

    def provider(self, name: str) -> LLMProvider:
        if name not in self._providers:
            pc = self.config.providers[name]
            if pc.type not in PROVIDER_FACTORIES:
                raise LLMError(f"no adapter for provider type {pc.type!r}")
            self._providers[name] = PROVIDER_FACTORIES[pc.type](name, pc)
        return self._providers[name]

    async def generate(
        self,
        role: str,
        messages: list[Message],
        *,
        schema: type[T] | None = None,
        tools: list[Tool] | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        if role not in self.config.roles:
            raise LLMError(f"unknown LLM role {role!r}")
        rc = self.config.roles[role]
        last_error: Exception | None = None
        for target in [rc, *rc.fallback]:
            request = LLMRequest(
                model=target.model,
                messages=messages,
                json_schema=schema.model_json_schema() if schema else None,
                tools=tools,
                temperature=rc.temperature if temperature is None else temperature,
                max_tokens=rc.max_tokens,
            )
            try:
                return await self._generate_validated(target.provider, request, schema, role)
            except RetriableLLMError as exc:
                log.warning("llm role=%s provider=%s gave up: %s", role, target.provider, exc)
                last_error = exc
        raise LLMError(f"all providers failed for role {role!r}: {last_error}") from last_error

    async def _generate_validated(
        self, provider_name: str, request: LLMRequest, schema: type[T] | None, role: str
    ) -> LLMResponse:
        for attempt in range(self.config.schema_retries + 1):
            resp = await self._call_with_retries(provider_name, request, role)
            if schema is None or resp.tool_calls:
                return resp
            try:
                resp.parsed = schema.model_validate_json(extract_json(resp.text or ""))
                return resp
            except (ValidationError, json.JSONDecodeError) as exc:
                if attempt == self.config.schema_retries:
                    raise LLMError(f"model output did not match {schema.__name__}: {exc}") from exc
                request = request.model_copy(
                    update={
                        "messages": [
                            *request.messages,
                            Message.assistant(resp.text or ""),
                            Message.user(
                                f"That output failed validation:\n{exc}\n"
                                "Reply again with only the corrected JSON."
                            ),
                        ]
                    }
                )
        raise AssertionError("unreachable")

    async def _call_with_retries(self, provider_name: str, request: LLMRequest, role: str) -> LLMResponse:
        provider = self.provider(provider_name)
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = await provider.generate(request)
                log.info(
                    "llm role=%s provider=%s model=%s in=%d out=%d",
                    role,
                    provider_name,
                    request.model,
                    resp.usage.input_tokens,
                    resp.usage.output_tokens,
                )
                return resp
            except RetriableLLMError:
                if attempt == self.config.max_retries:
                    raise
                await asyncio.sleep(self.backoff_seconds * 2**attempt)
        raise AssertionError("unreachable")


@lru_cache
def get_llm() -> LLMClient:
    return LLMClient(LLMConfig.load(get_settings().llm_config_path))
