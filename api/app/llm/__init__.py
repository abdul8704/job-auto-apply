"""Provider-agnostic LLM layer. Application code imports only from here:

    from app.llm import Message, get_llm
    resp = await get_llm().generate("extract", [Message.user("...")], schema=MyModel)

Roles ("extract", "write", "verify", "agent") map to a provider + model in config/llm.yaml,
so switching Gemini -> Claude / OpenAI / a local model is a config change.
"""

from app.llm.base import (
    FilePart,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
    RetriableLLMError,
    Tool,
    ToolCall,
    Usage,
)
from app.llm.client import LLMClient, get_llm

__all__ = [
    "FilePart",
    "LLMClient",
    "LLMError",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "Message",
    "RetriableLLMError",
    "Tool",
    "ToolCall",
    "Usage",
    "get_llm",
]
