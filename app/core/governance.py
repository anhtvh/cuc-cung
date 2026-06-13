"""Flow 2b + Flow 4: state machine maker-checker, validate phía app, dedup.

private ──submit──► pending_review ──approve──► public
  │                     └──reject (kèm lý do)──► rejected ──maker sửa──► private
private: NGƯỜI TẠO dùng được ngay. public: cả công ty thấy, router mới điều phối tới.

Validate phía app — KHÔNG tin model (Flow 2).
"""

import logging
import re
from typing import Any

from app.core.models import (
    MASTER_AGENT_NAME,
    Agent,
    ItemStatus,
    Skill,
    Visibility,
    now_iso,
)

log = logging.getLogger(__name__)


class GovernanceError(Exception):
    """Lỗi validate/transition — message trả thẳng về tool_result (is_error) cho master tự xử lý."""


# Agent: tên tự do Unicode 2-64 ký tự, không có khoảng trắng đầu/cuối (Flow 1).
# @mention dùng slug ASCII tự sinh (vd "Bé Bơ" → @be-bo).
AGENT_NAME_RE = re.compile(r"^(?! )[\w ]{2,64}(?<! )$")
# Skill: <domain>-<viec> (Flow 2b), vd "legal-tham-dinh-hop-dong".
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$")

# Chặn nội dung chứa secret lọt vào prompt/skill (Flow 2 validate).
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|client[_-]?secret)\b\s*[:=]\s*\S{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{20,}"),
]


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


# Field cho phép sửa qua update (cả direct edit lẫn pending_changes).
_AGENT_EDITABLE = {"description", "system_prompt", "connectors", "domain", "visibility", "escalate_enabled", "tagline"}
_SKILL_EDITABLE = {"description", "content", "domain"}

# Field editable nào là enum → coerce string thô (từ pending_changes JSON / API body) về
# enum trước khi setattr. Nếu không, gán str vào field Pydantic enum → repo.update gọi
# `a.visibility.value` sẽ raise AttributeError ('str' object has no attribute 'value').
_ENUM_FIELDS = {"visibility": Visibility}


def _coerce_field(key: str, value: Any) -> Any:
    enum_cls = _ENUM_FIELDS.get(key)
    if enum_cls is not None and not isinstance(value, enum_cls):
        return enum_cls(value)
    return value


class Governance:
    """Service dùng chung cho builder handlers và API review."""

    def __init__(
        self,
        agents,
        skills,
        admin_ids: set[str],
        catalog_servers: list[str],
        min_prompt_length: int = 200,
        llm=None,
        dedup_model: str | None = None,
    ):
        self._agents = agents
        self._skills = skills
        self._admin_ids = admin_ids
        self._catalog_servers = set(catalog_servers)
        self._min_prompt_length = min_prompt_length
        # llm optional: dedup mềm bằng LLM classify; không có → chỉ chặn cứng theo tên.
        self._llm = llm
        self._dedup_model = dedup_model

    # --- quyền ---

    def is_admin(self, user_id: str) -> bool:
        return user_id in self._admin_ids

    def can_edit(self, item: Agent | Skill, user_id: str) -> bool:
        """Update/submit chỉ owner hoặc admin (Flow 2)."""
        return item.created_by == user_id or self.is_admin(user_id)

    def can_use_agent(self, agent: Agent, user_id: str) -> bool:
        """Visibility (Flow 1): active+company → mọi người; còn lại chỉ owner/admin."""
        if agent.name == MASTER_AGENT_NAME:
            return True
        if agent.status == ItemStatus.public and agent.visibility == Visibility.company:
            return True
        return self.can_edit(agent, user_id)

    def visible_agents(self, user_id: str) -> list[Agent]:
        """Ứng viên cho router + Catalog: agent active company + agent của chính user."""
        out: dict[str, Agent] = {}
        for a in self._agents.list(status=ItemStatus.public):
            if a.visibility == Visibility.company and a.name != MASTER_AGENT_NAME:
                out[a.name] = a
        for a in self._agents.list(created_by=user_id):
            if a.name != MASTER_AGENT_NAME and a.status != ItemStatus.rejected:
                out[a.name] = a
        return list(out.values())

    # --- validate (không tin model) ---

    def validate_agent_payload(
        self,
        name: str,
        description: str,
        system_prompt: str,
        connectors: list[str],
    ) -> None:
        # I-04: reject tên có khoảng trắng kép — slugify sẽ collapse thành slug trùng
        name_norm = re.sub(r"\s+", " ", name).strip()
        if name_norm != name:
            raise GovernanceError(
                f"Tên agent '{name}' chứa khoảng trắng thừa — hãy dùng '{name_norm}'."
            )
        if not AGENT_NAME_RE.match(name):
            raise GovernanceError(
                f"Tên agent '{name}' không hợp lệ: 2-64 ký tự, không có khoảng trắng đầu/cuối (vd 'Bé Bơ' hoặc 'ThamDinhHopDong')."
            )
        if not description.strip():
            raise GovernanceError("description trống — router cần description để điều phối (1-2 câu, nêu rõ 'dùng khi nào').")
        if len(system_prompt) < self._min_prompt_length:
            raise GovernanceError(
                f"Persona prompt quá ngắn ({len(system_prompt)} < {self._min_prompt_length} ký tự). "
                "Theo template: vai trò → phạm vi → format output → điều không làm."
            )
        if contains_secret(system_prompt) or contains_secret(description):
            raise GovernanceError("Prompt/description chứa pattern API key/secret — không được lưu credential vào agent (dùng Identity module).")
        for c in connectors:
            if c not in self._catalog_servers:
                raise GovernanceError(
                    f"Connector '{c}' không có trong catalog. Catalog hiện có: {sorted(self._catalog_servers)}."
                )

    def validate_skill_payload(self, name: str, description: str, content: str) -> None:
        if not SKILL_NAME_RE.match(name):
            raise GovernanceError(
                f"Tên skill '{name}' sai convention <domain>-<viec> (chữ thường, gạch nối), vd 'legal-tham-dinh-hop-dong'."
            )
        if not description.strip():
            raise GovernanceError("description trống — Catalog và dedup cần description.")
        if not content.strip():
            raise GovernanceError("content trống — skill phải là markdown quy trình/checklist.")
        if contains_secret(content):
            raise GovernanceError("Nội dung skill chứa pattern API key/secret — không được lưu credential vào skill.")

    # --- dedup (Flow 2b, chặn 3 tầng — đây là tầng app) ---

    def check_duplicate_slug(self, slug: str) -> None:
        """Slug trùng → @mention trỏ sai agent → hard-block (B-04, L-08)."""
        for a in self._agents.list():
            if a.slug == slug:
                raise GovernanceError(
                    f"Slug '@{slug}' đã tồn tại (agent '{a.name}') — đặt tên khác để tránh xung đột @mention."
                )

    def check_duplicate_name(self, kind: str, name: str, user_id: str | None = None) -> None:
        """Trùng tên chính xác → hard-block (name là PK toàn cục).
        Phân biệt 3 trường hợp để thông báo đúng ngữ cảnh."""
        repo = self._agents if kind == "agent" else self._skills
        existing = repo.get(name)
        if existing is None:
            return
        if user_id and existing.created_by == user_id:
            raise GovernanceError(
                f"{kind} tên '{name}' đã tồn tại (của bạn, trạng thái: {existing.status.value}) — dùng update_{kind} để sửa."
            )
        if existing.status == ItemStatus.private:
            raise GovernanceError(
                f"{kind} tên '{name}' đã tồn tại (riêng tư của người khác, bạn không xem được) — hãy chọn tên khác."
            )
        raise GovernanceError(f"{kind} tên '{name}' đã tồn tại — dùng/update cái có sẵn hoặc đổi tên.")

    def dedup_candidates(
        self,
        kind: str,
        name: str,
        description: str,
        user_id: str | None = None,
        domain: str | None = None,
    ) -> list[dict[str, str]]:
        """LLM classify chồng lấn description → soft-warning, KHÔNG hard-block
        (tránh false positive chặn flow lúc demo live).
        Chỉ so sánh với item user_id được thấy — private của người khác bỏ qua."""
        def _visible_skill(s: Skill) -> bool:
            return s.status == ItemStatus.public or (user_id is not None and s.created_by == user_id)

        if kind == "agent":
            candidates_raw = [
                (a.name, a.description, a.domain)
                for a in self._agents.list()
                if a.name != MASTER_AGENT_NAME and self.can_use_agent(a, user_id or "")
            ]
        else:
            candidates_raw = [
                (s.name, s.description, s.domain)
                for s in self._skills.list()
                if _visible_skill(s)
            ]

        # L-07: pre-filter theo domain trước khi gửi lên LLM — giảm credit + tăng precision
        # fallback về toàn bộ chỉ khi không có candidate nào cùng domain
        if domain and candidates_raw:
            same_domain = [(n, d, dm) for n, d, dm in candidates_raw if dm == domain]
            if same_domain:
                candidates_raw = same_domain

        existing = [(n, d) for n, d, _ in candidates_raw]
        if not existing or self._llm is None:
            return []
        listing = "\n".join(f"- {n}: {d}" for n, d in existing)
        try:
            result = self._llm.classify_json(
                system=(
                    f"Bạn kiểm tra trùng lặp {kind} trong catalog nội bộ. "
                    "So mô tả item MỚI với danh sách HIỆN CÓ, liệt kê item chồng lấn rõ rệt về mục đích (nếu có)."
                ),
                message=f"Item mới: {name}: {description}\n\nHiện có:\n{listing}",
                schema_hint='{"overlapping": ["ten-item-1", ...]}  // mảng rỗng nếu không trùng',
                model=self._dedup_model,
            )
            names = {str(n) for n in result.get("overlapping", [])}
            return [{"name": n, "description": d} for n, d in existing if n in names]
        except Exception as e:  # noqa: BLE001 — dedup mềm fail thì bỏ qua, không chặn flow
            log.warning("dedup LLM check fail, bỏ qua: %s", e)
            return []

    # --- state machine ---

    def _get_or_raise(self, kind: str, name: str) -> Agent | Skill:
        repo = self._agents if kind == "agent" else self._skills
        item = repo.get(name)
        if item is None:
            raise GovernanceError(f"{kind} '{name}' không tồn tại.")
        return item

    def delete_agent(self, name: str, user_id: str) -> None:
        """Xóa agent private/rejected — chỉ owner hoặc admin."""
        agent = self._get_or_raise("agent", name)
        if name == MASTER_AGENT_NAME:
            raise GovernanceError("Không được xóa Master Agent.")
        if not self.can_edit(agent, user_id):
            raise GovernanceError(f"Chỉ người tạo ({agent.created_by}) hoặc admin được xóa '{name}'.")
        if agent.status not in (ItemStatus.private, ItemStatus.rejected):
            raise GovernanceError(
                f"Chỉ xóa được agent đang private hoặc rejected (hiện tại: {agent.status.value}). "
                "Agent public cần reject trước khi xóa."
            )
        self._agents.delete(name)

    def propose_update(self, kind: str, name: str, fields: dict[str, Any], user_id: str) -> Agent | Skill:
        """Sửa item (Flow 4): draft/rejected → sửa trực tiếp (về draft);
        active → ghi pending_changes, bản active VẪN phục vụ; pending_review → chặn."""
        item = self._get_or_raise(kind, name)
        if not self.can_edit(item, user_id):
            raise GovernanceError(f"Chỉ người tạo ({item.created_by}) hoặc admin được sửa '{name}'.")
        editable = _AGENT_EDITABLE if kind == "agent" else _SKILL_EDITABLE
        unknown = set(fields) - editable
        if unknown:
            raise GovernanceError(f"Field không cho phép sửa: {sorted(unknown)}. Cho phép: {sorted(editable)}.")
        if not fields:
            raise GovernanceError("Không có field nào để sửa.")

        if item.status == ItemStatus.pending_review:
            raise GovernanceError(f"'{name}' đang chờ duyệt — đợi admin xử lý hoặc nhờ admin reject để sửa.")

        if item.status == ItemStatus.public:
            # Hạ visibility xuống 'private' cho phép tức thì — siết quyền không cần duyệt.
            # Visibility chỉ có {company, private}; chỉ 'private' là siết quyền, các thay
            # đổi khác (kể cả nâng lại 'company') đi qua hàng chờ duyệt như mọi field khác.
            vis_field = fields.get("visibility") if kind == "agent" else None
            if vis_field is not None:
                try:
                    Visibility(vis_field)  # validate sớm, tránh giá trị rác
                except ValueError as e:
                    raise GovernanceError(f"visibility không hợp lệ: '{vis_field}'") from e
            if vis_field == Visibility.private.value:
                other_fields = {k: v for k, v in fields.items() if k != "visibility"}
                item.visibility = Visibility.private
                if other_fields:
                    merged = dict(item.pending_changes or {})
                    merged.update(other_fields)
                    self._validate_merged(kind, item, merged)
                    item.pending_changes = merged
            else:
                # Merge với pending_changes hiện có — tránh mất thay đổi lần trước chưa duyệt.
                merged = dict(item.pending_changes or {})
                merged.update(fields)
                self._validate_merged(kind, item, merged)
                item.pending_changes = merged
        else:  # draft | rejected → sửa trực tiếp, quay về draft
            self._validate_merged(kind, item, fields)
            for k, v in fields.items():
                setattr(item, k, _coerce_field(k, v))  # coerce enum (vd visibility) tránh gán str
            item.status = ItemStatus.private
            item.review_note = None
        # L-11: updated_at set 1 lần duy nhất trong repo.update() — không set lại ở đây
        repo = self._agents if kind == "agent" else self._skills
        return repo.update(item)

    def _validate_merged(self, kind: str, item: Agent | Skill, fields: dict[str, Any]) -> None:
        """Validate trạng thái SAU khi áp fields (không mutate item)."""
        if kind == "agent":
            self.validate_agent_payload(
                name=item.name,
                description=fields.get("description", item.description),
                system_prompt=fields.get("system_prompt", item.system_prompt),
                connectors=fields.get("connectors", item.connectors),
            )
            if "visibility" in fields:
                try:
                    Visibility(fields["visibility"])
                except ValueError as e:
                    raise GovernanceError(f"visibility không hợp lệ: '{fields['visibility']}'") from e
        else:
            self.validate_skill_payload(
                name=item.name,
                description=fields.get("description", item.description),
                content=fields.get("content", item.content),
            )

    def submit_for_review(self, kind: str, name: str, user_id: str) -> Agent | Skill:
        item = self._get_or_raise(kind, name)
        if not self.can_edit(item, user_id):
            raise GovernanceError(f"Chỉ người tạo ({item.created_by}) hoặc admin được submit '{name}'.")
        if item.status != ItemStatus.private:
            raise GovernanceError(f"Chỉ submit được từ private (hiện tại: {item.status.value}).")
        # Ràng buộc: agent con BẮT BUỘC có ≥1 skill — skill mã hoá quy trình/nguyên tắc
        # để mỗi lần gọi agent đều nhất quán (kể cả agent chỉ dùng connector).
        if kind == "agent" and not self._agents.skills_of(name):
            raise GovernanceError(
                f"Agent '{name}' chưa gắn skill nào — mọi agent con phải có ≥1 skill để chuẩn hoá "
                "quy trình/nguyên tắc làm việc. Tạo skill (create_skill) rồi gắn (attach_skill) trước khi submit."
            )
        # Fix nghịch lý #3: submit duyệt = ý định CHIA SẺ công ty. Nếu agent đang
        # visibility=private (vd master tạo mặc định private), nâng lên company — nếu không,
        # sau approve agent thành public+private → KHÔNG ai khác thấy, maker-checker vô nghĩa
        # và lời hứa "cả công ty thấy" sai. Lúc pending vẫn chỉ owner dùng (status≠public),
        # nên không lộ sớm. Use-case "tạm ẩn" (public→private) là hành động sau approve, không đụng.
        if kind == "agent" and item.visibility == Visibility.private:
            item.visibility = Visibility.company
            log.info("submit_for_review: nâng visibility private→company cho agent '%s' (ý định chia sẻ)", name)
        item.status = ItemStatus.pending_review
        repo = self._agents if kind == "agent" else self._skills
        return repo.update(item)

    def retract_submission(self, kind: str, name: str, user_id: str) -> Agent | Skill:
        """Hủy nộp duyệt: pending_review → private (chỉ owner hoặc admin)."""
        item = self._get_or_raise(kind, name)
        if not self.can_edit(item, user_id):
            raise GovernanceError(f"Chỉ người tạo ({item.created_by}) hoặc admin được hủy submit '{name}'.")
        if item.status != ItemStatus.pending_review:
            raise GovernanceError(f"Chỉ hủy được từ pending_review (hiện tại: {item.status.value}).")
        item.status = ItemStatus.private
        repo = self._agents if kind == "agent" else self._skills
        return repo.update(item)

    def approve(self, kind: str, name: str, admin_id: str) -> Agent | Skill:
        if not self.is_admin(admin_id):
            raise GovernanceError("Chỉ admin (checker) được approve.")
        item = self._get_or_raise(kind, name)

        # Trường hợp 1: item active có pending_changes → áp dụng bản chờ duyệt (Flow 4).
        if item.status == ItemStatus.public and item.pending_changes:
            for k, v in item.pending_changes.items():
                setattr(item, k, _coerce_field(k, v))  # coerce enum (vd visibility) tránh gán str
            item.pending_changes = None
            if kind == "skill":
                item.version += 1  # MỌI agent gắn nó nhận bản mới (đã qua duyệt)
            item.reviewed_by = admin_id
            repo = self._agents if kind == "agent" else self._skills
            return repo.update(item)

        # Trường hợp 2: pending_review → active.
        if item.status != ItemStatus.pending_review:
            raise GovernanceError(f"'{name}' không ở trạng thái chờ duyệt (hiện tại: {item.status.value}).")
        if kind == "agent":
            # Ràng buộc approve: MỌI skill agent gắn phải active (Flow 2b).
            not_active = [
                sn
                for sn in self._agents.skills_of(name)
                if (sk := self._skills.get(sn)) is None or sk.status != ItemStatus.public
            ]
            if not_active:
                raise GovernanceError(
                    f"Agent gắn skill chưa active: {not_active} — duyệt skill trước (trang Review hiện cùng nhau)."
                )
        item.status = ItemStatus.public
        item.reviewed_by = admin_id
        item.review_note = None
        # L-11: updated_at set trong repo.update() — không set lại ở đây
        repo = self._agents if kind == "agent" else self._skills
        return repo.update(item)

    # --- lint (HM2): soft quality check, không raise, không chặn flow ---

    def lint_agent_quality(
        self,
        name: str,
        description: str,
        system_prompt: str,
        connectors: list[str],
    ) -> list[str]:
        """Soft check nội dung ngữ nghĩa — trả list warning để master tự sửa."""
        warnings: list[str] = []
        prompt_lower = system_prompt.lower()

        # Persona 4 phần (keyword scan)
        _sections = [
            (["vai trò", "bạn là", "you are", "mình là", "i am"], "vai trò"),
            (["phạm vi", "không làm", "không được", "out of scope", "ngoài phạm vi", "scope"], "phạm vi"),
            (["format", "output", "định dạng", "trả về", "kết quả", "markdown", "bullet", "danh sách"], "format output"),
            (["tuyệt đối không", "không bao giờ", "never", "cấm", "must not", "lưu ý quan trọng", "không được phép"], "điều không làm"),
        ]
        for keywords, label in _sections:
            if not any(k in prompt_lower for k in keywords):
                warnings.append(
                    f"Persona chưa rõ phần '{label}' — template 4 phần: vai trò, phạm vi, format output, điều không làm."
                )

        if len(system_prompt) < 400:
            warnings.append(
                "Persona ngắn (<400 ký tự) — agent có thể hành xử chung chung. "
                "Cân nhắc thêm phạm vi rõ, format output, hoặc ví dụ cụ thể."
            )

        # Tone/pronoun check
        tone_ok = any(k in prompt_lower for k in ["xưng em", "xưng \"em\"", "xưng 'em'", "thân thiện", "gần gũi", "dễ thương"])
        if not tone_ok:
            warnings.append(
                "Persona chưa có hướng dẫn xưng hô — thêm 'Xưng em, gọi user là bạn; tone thân thiện, gần gũi, dễ thương' vào đầu persona."
            )

        # Connector alignment (soft)
        combined = (system_prompt + " " + description).lower()
        needs_web = any(k in combined for k in ["tìm kiếm", "search", "tra cứu", "internet", "thông tin mới nhất", "real-time"])
        has_web = any("search" in c or "web" in c for c in connectors)
        if needs_web and not has_web:
            warnings.append(
                "Persona/description nhắc tìm kiếm/tra cứu internet nhưng chưa gắn connector 'web-search' — "
                "agent sẽ không tra cứu được thông tin thực tế."
            )

        return warnings

    def lint_skill_quality(self, name: str, description: str, content: str) -> list[str]:
        """Soft check nội dung skill — trả list warning để master tự sửa."""
        warnings: list[str] = []

        has_structure = bool(
            re.search(r"^#{1,3}\s+\S", content, re.MULTILINE)
            or re.search(r"^\s*\d+\.\s+\S", content, re.MULTILINE)
            or re.search(r"^\s*[-*+]\s+\S", content, re.MULTILINE)
        )
        if not has_structure:
            warnings.append(
                "Skill content chỉ có văn xuôi — agent khó áp dụng chính xác. "
                "Dùng checklist (- [ ]), danh sách đánh số, hoặc heading ## để phân bước rõ ràng."
            )

        if len(content) < 200:
            warnings.append(
                "Skill content khá ngắn (<200 ký tự) — cân nhắc bổ sung tiêu chí cụ thể, ví dụ, hoặc edge case."
            )

        content_lower = content.lower()
        if len(content) > 500 and not any(k in content_lower for k in ["ví dụ", "example", "vd:", "e.g."]):
            warnings.append(
                "Skill chưa có ví dụ cụ thể — thêm 1–2 ví dụ giúp agent hiểu đúng tiêu chí hơn (không bắt buộc)."
            )

        return warnings

    def reject(self, kind: str, name: str, admin_id: str, reason: str) -> Agent | Skill:
        if not self.is_admin(admin_id):
            raise GovernanceError("Chỉ admin (checker) được reject.")
        if not reason.strip():
            raise GovernanceError("Reject bắt buộc nhập lý do (Flow 2b).")
        item = self._get_or_raise(kind, name)

        # Reject bản sửa đổi trên item active: huỷ pending_changes, bản active giữ nguyên.
        if item.status == ItemStatus.public and item.pending_changes:
            item.pending_changes = None
            item.reviewed_by = admin_id
            item.review_note = reason
        elif item.status == ItemStatus.pending_review:
            item.status = ItemStatus.rejected  # KHÔNG phải trạng thái cuối — maker sửa → private
            item.reviewed_by = admin_id
            item.review_note = reason
        else:
            raise GovernanceError(f"'{name}' không có gì để reject (hiện tại: {item.status.value}).")
        # L-11: updated_at set trong repo.update() — không set lại ở đây
        repo = self._agents if kind == "agent" else self._skills
        return repo.update(item)
