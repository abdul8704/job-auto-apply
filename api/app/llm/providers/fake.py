"""A scripted provider for tests and offline development (set a role's provider to `fake`)."""

from collections.abc import Callable

from app.llm.base import LLMRequest, LLMResponse, Usage

Responder = Callable[[LLMRequest], LLMResponse | str | Exception]


class FakeProvider:
    def __init__(self, name: str = "fake", responses: list[LLMResponse | str | Exception] | None = None):
        self.name = name
        self.responses = list(responses or [])
        self.responder: Responder | None = None
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.responder is not None:
            out = self.responder(request)
        elif self.responses:
            out = self.responses.pop(0)
        else:
            out = "{}" if request.json_schema else "ok"
        if isinstance(out, Exception):
            raise out
        if isinstance(out, str):
            out = LLMResponse(text=out, usage=Usage(input_tokens=1, output_tokens=1))
        return out.model_copy(update={"provider": self.name, "model": request.model})
