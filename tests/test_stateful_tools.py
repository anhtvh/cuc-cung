"""Contract test cho cờ ToolDef.stateful (seam plug-and-play A1).

Engine inject `_conversation_id` cho tool stateful dựa CỜ do provider khai báo — không
còn set tên cứng. Test khoá hành vi: (1) default False; (2) provider khai đúng tool ghi
trạng thái; (3) catalog giữ cờ khi đổi sang tên wire.
"""

from app.llm.base import ToolDef
from app.tools.catalog import ToolCatalog
from app.tools.file_export import FileExportProvider
from app.tools.partner_integration import PartnerIntegrationProvider


def test_tooldef_stateful_default_false():
    assert ToolDef(name="x", description="y").stateful is False


def test_partner_integration_marks_workspace_tools_stateful():
    by_name = {t.name: t for t in PartnerIntegrationProvider().list_tools()}
    # Workspace (ghi/đọc/đóng gói theo conversation) → stateful.
    for n in ("save_file", "list_workspace", "package_project"):
        assert by_name[n].stateful is True, n
    # Tool mô phỏng đọc-thuần KHÔNG stateful (vd read_phase).
    assert by_name["read_phase"].stateful is False


def test_file_export_marks_export_tools_stateful():
    for t in FileExportProvider().list_tools():
        assert t.stateful is True, t.name


def test_catalog_preserves_stateful_on_wire_rename():
    cat = ToolCatalog([PartnerIntegrationProvider()])
    by_wire = {t.name: t for t in cat.tools_for(["partner-integration"])}
    assert by_wire["partner-integration__save_file"].stateful is True
    assert by_wire["partner-integration__read_phase"].stateful is False
