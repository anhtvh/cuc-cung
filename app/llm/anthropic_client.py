"""Plan A — MaaS Anthropic Messages API, native tool-use (design §6, §8).

LƯU Ý đã xác minh 12/06: endpoint Anthropic của MaaS auth bằng
`Authorization: Bearer` → SDK phải dùng `auth_token=`, KHÔNG phải `api_key=`.
"""

import logging
import time
from typing import Any, Iterator

import httpx

from anthropic import Anthropic, APIConnectionError, APIStatusError, APITimeoutError

from app.core.models import ChatMessage
from app.llm.base import (
    Done,
    LLMEvent,
    TextDelta,
    ToolCallEvent,
    ToolStartEvent,
    ToolDef,
    ToolExecutor,
    ToolResult,
    execute_tools_maybe_parallel,
    parse_json_loose,
)

log = logging.getLogger(__name__)

# Sentinel: phân biệt "không truyền sla_seconds" (dùng default client) với "truyền None" (tắt SLA).
_SLA_DEFAULT = object()

# Nudge ép model tổng hợp khi chạm SLA — không cho tra cứu thêm.
_SLA_NUDGE = (
    "[Hệ thống — đã chạm giới hạn thời gian xử lý (SLA ~1 phút)]\n"
    "DỪNG tra cứu/tìm kiếm thêm. Hãy trả lời NGAY dựa trên dữ liệu đã thu thập được. "
    "Nêu rõ ở cuối: phần này được phân tích trên dữ liệu hiện có, có thể chưa đầy đủ."
)

# Câu trả lời an toàn khi 1 request tới MaaS bị timeout giữa chừng.
_TIMEOUT_FALLBACK = (
    "_(Xin lỗi, việc xử lý mất nhiều thời gian hơn dự kiến. Mình trả lời dựa trên "
    "dữ liệu đã có; bạn có thể hỏi lại để mình bổ sung phần còn thiếu nhé.)_"
)

# P2-2: SLA 2 tầng. Tool mạng CHẬM (web-search/fetch) là thủ phạm latency chính → khi chạm
# SLA (soft) gỡ trước, NHƯNG giữ tool nhanh (knowledge_search/system/escalate) để model vẫn
# tổng hợp/bám dữ liệu nội bộ thay vì bị buộc trả lời tay không (dễ bịa). Quá 1.5× SLA (hard)
# mới cắt sạch tool + ép dừng — chốt chặn cứng chống treo.
_SLA_HARD_FACTOR = 1.5
_SLOW_TOOL_PREFIXES = ("web-search",)  # khớp wire-name "web-search__search" / "web-search__fetch"


def _is_slow_tool(name: str) -> bool:
    return any(name.startswith(p) for p in _SLOW_TOOL_PREFIXES)


def _round_tools_for_elapsed(api_tools, effective_sla, elapsed):
    """Chọn bộ tool cho 1 vòng theo SLA (P2-2). Trả (round_tools, hard_deadline).

    - chưa quá SLA → đủ tool.
    - quá SLA (soft) → gỡ tool mạng chậm, giữ tool nhanh (None nếu không còn tool nhanh nào).
    - quá _SLA_HARD_FACTOR × SLA (hard) → None (cắt sạch); hard_deadline=True → caller break.
    """
    if effective_sla is None:
        return api_tools, False
    if elapsed > effective_sla * _SLA_HARD_FACTOR:
        return None, True
    if elapsed > effective_sla:
        fast = [t for t in api_tools if not _is_slow_tool(t["name"])]
        return (fast or None), False
    return api_tools, False


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
        sla_seconds: float | None = _SLA_DEFAULT,
        stream: bool = True,
        parallel_tools: bool = True,
    ) -> Iterator[LLMEvent]:
        """Vòng lặp tool-use (Flow 2/3): stream → tool_use → thực thi → tool_result → lặp.

        sla_seconds: override SLA cho lượt này. Mặc định (_SLA_DEFAULT) dùng SLA của client;
        master builder cần ngưỡng dài hơn để kịp gọi create_* (xem chat_engine).

        stream=False: dùng messages.create() (non-streaming). BẮT BUỘC cho master builder —
        bug MaaS/minimax: tool_use input LỚN (vd content skill markdown ~15k ký tự) bị MẤT khi
        streaming (block.input rỗng → KeyError 'name'); non-streaming trả input đầy đủ. Args nhỏ
        (websearch query, url) stream bình thường nên Flow 3 vẫn dùng stream=True.

        parallel_tools=True (Flow 3): ≥2 tool_use/vòng chạy song song (I-04). Đặt False cho
        master builder vì các tool ghi registry có thứ tự phụ thuộc (create_skill → attach_skill).
        """
        # Override SLA per-call: sentinel = giữ default client; None = tắt cắt-tool; số = ngưỡng riêng.
        effective_sla = self._sla_seconds if sla_seconds is _SLA_DEFAULT else sla_seconds
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
            # P2-2: SLA 2 tầng — soft gỡ tool chậm (giữ tool nhanh để vẫn tổng hợp), hard cắt sạch.
            elapsed = time.monotonic() - start
            round_tools, hard_sla = _round_tools_for_elapsed(api_tools, effective_sla, elapsed)

            stream_kwargs: dict[str, Any] = {
                "model": model or self._default_model,
                "max_tokens": self._max_tokens,
                "system": system,
                "messages": convo,
            }
            if round_tools is not None:
                stream_kwargs["tools"] = round_tools

            try:
                if stream:
                    with self._client.messages.stream(**stream_kwargs) as s:
                        for text in s.text_stream:
                            yield TextDelta(text)
                        final = s.get_final_message()
                else:
                    # Non-stream: lấy nguyên message rồi yield text các block (an toàn args lớn).
                    final = self._client.messages.create(**stream_kwargs)
                    for block in final.content:
                        if block.type == "text":
                            yield TextDelta(block.text)
            except (APITimeoutError, httpx.TimeoutException):
                # Request treo quá timeout → không để chết im lặng: trả lời an toàn rồi dừng.
                # httpx.TimeoutException: streaming reasoning model (minimax) "thinking" im lặng
                # vượt read-timeout → SDK KHÔNG bọc thành APITimeoutError mà raise raw httpx.ReadTimeout
                # giữa vòng lặp text_stream → phải bắt ở đây, nếu không sẽ crash cả stream.
                log.warning("MaaS request timeout sau %.1fs — trả lời fallback", time.monotonic() - start)
                yield TextDelta(_TIMEOUT_FALLBACK)
                yield Done(input_tokens=total_in, output_tokens=total_out, stop_reason="timeout")
                return
            except APIStatusError as e:
                # 429 rate-limit, 500/502/503 server error từ MaaS → fallback thay vì bubble up.
                log.warning("MaaS API status %d (round %d): %s", e.status_code, _round, e.message[:200])
                msg = (
                    "_(Dịch vụ AI đang bận, mình trả lời dựa trên dữ liệu đã có. "
                    "Bạn thử lại sau giây lát nếu cần thêm thông tin nhé.)_"
                    if e.status_code in (429, 503)
                    else _TIMEOUT_FALLBACK
                )
                yield TextDelta(msg)
                yield Done(input_tokens=total_in, output_tokens=total_out, stop_reason=f"api_error_{e.status_code}")
                return
            except APIConnectionError as e:
                # Mạng đứt / DNS fail / TLS error → fallback an toàn.
                log.warning("MaaS connection error (round %d): %s", _round, e)
                yield TextDelta(_TIMEOUT_FALLBACK)
                yield Done(input_tokens=total_in, output_tokens=total_out, stop_reason="connection_error")
                return

            total_in += final.usage.input_tokens
            total_out += final.usage.output_tokens
            stop_reason = final.stop_reason
            log.info("LLM round %d stop_reason=%s content_types=%s", _round, stop_reason,
                     [b.type for b in final.content])

            # Hard deadline (quá 1.5× SLA): vòng này đã chạy không-tool → ép dừng ngay.
            # Soft deadline KHÔNG break: model còn tool nhanh để hội tụ, vòng sau vẫn bị SLA chặn
            # (và đã nhận nudge tổng hợp) — tránh cắt grounding quá sớm khiến bịa.
            if hard_sla:
                stop_reason = "sla_deadline"
                break

            if final.stop_reason != "tool_use":
                # max_tokens = model bị cắt giữa chừng (thường do thinking ngốn budget) →
                # phản hồi cụt, chưa kịp gọi tool. Log để không dừng im lặng như trước.
                if final.stop_reason == "max_tokens":
                    log.warning("round %d bị cắt do max_tokens (=%d) — cân nhắc tăng max_tokens",
                                _round, self._max_tokens)
                break

            # Serialize content + tách tool_use blocks (giữ thứ tự gốc để event deterministic).
            assistant_content: list[dict[str, Any]] = []
            tool_use_blocks: list[Any] = []
            for block in final.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append(
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    )
                    tool_use_blocks.append(block)

            # Báo UI tất cả tool sắp chạy TRƯỚC (websearch/fetch chậm) — khi chạy song song
            # UI thấy cả 2 cùng "đang chạy".
            for block in tool_use_blocks:
                yield ToolStartEvent(name=block.name, input=block.input or {})

            # I-04: ≥2 tool_use/vòng → chạy song song (parallel_tools). Giữ thứ tự input.
            results = execute_tools_maybe_parallel(
                execute,
                [(b.name, b.input or {}) for b in tool_use_blocks],
                parallel_tools,
            )

            tool_results: list[dict[str, Any]] = []
            for block, result in zip(tool_use_blocks, results):
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
            if effective_sla is not None and (time.monotonic() - start) > effective_sla:
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
