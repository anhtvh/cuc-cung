"""Test ToolCatalog — timeout, wire name, shared executor."""

import time

import pytest

from app.llm.base import ToolDef, ToolResult
from app.tools.base import ToolProvider
from app.tools.catalog import ToolCatalog


class SlowProvider:
    server_name = "slow"
    is_mock = True

    def list_tools(self):
        return [ToolDef(name="wait", description="waits")]

    def call(self, tool_name: str, args: dict) -> str:
        time.sleep(5)
        return "done"


class EchoProvider:
    server_name = "echo"
    is_mock = True

    def list_tools(self):
        return [ToolDef(name="say", description="echo")]

    def call(self, tool_name: str, args: dict) -> str:
        return f"echo:{args.get('msg', '')}"


class ErrorProvider:
    server_name = "err"
    is_mock = True

    def list_tools(self):
        return [ToolDef(name="boom", description="always fails")]

    def call(self, tool_name: str, args: dict) -> str:
        raise RuntimeError("intentional error")


@pytest.fixture
def catalog():
    return ToolCatalog(
        providers=[EchoProvider(), SlowProvider(), ErrorProvider()],
        tool_timeout_seconds=1,
    )


class TestToolCatalogExecute:
    def test_successful_call(self, catalog):
        result = catalog.execute("echo__say", {"msg": "hello"})
        assert not result.is_error
        assert result.content == "echo:hello"

    def test_timeout_returns_error(self, catalog):
        result = catalog.execute("slow__wait", {})
        assert result.is_error
        assert "timeout" in result.content.lower()

    def test_provider_exception_returns_error(self, catalog):
        result = catalog.execute("err__boom", {})
        assert result.is_error
        assert "intentional error" in result.content

    def test_unknown_server_returns_error(self, catalog):
        result = catalog.execute("nonexistent__tool", {})
        assert result.is_error

    def test_malformed_wire_name_returns_error(self, catalog):
        result = catalog.execute("notawirename", {})
        assert result.is_error

    def test_tools_for_returns_wire_names(self, catalog):
        tools = catalog.tools_for(["echo"])
        assert len(tools) == 1
        assert tools[0].name == "echo__say"

    def test_shared_executor_reused(self, catalog):
        # L-05: executor phải là cùng 1 instance, không tạo lại
        ex1 = catalog._executor
        catalog.execute("echo__say", {})
        catalog.execute("echo__say", {})
        assert catalog._executor is ex1


class TestParsejsonLoose:
    def test_parse_plain_json(self):
        from app.llm.base import parse_json_loose
        assert parse_json_loose('{"a": 1}') == {"a": 1}

    def test_parse_with_leading_text(self):
        from app.llm.base import parse_json_loose
        result = parse_json_loose('Here is the result: {"agent_name": "Bé Pháp", "confidence": "high"}')
        assert result["agent_name"] == "Bé Pháp"

    def test_parse_with_trailing_text(self):
        from app.llm.base import parse_json_loose
        result = parse_json_loose('{"agent_name": null} Let me explain why...')
        assert result["agent_name"] is None

    def test_parse_code_fence(self):
        from app.llm.base import parse_json_loose
        text = '```json\n{"overlapping": ["legal-agent"]}\n```'
        assert parse_json_loose(text) == {"overlapping": ["legal-agent"]}
