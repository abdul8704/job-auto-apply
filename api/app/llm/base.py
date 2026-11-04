"""Neutral types shared by every provider adapter."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class FilePart(BaseModel):
    """A file passed to the model, e.g. a resume PDF."""

    data: bytes
    mime_type: str


class ToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[str | FilePart] = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)  # assistant messages that called tools
    tool_name: str | None = None  # for role="tool": which tool this result belongs to
    tool_call_id: str | None = None

    @classmethod
    def system(cls, text: str) -> "Message":
        return cls(role="system", content=text)

    @classmethod
    def user(cls, *parts: str | FilePart) -> "Message":
        return cls(
            role="user", content=parts[0] if len(parts) == 1 and isinstance(parts[0], str) else list(parts)
        )

    @classmethod
    def assistant(cls, text: str) -> "Message":
        return cls(role="assistant", content=text)

    def parts(self) -> list[str | FilePart]:
        return [self.content] if isinstance(self.content, str) else list(self.content)


class Tool(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMRequest(BaseModel):
    """What the client hands to a provider. `json_schema` is set when structured output is wanted."""

    model: str
    messages: list[Message]
    json_schema: dict[str, Any] | None = None
    tools: list[Tool] | None = None
    temperature: float = 0.2
    max_tokens: int = 4096


class LLMResponse(BaseModel):
    text: str | None = None
    parsed: Any = None  # a validated pydantic object when a schema was requested
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    provider: str = ""
    model: str = ""


class LLMError(Exception):
    """A failure that retrying will not fix (bad request, auth, invalid output after retries)."""


class RetriableLLMError(LLMError):
    """Rate limits, timeouts and 5xx errors: worth retrying or falling back to another provider."""


class LLMProvider(Protocol):
    name: str

    async def generate(self, request: LLMRequest) -> LLMResponse: ...
