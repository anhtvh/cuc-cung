"""PLUGIN #1 (design §3.3) — Flow 2: master factory, tool loop + handlers.

Flag BUILDER_ENABLED (contest: bật). Mọi handler validate qua Governance —
không tin model; lỗi trả ToolResult(is_error=True) + message rõ ràng để
master tự xử lý trong vòng lặp tool-use.
"""

import json
import logging
from pathlib import Path
from typing import Any

from app.core.governance import Governance, GovernanceError
from app.core.models import MASTER_AGENT_NAME, Agent, ItemStatus, Skill, Visibility
from app.llm.base import ToolDef, ToolResult

log = logging.getLogger(__name__)

MASTER_SYSTEM_PATH = Path(__file__).parent / "master_system.md"


def load_master_system_prompt() -> str:
    return MASTER_SYSTEM_PATH.read_text(encoding="utf-8")


# Flow 2: tools = [list_agents, get_agent_detail, create_agent, update_agent,
#                  list_skills, create_skill, attach_skill, submit_for_review, delete_agent]
MASTER_TOOLS: list[ToolDef] = [
    ToolDef(
        name="list_agents",
        description="Liệt kê agent trong registry (tên, mô tả, trạng thái, domain). LUÔN gọi trước khi tạo agent mới.",
        input_schema={
            "type": "object",
            "properties": {"domain": {"type": "string", "description": "Lọc theo domain (optional)"}},
        },
    ),
    ToolDef(
        name="get_agent_detail",
        description="Xem chi tiết một agent: persona prompt, skill đã gắn, connector, trạng thái.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    ToolDef(
        name="create_agent",
        description=(
            "Tạo agent mới ở trạng thái private (người tạo dùng được ngay). "
            "CHỈ gọi sau khi đã list_agents/list_skills và user xác nhận config. "
            "Nếu tool trả recommend_reuse, HỎI user trước — chỉ gọi lại với force=true khi user xác nhận muốn tạo mới."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên tự do (Unicode OK, vd 'Bé Pháp') hoặc PascalCase (vd ThamDinhHopDong); slug @mention tự sinh"},
                "tagline": {"type": "string", "description": "Mô tả ngắn hiển thị UI (≤80 ký tự, vd 'Hỗ trợ review hợp đồng')"},
                "description": {"type": "string", "description": "1-2 câu cho router: dùng khi nào"},
                "system_prompt": {"type": "string", "description": "Persona: vai trò → phạm vi → format → điều không làm (≥200 ký tự)"},
                "domain": {"type": "string", "description": "legal | hr | finance | tech | ..."},
                "connectors": {"type": "array", "items": {"type": "string"}, "description": "Server từ catalog, vd ['contract-db']"},
                "visibility": {"type": "string", "enum": ["company", "private"], "description": "Mặc định company"},
                "force": {"type": "boolean", "description": "true = bỏ qua recommend_reuse, tạo mới dù có agent tương tự"},
            },
            "required": ["name", "description", "system_prompt"],
        },
    ),
    ToolDef(
        name="update_agent",
        description=(
            "Sửa agent. Private/rejected: áp dụng ngay (về private). Public: bản sửa vào hàng chờ admin duyệt, "
            "bản đang chạy vẫn phục vụ."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "system_prompt": {"type": "string"},
                "domain": {"type": "string"},
                "connectors": {"type": "array", "items": {"type": "string"}},
                "visibility": {"type": "string", "enum": ["company", "private"]},
            },
            "required": ["name"],
        },
    ),
    ToolDef(
        name="list_skills",
        description="Liệt kê skill trong catalog chung (tên, mô tả, domain, version, trạng thái). LUÔN gọi trước khi tạo skill mới.",
        input_schema={
            "type": "object",
            "properties": {"domain": {"type": "string", "description": "Lọc theo domain (optional)"}},
        },
    ),
    ToolDef(
        name="create_skill",
        description=(
            "Tạo skill mới (markdown quy trình/checklist chuẩn hóa) vào catalog chung, trạng thái private. "
            "Tên theo convention <domain>-<viec>. "
            "Nếu tool trả recommend_reuse, HỎI user trước — chỉ gọi lại với force=true khi user xác nhận muốn tạo mới."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "vd legal-tham-dinh-hop-dong"},
                "description": {"type": "string", "description": "1-2 câu: skill này dùng khi nào"},
                "content": {"type": "string", "description": "Markdown quy trình/checklist đầy đủ"},
                "domain": {"type": "string"},
                "force": {"type": "boolean", "description": "true = bỏ qua recommend_reuse, tạo mới dù có skill tương tự"},
            },
            "required": ["name", "description", "content"],
        },
    ),
    ToolDef(
        name="attach_skill",
        description="Gắn một skill có sẵn vào agent (quan hệ n:n). Nội dung skill sẽ được inject vào system prompt của agent lúc chat.",
        input_schema={
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "skill_name": {"type": "string"},
            },
            "required": ["agent_name", "skill_name"],
        },
    ),
    ToolDef(
        name="submit_for_review",
        description="Submit agent hoặc skill (private) để admin duyệt. Sau khi approve, cả công ty thấy và router điều phối tới.",
        input_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["agent", "skill"], "description": "Mặc định agent"},
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    ToolDef(
        name="fetch_url",
        description=(
            "Fetch nội dung một trang web (HTML → plain text) để đọc và chưng cất thành skill. "
            "Dùng khi user cung cấp link tài liệu, wiki, runbook, hoặc quy trình online. "
            "Trả về title + text đã làm sạch (tối đa 8000 ký tự). "
            "Sau khi nhận kết quả, tóm tắt nội dung cho user xác nhận rồi mới gọi create_skill."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL cần fetch (http/https)"},
            },
            "required": ["url"],
        },
    ),
    ToolDef(
        name="delete_agent",
        description=(
            "Xóa vĩnh viễn agent private/rejected của user (kèm lịch sử chat và usage). "
            "Chỉ được xóa agent do chính user tạo ra và đang ở trạng thái private hoặc rejected. "
            "Hỏi xác nhận user trước khi gọi."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên agent cần xóa"},
            },
            "required": ["name"],
        },
    ),
    ToolDef(
        name="self_test_agent",
        description=(
            "Chạy self-test agent vừa tạo — sandbox không ghi memory, judge bằng model rẻ. "
            "Truyền acceptance case (scenario + expected) từ phỏng vấn bước 1. "
            "PASS hết → agent sẵn sàng giao user. FAIL → đọc lý do, sửa persona/skill rồi chạy lại (tối đa 2 lần)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "test_cases": {
                    "type": "array",
                    "description": "2–3 acceptance case từ phỏng vấn",
                    "items": {
                        "type": "object",
                        "properties": {
                            "scenario": {"type": "string", "description": "Câu hỏi/tình huống test"},
                            "expected": {"type": "string", "description": "Kỳ vọng ngắn về câu trả lời đúng"},
                        },
                        "required": ["scenario", "expected"],
                    },
                },
            },
            "required": ["agent_name", "test_cases"],
        },
    ),
    ToolDef(
        name="delegate_to_agent",
        description=(
            "Chuyển ngay yêu cầu của user sang agent chuyên biệt — frontend sẽ tự route và gửi message. "
            "Gọi khi: (1) vừa tạo xong agent mới và muốn nó trả lời ngay, "
            "hoặc (2) user có câu hỏi nghiệp vụ mà agent phù hợp đã active. "
            "Đây là hành động CUỐI CÙNG trong lượt — KHÔNG nói thêm gì sau khi gọi."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Tên agent nhận request"},
                "message": {"type": "string", "description": "Nội dung chuyển sang agent (giữ nguyên ý định gốc của user)"},
            },
            "required": ["agent_name", "message"],
        },
    ),
]


def _ok(payload: Any) -> ToolResult:
    return ToolResult(content=json.dumps(payload, ensure_ascii=False, default=str))


class MasterToolset:
    """Bộ tool quản trị của master, bound theo user đang chat (quyền sở hữu Flow 2)."""

    def __init__(self, agents, skills, governance: Governance, catalog, user_id: str, usage=None, tester=None):
        self._agents = agents
        self._skills = skills
        self._gov = governance
        self._catalog = catalog
        self._usage = usage
        self._user_id = user_id
        self._tester = tester  # AgentTester | None (HM3)

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        handler = getattr(self, f"_h_{name}", None)
        if handler is None:
            return ToolResult(content=f"tool không tồn tại: {name}", is_error=True)
        try:
            return handler(args)
        except GovernanceError as e:
            return ToolResult(content=str(e), is_error=True)
        except Exception as e:  # noqa: BLE001 — lỗi bất ngờ cũng trả về model, không vỡ stream
            log.exception("master tool %s lỗi", name)
            return ToolResult(content=f"lỗi hệ thống: {e}", is_error=True)

    # --- read ---

    def _h_fetch_url(self, args: dict) -> ToolResult:
        import ipaddress
        import re
        import socket as _socket
        import httpx
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse

        _PRIVATE_NETS = [
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("169.254.0.0/16"),  # cloud metadata endpoint (AWS/GCP)
            ipaddress.ip_network("::1/128"),
            ipaddress.ip_network("fc00::/7"),
            ipaddress.ip_network("fe80::/10"),
        ]

        def _safe_url(u: str) -> str | None:
            parsed = urlparse(u)
            host = parsed.hostname or ""
            if not host:
                return "URL thiếu hostname"
            try:
                resolved = _socket.gethostbyname(host)
                ip = ipaddress.ip_address(resolved)
                if any(ip in net for net in _PRIVATE_NETS):
                    return f"URL trỏ đến địa chỉ nội mạng ({resolved}) — không được phép vì lý do bảo mật"
            except (_socket.gaierror, ValueError):
                pass  # không resolve được → để httpx xử lý lỗi tự nhiên
            return None

        url: str = str(args["url"]).strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult(content="URL phải bắt đầu bằng http:// hoặc https://", is_error=True)
        ssrf_err = _safe_url(url)
        if ssrf_err:
            return ToolResult(content=ssrf_err, is_error=True)
        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(content=f"Timeout khi fetch '{url}' (>10s) — thử URL khác hoặc nhờ user copy/paste nội dung.", is_error=True)
        except httpx.HTTPStatusError as e:
            return ToolResult(content=f"HTTP {e.response.status_code} khi fetch '{url}'.", is_error=True)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"Không fetch được '{url}': {e}", is_error=True)

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return ToolResult(content=f"URL trả về '{content_type}' — chỉ hỗ trợ HTML/text. Nhờ user tải file về rồi upload.", is_error=True)

        soup = BeautifulSoup(resp.text, "html.parser")
        # Xóa nav, footer, script, style — giữ lại nội dung chính
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else url
        text = soup.get_text(separator="\n")
        # Gộp dòng trắng liên tiếp
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        MAX = 8000
        truncated = len(text) > MAX
        return _ok({
            "url": url,
            "title": title,
            "text": text[:MAX],
            "truncated": truncated,
            "note": "Tóm tắt nội dung cho user xác nhận trước khi gọi create_skill." + (" (nội dung bị cắt bớt do quá dài)" if truncated else ""),
        })

    def _h_list_agents(self, args: dict) -> ToolResult:
        domain = args.get("domain")
        all_visible = self._gov.visible_agents(self._user_id)
        if domain:
            all_visible = [a for a in all_visible if a.domain == domain]

        def _fmt(a: Agent) -> dict:
            return {
                "name": a.name,
                "description": a.description,
                "domain": a.domain,
                "status": a.status.value,
                "visibility": a.visibility.value,
                "skills": self._agents.skills_of(a.name),
                "connectors": a.connectors,
            }

        my_agents = [_fmt(a) for a in all_visible if a.created_by == self._user_id]

        # Top public agents phổ biến (không phải của user, không phải master)
        public_agents = [
            a for a in all_visible
            if a.created_by != self._user_id and a.status == ItemStatus.public
        ]
        top_names: list[str] = []
        if self._usage is not None:
            exclude = {a["name"] for a in my_agents} | {MASTER_AGENT_NAME}
            top_names = self._usage.top_agents(n=5, exclude_names=exclude)
        # Fallback nếu usage trống: lấy theo thứ tự created_at
        if not top_names:
            top_names = [a.name for a in public_agents][:5]
        top_names_set = set(top_names)
        suggested = [_fmt(a) for a in public_agents if a.name in top_names_set]
        # Giữ thứ tự theo usage rank
        suggested.sort(key=lambda x: top_names.index(x["name"]) if x["name"] in top_names else 99)

        return _ok({"my_agents": my_agents, "suggested_public": suggested})

    def _h_delete_agent(self, args: dict) -> ToolResult:
        name = str(args["name"])
        self._gov.delete_agent(name, self._user_id)
        return _ok({"deleted": name, "note": "Agent và toàn bộ lịch sử chat, usage đã được xóa vĩnh viễn."})

    def _h_get_agent_detail(self, args: dict) -> ToolResult:
        agent = self._agents.get(str(args["name"]))
        if agent is None or not self._gov.can_use_agent(agent, self._user_id):
            return ToolResult(content=f"agent '{args['name']}' không tồn tại hoặc bạn không có quyền xem.", is_error=True)
        data = agent.model_dump(mode="json")
        data["skills"] = self._agents.skills_of(agent.name)
        return _ok(data)

    def _h_list_skills(self, args: dict) -> ToolResult:
        all_skills = self._skills.list()
        # Chỉ trả skill public HOẶC skill của chính user (private của người khác → ẩn)
        skills = [
            s for s in all_skills
            if s.status == ItemStatus.public or s.created_by == self._user_id
        ]
        domain = args.get("domain")
        if domain:
            skills = [s for s in skills if s.domain == domain]
        return _ok(
            [
                {
                    "name": s.name,
                    "description": s.description,
                    "domain": s.domain,
                    "status": s.status.value,
                    "version": s.version,
                }
                for s in skills
            ]
        )

    # --- write ---

    def _h_create_agent(self, args: dict) -> ToolResult:
        name = str(args["name"]).strip()
        force = bool(args.get("force", False))
        connectors = list(args.get("connectors") or [])
        self._gov.check_duplicate_name("agent", name, user_id=self._user_id)
        self._gov.validate_agent_payload(
            name=name,
            description=str(args["description"]),
            system_prompt=str(args["system_prompt"]),
            connectors=connectors,
        )
        if not force:
            candidates = self._gov.dedup_candidates(
                "agent", name, str(args["description"]),
                user_id=self._user_id, domain=args.get("domain"),
            )
            if candidates:
                return _ok({
                    "recommend_reuse": candidates,
                    "note": (
                        "Tìm thấy agent public tương tự — hỏi user muốn dùng agent có sẵn "
                        "hay vẫn tạo mới (gọi lại với force=true)."
                    ),
                })
        agent = Agent(
            name=name,
            tagline=str(args["tagline"]).strip() if args.get("tagline") else None,
            description=str(args["description"]),
            system_prompt=str(args["system_prompt"]),
            connectors=connectors,
            domain=args.get("domain"),
            visibility=Visibility(args.get("visibility") or "company"),
            created_by=self._user_id,
        )
        self._gov.check_duplicate_slug(agent.slug)  # B-04: slug collision → @mention sai
        self._agents.create(agent)
        result: dict[str, Any] = {
            "created": name,
            "slug": agent.slug,
            "status": "private",
            "note": (
                f"Agent đã tạo. @mention slug = @{agent.slug} (chữ thường). "
                "Gọi self_test_agent để kiểm tra trước, sau đó submit_for_review hoặc để user test riêng."
            ),
        }
        warnings = self._gov.lint_agent_quality(name, str(args["description"]), str(args["system_prompt"]), connectors)
        if warnings:
            result["quality_warnings"] = warnings
        return _ok(result)

    def _h_update_agent(self, args: dict) -> ToolResult:
        name = str(args.get("name"))  # B-05: dùng .get() thay .pop() để không mutate dict caller
        fields = {k: v for k, v in args.items() if v is not None and k != "name"}
        item = self._gov.propose_update("agent", name, fields, self._user_id)
        if item.status == ItemStatus.public:
            return _ok({"updated": name, "note": "Agent đang active — bản sửa đã vào hàng chờ admin duyệt, bản đang chạy vẫn phục vụ."})
        return _ok({"updated": name, "status": item.status.value})

    def _h_create_skill(self, args: dict) -> ToolResult:
        name = str(args["name"]).strip()
        force = bool(args.get("force", False))
        self._gov.check_duplicate_name("skill", name, user_id=self._user_id)
        self._gov.validate_skill_payload(
            name=name, description=str(args["description"]), content=str(args["content"])
        )
        if not force:
            candidates = self._gov.dedup_candidates(
                "skill", name, str(args["description"]),
                user_id=self._user_id, domain=args.get("domain"),
            )
            if candidates:
                return _ok({
                    "recommend_reuse": candidates,
                    "note": (
                        "Tìm thấy skill public tương tự — hỏi user muốn dùng skill có sẵn (attach_skill) "
                        "hay vẫn tạo mới (gọi lại với force=true)."
                    ),
                })
        skill = Skill(
            name=name,
            description=str(args["description"]),
            content=str(args["content"]),
            domain=args.get("domain"),
            created_by=self._user_id,
        )
        self._skills.create(skill)
        result: dict[str, Any] = {"created": name, "status": "private", "version": 1}
        warnings = self._gov.lint_skill_quality(name, str(args["description"]), str(args["content"]))
        if warnings:
            result["quality_warnings"] = warnings
        return _ok(result)

    def _h_attach_skill(self, args: dict) -> ToolResult:
        agent_name = str(args["agent_name"])
        skill_name = str(args["skill_name"])
        agent = self._agents.get(agent_name)
        if agent is None:
            return ToolResult(content=f"agent '{agent_name}' không tồn tại.", is_error=True)
        if not self._gov.can_edit(agent, self._user_id):
            return ToolResult(content=f"chỉ người tạo ({agent.created_by}) hoặc admin được gắn skill vào '{agent_name}'.", is_error=True)
        if self._skills.get(skill_name) is None:
            return ToolResult(content=f"skill '{skill_name}' không tồn tại — list_skills để xem catalog.", is_error=True)
        self._agents.attach_skill(agent_name, skill_name)
        return _ok({"attached": {"agent": agent_name, "skill": skill_name}})

    def _h_submit_for_review(self, args: dict) -> ToolResult:
        kind = str(args.get("kind") or "agent")
        name = str(args["name"])
        item = self._gov.submit_for_review(kind, name, self._user_id)
        extra = ""
        if kind == "agent":
            private_skills = [
                sn
                for sn in self._agents.skills_of(name)
                if (sk := self._skills.get(sn)) is not None and sk.status == ItemStatus.private
            ]
            if private_skills:
                # L-02: tự động submit skill private gắn kèm thay vì chỉ cảnh báo
                auto_submitted: list[str] = []
                for sn in private_skills:
                    try:
                        self._gov.submit_for_review("skill", sn, self._user_id)
                        auto_submitted.append(sn)
                    except GovernanceError:
                        pass
                remaining = [sn for sn in private_skills if sn not in auto_submitted]
                if auto_submitted:
                    extra += f" Đã tự động submit skill {auto_submitted} để admin duyệt cùng."
                if remaining:
                    extra += f" LƯU Ý: skill {remaining} chưa submit được (không có quyền) — yêu cầu người tạo submit riêng."
        return _ok({"submitted": name, "kind": kind, "status": item.status.value, "note": "Chờ admin duyệt." + extra})

    def _h_self_test_agent(self, args: dict) -> ToolResult:
        if self._tester is None:
            return _ok({
                "skipped": True,
                "note": "Self-test bị tắt (SELF_TEST_ENABLED=false) — bỏ qua, gọi submit_for_review trực tiếp.",
            })
        from app.core.agent_test import TestCase
        agent_name = str(args["agent_name"])
        agent = self._agents.get(agent_name)
        if agent is None or not self._gov.can_use_agent(agent, self._user_id):
            return ToolResult(content=f"Agent '{agent_name}' không tồn tại.", is_error=True)
        raw = list(args.get("test_cases") or [])[:3]  # HM4: cap 3 cases
        if not raw:
            return ToolResult(content="Cần ít nhất 1 test case (scenario + expected).", is_error=True)
        test_cases = [TestCase(scenario=str(c["scenario"]), expected=str(c["expected"])) for c in raw]
        report = self._tester.run_tests(agent, test_cases)
        return _ok({
            "agent_name": agent_name,
            "all_passed": report.all_passed,
            "passed": report.passed,
            "total": report.total,
            "summary": report.summary(),
            "results": [
                {
                    "scenario": r.scenario,
                    "expected": r.expected,
                    "actual": r.actual[:500],
                    "passed": r.passed,
                    "reason": r.reason,
                }
                for r in report.results
            ],
            "note": (
                "✅ Tất cả test PASS — agent sẵn sàng! Gọi submit_for_review hoặc để user test thêm."
                if report.all_passed
                else f"❌ {report.failed}/{report.total} test FAIL — xem 'results' để biết lý do. "
                     "Sửa persona (update_agent) hoặc skill (create_skill) rồi gọi self_test_agent lại (tối đa 2 lần)."
            ),
        })

    def _h_delegate_to_agent(self, args: dict) -> ToolResult:
        agent_name = str(args["agent_name"])
        message = str(args.get("message", ""))
        agent = self._agents.get(agent_name)
        if agent is None or not self._gov.can_use_agent(agent, self._user_id):
            return ToolResult(content=f"Agent '{agent_name}' không tồn tại hoặc bạn không có quyền dùng.", is_error=True)
        return ToolResult(
            content=f"Đã chuyển sang @{agent_name}.",
            delegate_to=agent_name,
            delegate_message=message,
        )
