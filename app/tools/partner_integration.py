"""Server `partner-integration` (Flow 5) — bộ tool cho agent Upia mô phỏng quy trình
tích hợp đối tác thanh toán hoá đơn vào zalopay (4 phase).

`is_mock=True` vì các tool ĐẶC TRƯNG (go build/test, tạo repo/MR) là MÔ PHỎNG —
agent con Agent Hub chạy trên MaaS, không có go toolchain / git / glab thật.
Riêng `read_phase` / `read_reference` là ĐỌC FILE THẬT (tri thức Upia bundle trong
repo) — tái hiện cơ chế lazy-load của Upia gốc: agent chỉ nạp instruction từng phase
khi vào phase đó, giữ system prompt mỏng.

Nếu sau này muốn codegen THẬT: thay nhóm tool mock bằng MCP server out-of-process
(go runner + glab) qua gateway — cùng interface `ToolProvider`, không đổi flow.
"""

import json
import logging
import random
from pathlib import Path
from typing import Any

from app.llm.base import ToolDef

log = logging.getLogger(__name__)

_UPIA_ROOT = Path(__file__).resolve().parent.parent / "agents" / "upia"
_PHASES_DIR = _UPIA_ROOT / "phases"
_CONTEXT_DIR = _UPIA_ROOT / "context"

_PHASE_NAMES = {1: "Analysis", 2: "Scaffold", 3: "Implement", 4: "Test"}
_REFERENCES = {
    "provider-pattern": "zalopay-provider-pattern.md",
    "observability": "observability-protocol.md",
    "qc-format": "qc-test-case-reference.md",
}


def _read_phase_file(phase: int) -> str:
    matches = sorted(_PHASES_DIR.glob(f"{phase:02d}_*.md"))
    if not matches:
        raise ValueError(f"không tìm thấy file phase {phase}")
    return matches[0].read_text(encoding="utf-8")


# --- Dữ liệu giả lập hoá đơn (Phase 5 — Sandbox verify) ------------------------
_HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi", "Đỗ", "Hồ"]
_DEM = ["Văn", "Thị", "Hữu", "Đức", "Minh", "Quang", "Thanh", "Ngọc"]
_TEN = ["An", "Bình", "Cường", "Dũng", "Hà", "Hương", "Khoa", "Lan", "Nam", "Phúc", "Quân", "Trang"]
_DUONG = ["Lê Lợi", "Nguyễn Huệ", "Cách Mạng Tháng 8", "Điện Biên Phủ", "Trần Hưng Đạo", "Hai Bà Trưng"]
_QUAN = ["Quận 1", "Quận 3", "Quận Bình Thạnh", "Quận Phú Nhuận", "Quận Gò Vấp"]
# serviceID → (prefix mã hoá đơn, nhãn dịch vụ)
_SERVICE = {
    "DIEN": ("PD", "Tiền điện"),
    "NUOC": ("PN", "Tiền nước"),
    "NET": ("PI", "Cước Internet"),
    "TToán truyền hình": ("PT", "Truyền hình"),
}


def _random_customer_code(service_id: str) -> str:
    prefix = _SERVICE.get(service_id, ("PD", ""))[0]
    return f"{prefix}{random.randint(10**9, 10**10 - 1)}"


def _random_bill(customer_code: str, service_id: str) -> dict[str, Any]:
    prefix, label = _SERVICE.get(service_id, ("PD", "Tiền điện"))
    if not customer_code:
        customer_code = _random_customer_code(service_id)
    month = random.randint(1, 12)
    amount = random.randrange(50, 900) * 1000  # VND, làm tròn nghìn
    name = f"{random.choice(_HO)} {random.choice(_DEM)} {random.choice(_TEN)}"
    return {
        "provider_status": "00",  # mã success của đối tác (giả lập)
        "final_status": 1,  # ProviderSuccess
        "service": label,
        "bill_id": f"{prefix}{2026}{month:02d}{random.randint(100000, 999999)}",
        "customer_code": customer_code,
        "customer_name": name,  # PII — chỉ hiển thị demo, không log thật
        "address": f"{random.randint(1, 300)} {random.choice(_DUONG)}, {random.choice(_QUAN)}, TP.HCM",
        "period": f"{month:02d}/2026",
        "amount_vnd": amount,
        "due_date": f"2026-{month:02d}-25",
        "status": "Chưa thanh toán",
        "note": "MÔ PHỎNG — hoá đơn sinh ngẫu nhiên trên sandbox, không phải dữ liệu thật",
    }


class PartnerIntegrationProvider:
    server_name = "partner-integration"
    is_mock = True

    def list_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="read_phase",
                description=(
                    "(THẬT) Nạp hướng dẫn chi tiết của 1 phase (1=Analysis, 2=Scaffold, "
                    "3=Implement, 4=Test). Gọi ngay TRƯỚC khi bắt đầu mỗi phase — đừng nạp sẵn."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "phase": {"type": "integer", "enum": [1, 2, 3, 4], "description": "Số phase 1-4."}
                    },
                    "required": ["phase"],
                },
            ),
            ToolDef(
                name="read_reference",
                description=(
                    "(THẬT) Nạp tài liệu tham chiếu zalopay khi cần: 'provider-pattern' "
                    "(hằng số/interface/coding standard — đọc trước Phase 3), 'observability' "
                    "(format confidence score), 'qc-format' (mẫu QC test case — đọc trước Phase 4)."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": list(_REFERENCES),
                            "description": "Tên tài liệu tham chiếu.",
                        }
                    },
                    "required": ["name"],
                },
            ),
            ToolDef(
                name="go_build",
                description="(MÔ PHỎNG) Chạy `go build ./...` trên repo. Trả lỗi build, rỗng nếu pass.",
                input_schema={
                    "type": "object",
                    "properties": {"repo_path": {"type": "string"}},
                    "required": ["repo_path"],
                },
            ),
            ToolDef(
                name="go_test",
                description="(MÔ PHỎNG) Chạy `go test ./... -cover -race`. Trả summary mỗi package.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "verbose": {"type": "boolean"},
                    },
                    "required": ["repo_path"],
                },
            ),
            ToolDef(
                name="go_vet",
                description="(MÔ PHỎNG) Chạy `go vet ./...`. Trả cảnh báo, rỗng nếu sạch.",
                input_schema={
                    "type": "object",
                    "properties": {"repo_path": {"type": "string"}},
                    "required": ["repo_path"],
                },
            ),
            ToolDef(
                name="create_gitlab_repo",
                description=(
                    "(MÔ PHỎNG) Tạo project GitLab `provider-{partner}` trong namespace. "
                    "Trả web_url + ssh_url giả lập."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "description": "vd aqr/bill"},
                        "partner_name": {"type": "string"},
                    },
                    "required": ["namespace", "partner_name"],
                },
            ),
            ToolDef(
                name="create_mr",
                description=(
                    "(MÔ PHỎNG) Tạo Merge Request từ feature branch vào master. Trả URL MR giả lập. "
                    "Chỉ gọi sau khi user xác nhận ở checkpoint Phase 4."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_path": {"type": "string", "description": "vd aqr/bill/provider-vnpt"},
                        "source_branch": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["project_path", "source_branch", "title"],
                },
            ),
            ToolDef(
                name="merge_mr",
                description=(
                    "(MÔ PHỎNG) Merge nhanh MR vào nhánh `dev` để deploy sandbox. "
                    "Chỉ gọi sau khi user xác nhận. Trả trạng thái merged + commit SHA giả lập."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_path": {"type": "string"},
                        "target_branch": {"type": "string", "description": "Mặc định 'dev'."},
                    },
                    "required": ["project_path"],
                },
            ),
            ToolDef(
                name="deploy_sandbox",
                description=(
                    "(MÔ PHỎNG) Deploy nhánh dev lên môi trường sandbox và chạy healthcheck. "
                    "Trả sandbox_url + trạng thái healthcheck giả lập."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"partner_name": {"type": "string"}},
                    "required": ["partner_name"],
                },
            ),
            ToolDef(
                name="query_bill_sandbox",
                description=(
                    "(MÔ PHỎNG) Tra cứu hoá đơn trên sandbox bằng adapter vừa deploy. "
                    "Trả nội dung hoá đơn NGẪU NHIÊN (mã, tên KH, kỳ, số tiền...). "
                    "Bỏ trống customer_code → sinh luôn mã hoá đơn ngẫu nhiên."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "customer_code": {"type": "string", "description": "Mã hoá đơn/khách hàng; trống = random."},
                        "service_id": {"type": "string", "description": "DIEN/NUOC/NET... (mặc định DIEN)."},
                    },
                },
            ),
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "read_phase":
            phase = int(args.get("phase", 0))
            if phase not in _PHASE_NAMES:
                raise ValueError(f"phase không hợp lệ: {phase} (chỉ 1-4)")
            return _read_phase_file(phase)

        if tool_name == "read_reference":
            name = str(args.get("name", ""))
            fname = _REFERENCES.get(name)
            if fname is None:
                raise ValueError(f"reference không tồn tại: {name} (chọn {list(_REFERENCES)})")
            return (_CONTEXT_DIR / fname).read_text(encoding="utf-8")

        if tool_name == "go_vet":
            return ""  # mô phỏng: vet sạch

        if tool_name == "go_build":
            return ""  # mô phỏng: build pass (output rỗng = không lỗi)

        if tool_name == "go_test":
            # mô phỏng kết quả test pass với coverage hợp lý theo pattern repo provider.
            return (
                "ok  \tinternal/constant\t0.012s\tcoverage: 100.0% of statements\n"
                "ok  \tinternal/provider\t1.284s\tcoverage: 87.5% of statements\n"
                "ok  \tinternal/business/manager/common\t0.341s\tcoverage: 82.1% of statements\n"
                "ok  \tinternal/business/manager/electricity\t0.118s\tcoverage: 90.0% of statements\n"
                "exit_code: 0"
            )

        if tool_name == "create_gitlab_repo":
            partner = str(args.get("partner_name", "partner")).lower().strip()
            namespace = str(args.get("namespace", "aqr/bill")).strip("/")
            base = "https://gitlab.zalopay.vn"
            return json.dumps(
                {
                    "id": 111745,
                    "name": f"provider-{partner}",
                    "web_url": f"{base}/{namespace}/provider-{partner}",
                    "ssh_url": f"git@gitlab.zalopay.vn:{namespace}/provider-{partner}.git",
                    "note": "MÔ PHỎNG — chưa tạo repo thật trên GitLab",
                },
                ensure_ascii=False,
            )

        if tool_name == "create_mr":
            project = str(args.get("project_path", "aqr/bill/provider-partner")).strip("/")
            return json.dumps(
                {
                    "iid": 1,
                    "url": f"https://gitlab.zalopay.vn/{project}/-/merge_requests/1",
                    "source_branch": str(args.get("source_branch", "")),
                    "target_branch": "master",
                    "title": str(args.get("title", "")),
                    "note": "MÔ PHỎNG — chưa tạo MR thật trên GitLab",
                },
                ensure_ascii=False,
            )

        if tool_name == "merge_mr":
            project = str(args.get("project_path", "aqr/bill/provider-partner")).strip("/")
            target = str(args.get("target_branch") or "dev")
            return json.dumps(
                {
                    "merged": True,
                    "project_path": project,
                    "target_branch": target,
                    "merge_commit_sha": f"{random.randint(0, 16**8 - 1):08x}",
                    "pipeline": "passed",
                    "note": "MÔ PHỎNG — chưa merge thật trên GitLab",
                },
                ensure_ascii=False,
            )

        if tool_name == "deploy_sandbox":
            partner = str(args.get("partner_name", "partner")).lower().strip()
            return json.dumps(
                {
                    "deployed": True,
                    "environment": "sandbox",
                    "sandbox_url": f"https://sandbox-provider-{partner}.zalopay.vn",
                    "version": f"dev-{random.randint(0, 16**7 - 1):07x}",
                    "healthcheck": {"status": "healthy", "endpoint": "/health", "http_status": 200},
                    "note": "MÔ PHỎNG — không deploy thật, healthcheck giả lập thành công",
                },
                ensure_ascii=False,
            )

        if tool_name == "query_bill_sandbox":
            service_id = str(args.get("service_id") or "DIEN").upper()
            customer_code = str(args.get("customer_code") or "").strip()
            return json.dumps(_random_bill(customer_code, service_id), ensure_ascii=False)

        raise ValueError(f"tool không tồn tại: {tool_name}")
