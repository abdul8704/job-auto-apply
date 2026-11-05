import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.llm import FilePart, LLMError, LLMRequest, Message, RetriableLLMError, Tool, ToolCall
from app.llm.providers.gemini import GeminiProvider, build_config, to_gemini_contents


def test_messages_map_to_gemini_contents():
    system, contents = to_gemini_contents(
        [
            Message.system("be exact"),
            Message.user("read this", FilePart(data=b"%PDF", mime_type="application/pdf")),
            Message(role="assistant", content="", tool_calls=[ToolCall(name="fill", arguments={"x": 1})]),
            Message(role="tool", content="done", tool_name="fill"),
        ]
    )
    assert system == "be exact"
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[0].parts[0].text == "read this"
    assert contents[0].parts[1].inline_data.mime_type == "application/pdf"
    assert contents[1].parts[0].function_call.name == "fill"
    assert contents[2].parts[0].function_response.name == "fill"


def test_config_uses_json_schema_or_tools():
    req = LLMRequest(model="m", messages=[], json_schema={"type": "object"})
    cfg = build_config(req, "sys")
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == {"type": "object"}
    req = LLMRequest(
        model="m", messages=[], tools=[Tool(name="t", description="d", parameters={"type": "object"})]
    )
    cfg = build_config(req, None)
    assert cfg.tools[0].function_declarations[0].name == "t" and cfg.response_mime_type is None


class _Models:
    def __init__(self, result):
        self.result = result

    async def generate_content(self, **kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _provider(result) -> GeminiProvider:
    fake_client = SimpleNamespace(aio=SimpleNamespace(models=_Models(result)))
    return GeminiProvider(api_key="", client=fake_client)


def test_response_and_errors_are_mapped():
    ok = SimpleNamespace(
        text="hello",
        function_calls=None,
        usage_metadata=SimpleNamespace(prompt_token_count=5, candidates_token_count=2),
    )
    resp = asyncio.run(_provider(ok).generate(LLMRequest(model="m", messages=[Message.user("hi")])))
    assert resp.text == "hello" and resp.usage.input_tokens == 5 and resp.provider == "gemini"

    req = LLMRequest(model="m", messages=[Message.user("hi")])
    with pytest.raises(RetriableLLMError):
        asyncio.run(_provider(errors.APIError(429, {"error": {"message": "slow down"}})).generate(req))
    with pytest.raises(LLMError):
        asyncio.run(_provider(errors.APIError(400, {"error": {"message": "bad"}})).generate(req))


def test_missing_key_is_a_clear_error():
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiProvider(api_key="")
