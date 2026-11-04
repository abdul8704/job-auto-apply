"""Gemini adapter (google-genai SDK). Maps neutral messages, tools and JSON schemas to Gemini's API."""

from google import genai
from google.genai import errors, types

from app.llm.base import (
    FilePart,
    LLMError,
    LLMRequest,
    LLMResponse,
    Message,
    RetriableLLMError,
    ToolCall,
    Usage,
)


def to_gemini_contents(messages: list[Message]) -> tuple[str | None, list[types.Content]]:
    """Gemini takes the system prompt separately and calls the assistant role "model"."""
    system = "\n\n".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
    contents: list[types.Content] = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=m.tool_name or "tool", response={"result": m.content}
                        )
                    ],
                )
            )
            continue
        parts: list[types.Part] = []
        for p in m.parts():
            if isinstance(p, FilePart):
                parts.append(types.Part.from_bytes(data=p.data, mime_type=p.mime_type))
            elif p:
                parts.append(types.Part.from_text(text=p))
        for tc in m.tool_calls:
            parts.append(types.Part.from_function_call(name=tc.name, args=tc.arguments))
        contents.append(types.Content(role="model" if m.role == "assistant" else "user", parts=parts))
    return (system or None), contents


def build_config(request: LLMRequest, system: str | None) -> types.GenerateContentConfig:
    kwargs: dict = {
        "temperature": request.temperature,
        "max_output_tokens": request.max_tokens,
        "system_instruction": system,
    }
    if request.json_schema and not request.tools:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_json_schema"] = request.json_schema
    if request.tools:
        kwargs["tools"] = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name, description=t.description, parameters_json_schema=t.parameters
                    )
                    for t in request.tools
                ]
            )
        ]
        kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
    return types.GenerateContentConfig(**kwargs)


class GeminiProvider:
    def __init__(self, api_key: str, name: str = "gemini", client: genai.Client | None = None):
        if client is None and not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.name = name
        self.client = client or genai.Client(api_key=api_key)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        system, contents = to_gemini_contents(request.messages)
        try:
            resp = await self.client.aio.models.generate_content(
                model=request.model, contents=contents, config=build_config(request, system)
            )
        except errors.APIError as exc:
            if exc.code in (408, 429) or (exc.code or 0) >= 500:
                raise RetriableLLMError(f"gemini {exc.code}: {exc.message}") from exc
            raise LLMError(f"gemini {exc.code}: {exc.message}") from exc

        calls = [
            ToolCall(id=fc.id, name=fc.name or "", arguments=dict(fc.args or {}))
            for fc in (resp.function_calls or [])
        ]
        um = resp.usage_metadata
        usage = Usage(
            input_tokens=(um.prompt_token_count or 0) if um else 0,
            output_tokens=(um.candidates_token_count or 0) if um else 0,
        )
        text = None if calls else resp.text
        return LLMResponse(text=text, tool_calls=calls, usage=usage, provider=self.name, model=request.model)
