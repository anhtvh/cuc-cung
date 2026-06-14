"""Plan B / provider khác — OpenAI-compatible endpoint của MaaS (`/v1`).

Cùng LLMClient protocol với anthropic_client → swap bằng env LLM_PROVIDER,
flow phía trên không đổi (design §6).
"""

import json
import logging
from typing import Any, Iterator

from openai import BadRequestError, OpenAI

from app.core.models import ChatMessage
from app.llm.base import (
    Done,
    LLMEvent,
    TextDelta,
    ToolCallEvent,
    ToolDef,
    ToolExecutor,
    parse_json_loose,
)

log = logging.getLogger(__name__)


class OpenAIMaaSClient:
    def __init__(self, base_url: str, api_key: str, default_model: str, max_tokens: int = 4096,
                 request_timeout: float | None = None):
        # timeout: router classify treo sẽ raise sau ngưỡng này → router fallback master (Flow 1).
        self._client = OpenAI(base_url=f"{base_url.rstrip('/')}/v1", api_key=api_key, timeout=request_timeout)
        self._default_model = default_model
        self._max_tokens = max_tokens

    def chat(
        self,
        system: str,
        messages: list[ChatMessage],
        model: str | None = None,
    ) -> Iterator[LLMEvent]:
        stream = self._client.chat.completions.create(
            model=model or self._default_model,
            max_tokens=self._max_tokens,
            messages=[{"role": "system", "content": system}, *(m.model_dump() for m in messages)],
            stream=True,
            stream_options={"include_usage": True},
        )
        usage_in, usage_out = 0, 0
        finish = None
        for chunk in stream:
            if chunk.usage:
                usage_in, usage_out = chunk.usage.prompt_tokens, chunk.usage.completion_tokens
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield TextDelta(delta.content)
                if chunk.choices[0].finish_reason:
                    finish = chunk.choices[0].finish_reason
        yield Done(input_tokens=usage_in, output_tokens=usage_out, stop_reason=finish)

    def chat_with_tools(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDef],
        execute: ToolExecutor,
        max_rounds: int = 5,
        model: str | None = None,
    ) -> Iterator[LLMEvent]:
        api_tools = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
            }
            for t in tools
        ]
        convo: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *(m.model_dump() for m in messages),
        ]
        total_in, total_out = 0, 0
        finish = None

        for _round in range(max_rounds):
            # B-06: dùng stream=True để text delta hiện dần, không bị blank → đột ngột
            stream = self._client.chat.completions.create(
                model=model or self._default_model,
                max_tokens=self._max_tokens,
                messages=convo,
                tools=api_tools,
                stream=True,
                stream_options={"include_usage": True},
            )
            content_parts: list[str] = []
            tc_acc: dict[int, dict[str, str]] = {}  # index → {id, name, arguments}
            round_in = round_out = 0
            finish = None

            for chunk in stream:
                if chunk.usage:
                    round_in = chunk.usage.prompt_tokens or 0
                    round_out = chunk.usage.completion_tokens or 0
                if not chunk.choices:
                    continue
                ch = chunk.choices[0]
                if ch.finish_reason:
                    finish = ch.finish_reason
                delta = ch.delta
                if delta.content:
                    content_parts.append(delta.content)
                    yield TextDelta(delta.content)
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tc_acc:
                            tc_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tc_acc[idx]["id"] += tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tc_acc[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tc_acc[idx]["arguments"] += tc_delta.function.arguments

            total_in += round_in
            total_out += round_out
            log.info("OAI round %d finish=%s tc_count=%d", _round, finish, len(tc_acc))

            if not tc_acc:
                break

            content = "".join(content_parts)
            tool_calls_list = [
                {
                    "id": tc_acc[idx]["id"],
                    "type": "function",
                    "function": {"name": tc_acc[idx]["name"], "arguments": tc_acc[idx]["arguments"]},
                }
                for idx in sorted(tc_acc)
            ]
            # Một số OpenAI-compat endpoint reject "content": null khi có tool_calls
            # → omit key khi không có text, không set null
            assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls_list}
            if content:
                assistant_msg["content"] = content
            convo.append(assistant_msg)
            for tc_dict in tool_calls_list:
                try:
                    args = json.loads(tc_dict["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute(tc_dict["function"]["name"], args)
                yield ToolCallEvent(name=tc_dict["function"]["name"], input=args, result=result)
                tool_content = result.content if not result.is_error else f"LỖI: {result.content}"
                convo.append({"role": "tool", "tool_call_id": tc_dict["id"], "content": tool_content})
        else:
            log.warning("tool loop chạm trần %d vòng — dừng lượt", max_rounds)
            finish = "max_tool_rounds"

        yield Done(input_tokens=total_in, output_tokens=total_out, stop_reason=finish)

    def classify_json(
        self,
        system: str,
        message: str,
        schema_hint: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        sys_prompt = f"{system}\n\nChỉ trả về MỘT object JSON đúng schema sau:\n{schema_hint}"
        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "max_tokens": 512,
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": message}],
            # Tắt thinking mode (qwen3, deepseek-r1...) — classify chỉ cần JSON ngắn,
            # thinking chiếm hết token budget mà không sinh content.
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        try:
            resp = self._client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        except BadRequestError:
            # Chỉ retry khi model KHÔNG hỗ trợ response_format (HTTP 400) → bỏ tham số.
            # Lỗi khác (timeout/auth/network) để propagate — caller (router) tự fallback,
            # tránh tốn thêm 1 call full vô ích.
            resp = self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content
        # Một số model trả content=None khi thinking vẫn bật hoặc hết token — fallback an toàn.
        return parse_json_loose(content or "{}") if content else {}
