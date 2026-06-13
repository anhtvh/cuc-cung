"""Unit tests cho McpGatewayProvider — không gọi cloud thật."""

from unittest.mock import MagicMock, patch

import pytest

from app.llm.base import ToolDef
from app.tools.mcp_gateway import IamTokenProvider, McpGatewayProvider


def make_provider(target: str | None = "websearch") -> McpGatewayProvider:
    token_provider = MagicMock(spec=IamTokenProvider)
    token_provider.get_token.return_value = "fake-token"
    return McpGatewayProvider(
        server_name="web-search-live",
        gateway_endpoint="https://gw-test.example.com",
        token_provider=token_provider,
        target_name=target,
        call_timeout=5,
    )


class TestRpcUrl:
    def test_with_target(self):
        p = make_provider(target="websearch")
        assert p._rpc_url() == "https://gw-test.example.com/websearch"

    def test_without_target(self):
        p = make_provider(target=None)
        assert p._rpc_url() == "https://gw-test.example.com"

    def test_trailing_slash_stripped(self):
        token_provider = MagicMock(spec=IamTokenProvider)
        token_provider.get_token.return_value = "fake-token"
        p = McpGatewayProvider(
            server_name="ws",
            gateway_endpoint="https://gw-test.example.com/",
            token_provider=token_provider,
            target_name="ws",
        )
        assert p._rpc_url() == "https://gw-test.example.com/ws"


class TestListTools:
    def test_filters_by_target_prefix(self):
        p = make_provider(target="websearch")
        mock_result = {
            "tools": [
                {"name": "websearch__search", "description": "Tìm kiếm", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "websearch__fetch", "description": "Fetch trang", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "other__tool", "description": "Tool khác"},
            ]
        }
        with patch.object(p, "_rpc", return_value=mock_result):
            tools = p.list_tools()
        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "search" in names
        assert "fetch" in names
        assert "tool" not in names

    def test_no_target_returns_all(self):
        p = make_provider(target=None)
        mock_result = {
            "tools": [
                {"name": "search", "description": "S", "inputSchema": {}},
                {"name": "fetch", "description": "F", "inputSchema": {}},
            ]
        }
        with patch.object(p, "_rpc", return_value=mock_result):
            tools = p.list_tools()
        assert len(tools) == 2

    def test_cache_hit(self):
        p = make_provider()
        mock_result = {"tools": [{"name": "websearch__search", "description": "S", "inputSchema": {}}]}
        with patch.object(p, "_rpc", return_value=mock_result) as mock_rpc:
            p.list_tools()
            p.list_tools()  # cache hit
        assert mock_rpc.call_count == 1  # chỉ gọi 1 lần

    def test_error_returns_cache(self):
        p = make_provider()
        # Lần đầu OK
        mock_result = {"tools": [{"name": "websearch__search", "description": "S", "inputSchema": {}}]}
        with patch.object(p, "_rpc", return_value=mock_result):
            p.list_tools()
        # Force expire cache
        p._tools_cache_at = 0
        # Lần hai lỗi → trả cache cũ
        with patch.object(p, "_rpc", side_effect=Exception("network error")):
            tools = p.list_tools()
        assert len(tools) == 1  # vẫn có tool từ cache


class TestCallTool:
    def test_adds_target_prefix(self):
        p = make_provider(target="websearch")
        mock_result = {"content": [{"type": "text", "text": "kết quả"}], "isError": False}
        with patch.object(p, "_rpc", return_value=mock_result) as mock_rpc:
            result = p.call("search", {"query": "test"})
        # Kiểm tra tool name được gắn prefix
        mock_rpc.assert_called_once_with("tools/call", {"name": "websearch__search", "arguments": {"query": "test"}})
        assert result == "kết quả"

    def test_no_target_no_prefix(self):
        p = make_provider(target=None)
        mock_result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        with patch.object(p, "_rpc", return_value=mock_result) as mock_rpc:
            p.call("search", {})
        mock_rpc.assert_called_once_with("tools/call", {"name": "search", "arguments": {}})

    def test_is_error_raises(self):
        p = make_provider()
        mock_result = {"content": [{"type": "text", "text": "boom"}], "isError": True}
        with patch.object(p, "_rpc", return_value=mock_result):
            with pytest.raises(RuntimeError):
                p.call("search", {})

    def test_multi_content_joined(self):
        p = make_provider()
        mock_result = {
            "content": [
                {"type": "text", "text": "phần 1"},
                {"type": "text", "text": "phần 2"},
            ],
            "isError": False,
        }
        with patch.object(p, "_rpc", return_value=mock_result):
            result = p.call("fetch", {"url": "http://example.com"})
        assert result == "phần 1\nphần 2"
