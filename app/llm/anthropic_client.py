"""Plan A — MaaS Anthropic Messages API, native tool-use (design §6, §8).

LƯU Ý đã xác minh 12/06: endpoint Anthropic của MaaS auth bằng
`Authorization: Bearer` → SDK phải dùng `auth_token=`, KHÔNG phải `api_key=`.
"""

import logging
import time
from typing import Any, Iterator

from anthropic import Anthropic, APITimeoutError

from app.core.models import ChatMessage
from app.llm.base import (
    Done,
    LLMEvent,
    TextDelta,
    ToolCallEvent,
    ToolDef,
    ToolExecutor,
    ToolResult,
    parse_json_loose,
)

log = logging.getLogger(__name__)

# Nudge ép model tổng hợp khi chạm SLA — không cho tra cứu thêm.
_SLA_NUDGE = (
    "[Hệ thống — đã chạm giới hạn thời gian xử lý (SLA ~1 phút)]\n"
    "DỪNG tra cứu/tìm kiếm thêm. Hãy trả lời NGAY dựa trên dữ liệu đã thu thập được. "
    "Nêu rõ ở cuối: phần này được phân tích trên dữ liệu hiện có, có thể chưa đầy đủ."
)

# Câu trả lời an toàn khi 1 request tới MaaS bị timeout giữa chừng.
_TIMEOUT_FALLBACK = (
    "\n\n_(Xin lỗi, việc xử lý mất nhiều thời gian hơn dự kiến. Mình trả lời dựa trên "
    "dữ liệu đã có; bạn có thể hỏi lại để mình bổ sung phần còn thiếu nhé.)_"
)


class AnthropicMaaSClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str,
        max_tokens: int = 4096,
        request_timeout: float | None = None,
        sla_seconds: float | None = None,
    ):
        # auth_token → header "Authorization: Bearer <key>" (xem docstring).
        # timeout: chặn 1 request HTTP treo vô hạn (an toàn nền cho SLA).
        self._client = Anthropic(base_url=base_url, auth_token=api_key, timeout=request_timeout)
        self._default_model = default_model
        self._max_tokens = max_tokens
        # SLA soft-deadline cho tool loop: vượt ngưỡng → ép trả lời trên data đã có.
        self._sla_seconds = sla_seconds

    @staticmethod
    def _serialize(messages) -> list[dict]:
        return [m.model_dump() if hasattr(m, "model_dump") else m for m in messages]

    def chat(
        self,
        system: str,
        messages: list,
        model: str | None = None,
    ) -> Iterator[LLMEvent]:
        with self._client.messages.stream(
            model=model or self._default_model,
            max_tokens=self._max_tokens,
            system=system,
            messages=self._serialize(messages),
        ) as stream:
            for text in stream.text_stream:
                yield TextDelta(text)
            final = stream.get_final_message()
        yield Done(
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            stop_reason=final.stop_reason,
        )

    def chat_with_tools(
        self,
        system: str,
        messages: list,
        tools: list[ToolDef],
        execute: ToolExecutor,
        max_rounds: int = 5,
        model: str | None = None,
    ) -> Iterator[LLMEvent]:
        """Vòng lặp tool-use (Flow 2/3): stream → tool_use → thực thi → tool_result → lặp."""
        api_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        convo: list[dict[str, Any]] = self._serialize(messages)
        total_in, total_out = 0, 0
        stop_reason: str | None = None
        # SLA: mốc thời gian bắt đầu lượt — dùng để cắt tool loop khi quá hạn.
        start = time.monotonic()

        for _round in range(max_rounds):
            # Quá SLA → vòng này KHÔNG cấp tool nữa, model buộc trả lời trên data đã có.
            over_sla = self._sla_seconds is not None and (time.monotonic() - start) > self._sla_seconds
            round_tools = None if over_sla else api_tools

            stream_kwargs: dict[str, Any] = {
                "model": model or self._default_model,
                "max_tokens": self._max_tokens,
                "system": system,
                "messages": convo,
            }
            if round_tools is not None:
                stream_kwargs["tools"] = round_tools

            try:
                with self._client.messages.stream(**stream_kwargs) as stream:
                    for text in stream.text_stream:
                        yield TextDelta(text)
                    final = stream.get_final_message()
            except APITimeoutError:
                # Request treo quá timeout → không để chết im lặng: trả lời an toàn rồi dừng.
                log.warning("MaaS request timeout sau %.1fs — trả lời fallback", time.monotonic() - start)
                yield TextDelta(_TIMEOUT_FALLBACK)
                yield Done(input_tokens=total_in, output_tokens=total_out, stop_reason="timeout")
                return

            total_in += final.usage.input_tokens
            total_out += final.usage.output_tokens
            stop_reason = final.stop_reason

            # Đã ép trả lời do quá SLA (vòng không tool) → kết thúc với stop_reason riêng.
            if over_sla:
                stop_reason = "sla_deadline"
                break

            if final.stop_reason != "tool_use":
                break

            # Serialize lại content block thủ công — chỉ giữ field API cần.
            assistant_content: list[dict[str, Any]] = []
            tool_results: list[dict[str, Any]] = []
            for block in final.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append(
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    )
                    result = execute(block.name, block.input or {})
                    yield ToolCallEvent(name=block.name, input=block.input or {}, result=result)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                    )
            convo.append({"role": "assistant", "content": assistant_content})
            convo.append({"role": "user", "content": tool_results})

            # Vừa execute tool xong mà đã quá SLA → chèn nudge để vòng kế (no-tool) tổng hợp ngay.
            if self._sla_seconds is not None and (time.monotonic() - start) > self._sla_seconds:
                convo.append({"role": "user", "content": [{"type": "text", "text": _SLA_NUDGE}]})
        else:
            # hết max_rounds mà model vẫn đòi tool → dừng lượt (an toàn Flow 3)
            log.warning("tool loop chạm trần %d vòng — dừng lượt", max_rounds)
            stop_reason = "max_tool_rounds"

        yield Done(input_tokens=total_in, output_tokens=total_out, stop_reason=stop_reason)

    def classify_json(
        self,
        system: str,
        message: str,
        schema_hint: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Messages API không có response_format → prompt 'chỉ trả JSON' + parse, 1 retry (Flow 1)."""
        sys_prompt = f"{system}\n\nChỉ trả về MỘT object JSON đúng schema sau, không thêm chữ nào khác:\n{schema_hint}"
        convo = [{"role": "user", "content": message}]
        last_err: Exception | None = None
        for attempt in range(2):
            resp = self._client.messages.create(
                model=model or self._default_model,
                max_tokens=512,
                system=sys_prompt,
                messages=convo,
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            try:
                return parse_json_loose(text)
            except Exception as e:  # noqa: BLE001 — retry 1 lần rồi mới raise
                last_err = e
                log.warning("classify_json parse fail (lần %d): %s", attempt + 1, text[:200])
                convo = [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "Output trên không phải JSON hợp lệ. Trả lại CHỈ object JSON."},
                ]
        raise ValueError(f"classify_json: model không trả JSON hợp lệ sau 2 lần: {last_err}")
