"""LLMClient protocol (design §6 — wrapper chống rủi ro model).

Plan A: native tool-use (anthropic_client). Plan B: prompt-based JSON
(openai_client hoặc client khác) — flow phía trên không đổi một dòng.

chat / chat_with_tools trả Iterator[LLMEvent] để chat engine stream SSE
và xử lý tool-use cùng một vòng lặp (Flow 2 + Flow 3).
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol

from app.core.models import ChatMessage


@dataclass
class ToolDef:
    """Định nghĩa tool theo schema Anthropic (input_schema = JSON Schema)."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    delegate_to: str | None = None       # agent name để auto-handoff
    delegate_message: str | None = None  # message gốc chuyển sang agent
    display_output: str | None = None    # output hiển thị UI (orchestration sub-agent card)


# executor nhận (tool_name, args) → ToolResult; lỗi tool trả is_error=True
# để model tự xử lý (Flow 3 bước 5).
ToolExecutor = Callable[[str, dict[str, Any]], ToolResult]


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallEvent:
    name: str
    input: dict[str, Any]
    result: ToolResult


@dataclass
class Done:
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


LLMEvent = TextDelta | ToolCallEvent | Done


class LLMClient(Protocol):
    def chat(
        self,
        system: str,
        messages: list[ChatMessage],
        model: str | None = None,
    ) -> Iterator[LLMEvent]: ...

    def chat_with_tools(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDef],
        execute: ToolExecutor,
        max_rounds: int = 5,
        model: str | None = None,
    ) -> Iterator[LLMEvent]: ...

    def classify_json(
        self,
        system: str,
        message: str,
        schema_hint: str,
        model: str | None = None,
    ) -> dict[str, Any]: ...


def parse_json_loose(text: str) -> dict[str, Any]:
    """Parse JSON từ output model — chịu được code fence / text thừa quanh JSON."""
    import json
    import re

    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # I-03: tìm block {...} ngoài cùng — dùng vị trí { đầu và } cuối thay vì
        # greedy regex (greedy DOTALL match sai khi model thêm text sau JSON).
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise
