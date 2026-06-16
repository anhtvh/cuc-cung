"""Parity cấp engine: tool experimental-gated (workspace Upia) ẩn/lộ đúng qua seam capability.

Khoá hành vi gốc: chưa expose → ẩn (giữ flow mock); expose → lộ. Đường gating nay đi qua
CapabilityResolver.gated_tools thay vì set tên cứng trong engine.
"""

from app.core.capabilities import CapabilityResolver
from app.core.chat_engine import ChatEngine
from app.core.models import Agent, ItemStatus
from app.tools.catalog import SystemProvider, ToolCatalog
from app.tools.partner_integration import PartnerIntegrationProvider

_WS = {
    "partner-integration__save_file",
    "partner-integration__list_workspace",
    "partner-integration__package_project",
}


def _engine():
    cat = ToolCatalog([SystemProvider(), PartnerIntegrationProvider()])
    return ChatEngine(agents=None, skills=None, usage=None, memory=None, llm=None, catalog=cat)


def _upia():
    return Agent(name="Upia", description="d", system_prompt="p",
                 connectors=["partner-integration"], domain="x", status=ItemStatus.public)


def test_workspace_tools_hidden_when_not_exposed():
    eng = _engine()
    gated = CapabilityResolver(experimental_enabled=False).gated_tools("Upia")
    tools, _ = eng._assemble_tools(_upia(), "hi", has_kb=False,
                                   gated_tools=gated, expose_workspace_tools=False)
    names = {t.name for t in tools}
    assert not (_WS & names), "workspace tool phải bị ẩn khi chưa expose"


def test_workspace_tools_present_when_exposed():
    eng = _engine()
    gated = CapabilityResolver(experimental_enabled=True).gated_tools("Upia")
    tools, _ = eng._assemble_tools(_upia(), "hi", has_kb=False,
                                   gated_tools=gated, expose_workspace_tools=True)
    names = {t.name for t in tools}
    assert _WS <= names, "workspace tool phải lộ khi expose"


def test_workspace_tools_marked_stateful_in_assembled_set():
    # Sau khi lộ, các tool này phải mang cờ stateful → engine inject _conversation_id.
    eng = _engine()
    gated = CapabilityResolver(experimental_enabled=True).gated_tools("Upia")
    tools, _ = eng._assemble_tools(_upia(), "hi", has_kb=False,
                                   gated_tools=gated, expose_workspace_tools=True)
    stateful = {t.name for t in tools if t.stateful}
    assert _WS <= stateful
