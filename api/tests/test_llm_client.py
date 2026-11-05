import asyncio

import pytest
from pydantic import BaseModel

from app.llm import LLMClient, LLMError, Message, RetriableLLMError
from app.llm.config import LLMConfig
from app.llm.providers.fake import FakeProvider


class Answer(BaseModel):
    value: int


def make_client(primary: FakeProvider, backup: FakeProvider | None = None) -> LLMClient:
    cfg = LLMConfig.model_validate(
        {
            "providers": {"a": {"type": "fake"}, "b": {"type": "fake"}},
            "roles": {
                "extract": {"provider": "a", "model": "m1", "fallback": [{"provider": "b", "model": "m2"}]}
            },
            "max_retries": 2,
        }
    )
    client = LLMClient(cfg, {"a": primary, "b": backup or FakeProvider("b")})
    client.backoff_seconds = 0
    return client


def run(coro):
    return asyncio.run(coro)


def test_structured_output_is_validated():
    client = make_client(FakeProvider("a", ['```json\n{"value": 7}\n```']))
    resp = run(client.generate("extract", [Message.user("hi")], schema=Answer))
    assert resp.parsed == Answer(value=7) and resp.provider == "a" and resp.model == "m1"


def test_invalid_json_gets_one_repair_retry():
    primary = FakeProvider("a", ['{"value": "seven"}', '{"value": 7}'])
    resp = run(make_client(primary).generate("extract", [Message.user("hi")], schema=Answer))
    assert resp.parsed.value == 7
    assert "failed validation" in primary.requests[1].messages[-1].content


def test_invalid_json_twice_raises():
    client = make_client(FakeProvider("a", ["nope", "still nope"]))
    with pytest.raises(LLMError, match="did not match Answer"):
        run(client.generate("extract", [Message.user("hi")], schema=Answer))


def test_rate_limits_are_retried_then_fall_back():
    primary = FakeProvider("a", [RetriableLLMError("429")] * 3)
    backup = FakeProvider("b", ['{"value": 1}'])
    resp = run(make_client(primary, backup).generate("extract", [Message.user("hi")], schema=Answer))
    assert len(primary.requests) == 3 and resp.provider == "b" and resp.model == "m2"


def test_unknown_role_and_provider_are_rejected(tmp_path):
    with pytest.raises(LLMError):
        run(make_client(FakeProvider("a")).generate("nope", [Message.user("hi")]))
    bad = tmp_path / "llm.yaml"
    bad.write_text("providers: {}\nroles: {extract: {provider: x, model: m}}\n")
    with pytest.raises(ValueError, match="unknown provider"):
        LLMConfig.load(bad)


def test_repo_llm_config_loads():
    from app.settings import API_ROOT

    cfg = LLMConfig.load(API_ROOT / "config" / "llm.yaml")
    assert {"extract", "write", "verify", "agent"} <= set(cfg.roles)
