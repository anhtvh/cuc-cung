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

import base64
import json
import logging
import random
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from app.llm.base import ToolDef

log = logging.getLogger(__name__)

_UPIA_ROOT = Path(__file__).resolve().parent.parent / "agents" / "upia"
_PHASES_DIR = _UPIA_ROOT / "phases"
_CONTEXT_DIR = _UPIA_ROOT / "context"
_TEMPLATES_DIR = _UPIA_ROOT / "templates"
_TEMPLATE_PROJECT_DIR = _UPIA_ROOT / "template_project"

# Workspace + artifact đặt dưới data/ (đã gitignore) — KHÔNG bẩn repo.
# parents[2] = repo root (app/tools/partner_integration.py → app → root).
_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
_WORKSPACE_ROOT = _DATA_ROOT / "upia_workspace"
_ARTIFACT_ROOT = _DATA_ROOT / "upia_artifacts"

# Module path baseline của template (đổi tên khi package_project đóng gói).
_TEMPLATE_MODULE_SEGMENT = "provider-imedia"

# File text được rewrite module path khi đóng gói.
_TEXT_SUFFIXES = (".go", ".mod", ".yaml", ".yml", ".md", ".env", ".sum")

# Completeness gate: file BẮT BUỘC agent phải save_file trước khi đóng gói (định nghĩa
# "adapter compile được"). Thiếu bất kỳ cái nào → package_project trả danh sách thiếu, KHÔNG nén.
_REQUIRED_FILES = (
    "internal/constant/provider.go",
    "internal/entity/provider/provider.go",
    "internal/provider/client.go",
    "internal/provider/dto.go",
)
# Ngoài ra cần ≥1 converter: internal/business/manager/{type}/service.go (glob, không cố định type).

_PHASE_NAMES = {1: "Analysis", 2: "Scaffold", 3: "Implement", 4: "Test"}
_REFERENCES = {
    "provider-pattern": "zalopay-provider-pattern.md",
    "observability": "observability-protocol.md",
    "qc-format": "qc-test-case-reference.md",
}
# Khung file Go mẫu cho Phase 3 (agent/templates/*.go.tmpl) — nạp lazy như reference.
_TEMPLATES = {
    "provider-constants": "provider_constants.go.tmpl",
    "entity-provider": "entity_provider.go.tmpl",
    "provider-dto": "provider_dto.go.tmpl",
    "provider-client": "provider_client.go.tmpl",
    "converter-service": "converter_service.go.tmpl",
}


def _read_phase_file(phase: int) -> str:
    matches = sorted(_PHASES_DIR.glob(f"{phase:02d}_*.md"))
    if not matches:
        raise ValueError(f"không tìm thấy file phase {phase}")
    return matches[0].read_text(encoding="utf-8")


# --- Workspace per-conversation (cơ chế "đĩa là source-of-truth") -------------
def _safe_segment(value: str, fallback: str) -> str:
    """Chuẩn hoá 1 đoạn tên dùng trong path (conversation_id, partner) — chỉ [a-z0-9_-]."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", (value or "").strip()).strip("-")
    return cleaned or fallback


def _workspace_dir(conversation_id: str | None) -> Path:
    return _WORKSPACE_ROOT / _safe_segment(conversation_id or "", "default")


def _artifact_dir(conversation_id: str | None) -> Path:
    return _ARTIFACT_ROOT / _safe_segment(conversation_id or "", "default")


def _resolve_in(base: Path, rel: str) -> Path:
    """Ghép base/rel an toàn — chặn path traversal (../) và đường dẫn tuyệt đối."""
    rel = (rel or "").strip()
    if not rel:
        raise ValueError("path trống")
    if rel.startswith("/") or Path(rel).is_absolute():
        raise ValueError(f"không cho phép đường dẫn tuyệt đối: {rel}")
    target = (base / rel).resolve()
    base_r = base.resolve()
    if target != base_r and base_r not in target.parents:
        raise ValueError(f"đường dẫn ngoài workspace: {rel}")
    return target


def _list_workspace_files(ws: Path) -> list[Path]:
    if not ws.exists():
        return []
    return sorted(p for p in ws.rglob("*") if p.is_file())


def _missing_required(ws: Path) -> list[str]:
    """Trả danh sách file bắt buộc còn thiếu (completeness gate)."""
    missing = [rel for rel in _REQUIRED_FILES if not (ws / rel).is_file()]
    # ≥1 converter service
    has_converter = any(ws.glob("internal/business/manager/*/service.go"))
    if not has_converter:
        missing.append("internal/business/manager/{type}/service.go (≥1 converter)")
    return missing


def _rewrite_module_path(staging: Path, partner: str) -> None:
    """Đổi segment module path template → provider-{partner} trên toàn cây (idempotent)."""
    new_segment = f"provider-{partner}"
    if new_segment == _TEMPLATE_MODULE_SEGMENT:
        return
    for p in staging.rglob("*"):
        if p.is_file() and p.suffix in _TEXT_SUFFIXES:
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if _TEMPLATE_MODULE_SEGMENT in text:
                p.write_text(text.replace(_TEMPLATE_MODULE_SEGMENT, new_segment), encoding="utf-8")


def artifact_b64(conversation_id: str | None, filename: str, max_bytes: int = 6_000_000) -> str | None:
    """Đọc file ZIP đã đóng gói → base64 để gửi THẲNG về user qua kênh chat (không cần URL).
    Trả None nếu không có file hoặc vượt giới hạn (tránh nhồi SSE quá lớn)."""
    p = _artifact_dir(conversation_id) / Path(filename).name
    if not p.is_file() or p.stat().st_size > max_bytes:
        return None
    return base64.b64encode(p.read_bytes()).decode()


def _build_zip(conversation_id: str | None, partner: str) -> tuple[Path, int]:
    """Dựng project hoàn chỉnh: copy template base → overlay file workspace → đổi module path
    → nén ZIP (thư mục gốc provider-{partner}/). Trả (đường dẫn zip, số file)."""
    ws = _workspace_dir(conversation_id)
    art = _artifact_dir(conversation_id)
    root_name = f"provider-{partner}"
    staging = art / "_staging" / root_name

    # Dọn staging cũ + dựng base từ template (đã được làm sạch sẵn).
    if staging.parent.exists():
        shutil.rmtree(staging.parent)
    if not _TEMPLATE_PROJECT_DIR.exists():
        raise ValueError("thiếu template_project — không có base hạ tầng để đóng gói")
    shutil.copytree(_TEMPLATE_PROJECT_DIR, staging)

    # Overlay file agent đã save_file (workspace thắng — đè base).
    for src in _list_workspace_files(ws):
        rel = src.relative_to(ws)
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    _rewrite_module_path(staging, partner)

    # Nén — giữ thư mục gốc provider-{partner}/ cho gọn khi giải nén.
    art.mkdir(parents=True, exist_ok=True)
    zip_path = art / f"{root_name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=str(Path(root_name) / p.relative_to(staging)))
                file_count += 1

    shutil.rmtree(staging.parent, ignore_errors=True)  # dọn staging sau khi nén
    return zip_path, file_count


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
                name="read_template",
                description=(
                    "(THẬT) Nạp khung file Go mẫu cho Phase 3 — đọc NGAY TRƯỚC khi viết file "
                    "tương ứng: 'provider-constants' (constant/provider.go), 'entity-provider' "
                    "(entity/provider/provider.go), 'provider-dto' (provider/dto.go), "
                    "'provider-client' (provider/client.go), 'converter-service' "
                    "(business/manager/{type}/service.go). Viết file theo đúng pattern trong template."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": list(_TEMPLATES),
                            "description": "Tên template Go cần nạp.",
                        }
                    },
                    "required": ["name"],
                },
            ),
            ToolDef(
                name="save_file",
                description=(
                    "(THẬT) Ghi 1 file vào workspace của project đang dựng (đĩa thật, bền qua "
                    "context). Dùng MỖI khi tạo/sửa file: code Go, docs/, input/ "
                    "(vd path='internal/provider/client.go' hoặc 'docs/requirements.md'). "
                    "Đây là nơi lưu deliverable — KHÔNG cần in lại nội dung file ra chat."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Đường dẫn tương đối trong project (vd 'internal/config/config.go').",
                        },
                        "content": {"type": "string", "description": "Toàn bộ nội dung file."},
                    },
                    "required": ["path", "content"],
                },
                stateful=True,  # ghi vào workspace theo conversation → cần _conversation_id
            ),
            ToolDef(
                name="list_workspace",
                description=(
                    "(THẬT) Liệt kê các file đã save_file trong workspace (path + kích thước). "
                    "Gọi đầu mỗi phase để biết đã có gì trên đĩa → làm tiếp phần còn thiếu, "
                    "không dựa vào trí nhớ hội thoại."
                ),
                input_schema={"type": "object", "properties": {}},
                stateful=True,  # đọc workspace theo conversation → cần _conversation_id
            ),
            ToolDef(
                name="package_project",
                description=(
                    "(THẬT) Đóng gói project hoàn chỉnh thành file ZIP để gửi user: ghép hạ tầng "
                    "template + các file đã save_file + đổi module path theo partner. Kiểm tra "
                    "đủ file bắt buộc trước (thiếu → trả danh sách, KHÔNG nén). Trả download_url."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "partner_name": {"type": "string", "description": "Tên đối tác (đặt tên repo/zip)."}
                    },
                    "required": ["partner_name"],
                },
                stateful=True,  # đóng gói workspace theo conversation → cần _conversation_id
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

        if tool_name == "read_template":
            name = str(args.get("name", ""))
            fname = _TEMPLATES.get(name)
            if fname is None:
                raise ValueError(f"template không tồn tại: {name} (chọn {list(_TEMPLATES)})")
            return (_TEMPLATES_DIR / fname).read_text(encoding="utf-8")

        if tool_name == "save_file":
            cid = args.get("_conversation_id")
            ws = _workspace_dir(cid)
            rel = str(args.get("path", ""))
            content = args.get("content", "")
            if content is None:
                content = ""
            target = _resolve_in(ws, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            n_bytes = len(str(content).encode("utf-8"))
            total = len(_list_workspace_files(ws))
            # Result GỌN (chỉ ack) — không echo content để history không phình.
            return f"✓ saved {rel} ({n_bytes} B) — workspace hiện có {total} file"

        if tool_name == "list_workspace":
            cid = args.get("_conversation_id")
            ws = _workspace_dir(cid)
            files = _list_workspace_files(ws)
            if not files:
                return "workspace trống — chưa có file nào được save_file."
            lines = [f"{p.relative_to(ws)} ({p.stat().st_size} B)" for p in files]
            missing = _missing_required(ws)
            out = f"{len(files)} file trong workspace:\n" + "\n".join(lines)
            if missing:
                out += "\n\nFile bắt buộc còn THIẾU (cần trước khi package_project):\n- " + "\n- ".join(missing)
            else:
                out += "\n\n✓ Đã đủ file bắt buộc — sẵn sàng package_project."
            return out

        if tool_name == "package_project":
            cid = args.get("_conversation_id")
            ws = _workspace_dir(cid)
            if not _list_workspace_files(ws):
                return "Không thể đóng gói: workspace trống. Hãy save_file các file project trước."
            missing = _missing_required(ws)
            if missing:
                # Completeness gate: KHÔNG nén nửa vời.
                return (
                    "Chưa đóng gói được — thiếu file bắt buộc:\n- "
                    + "\n- ".join(missing)
                    + "\n\nHãy save_file các file này rồi gọi lại package_project."
                )
            partner = _safe_segment(str(args.get("partner_name", "")).lower(), "partner")
            zip_path, file_count = _build_zip(cid, partner)
            download_url = f"/artifacts/{_safe_segment(cid or '', 'default')}/{zip_path.name}"
            return json.dumps(
                {
                    "packaged": True,
                    "zip_name": zip_path.name,
                    "download_url": download_url,
                    "file_count": file_count,
                    "size_kb": round(zip_path.stat().st_size / 1024, 1),
                    "note": (
                        "Project hoàn chỉnh (hạ tầng template + code sinh ra). "
                        "Hệ thống ĐÃ TỰ gửi file ZIP về user kèm nút tải ngay dưới tin nhắn — "
                        "TUYỆT ĐỐI KHÔNG in/bịa bất kỳ link tải nào (không markdown link, không sandbox:/tmp/, "
                        "không download_url). Chỉ cần thông báo tên file zip_name. "
                        "Đây là chế độ thử nghiệm — chưa qua build/test thật."
                    ),
                },
                ensure_ascii=False,
            )

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
