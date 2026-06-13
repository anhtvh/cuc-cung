"""Flow 1 — Routing mỗi message vào.

Sticky session là client-side (UI giữ agent_name sau lần route đầu) — server stateless.
"""

import logging
import re
from pathlib import Path

from app.core.governance import Governance
from app.core.models import MASTER_AGENT_NAME, RouteDecision

log = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"(?<!\w)@([a-z][a-z0-9-]{1,63})\b")
_PROMPT_PATH = Path(__file__).parent / "prompts" / "router_system.md"
_SCHEMA_HINT = '{"agent_name": "string hoặc null", "confidence": "high|medium|low"}'


class IntentRouter:
    def __init__(self, governance: Governance, llm, router_model: str):
        self._governance = governance
        self._llm = llm
        self._router_model = router_model  # model rẻ nhất pool — rủi ro #3 credit
        self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    def route(self, user_id: str, message: str, agent_name: str | None = None) -> RouteDecision:
        candidates = {a.name: a for a in self._governance.visible_agents(user_id)}
        slug_map = {a.slug: a for a in candidates.values() if a.slug}
        # name_map: nhận diện mention theo TÊN hiển thị (có dấu/dấu cách) — UI có thể gửi
        # "@Bé Gà" thay vì "@be-ga"; key lowercase để match case-insensitive.
        name_map = {a.name.lower(): a for a in candidates.values()}
        # Thêm master vào slug_map để @daitongquan (và slug custom bất kỳ) → master
        _master = self._governance._agents.get(MASTER_AGENT_NAME)
        if _master and _master.slug and _master.slug not in slug_map:
            slug_map[_master.slug] = _master

        # 0. Đa-mention: ≥2 agent khác nhau được nhắc → Master điều phối (orchestration).
        _all_mentions = re.findall(r"@([a-z][a-z0-9-]{1,63})", message)
        _known = [slug_map[s].name for s in _all_mentions if s in slug_map]
        # Bổ sung mention theo tên (có dấu) cho đúng số lượng agent khi đếm đa-mention.
        # Match tên DÀI trước rồi "tiêu thụ" chuỗi đã khớp, để tên ngắn là prefix của tên
        # dài (vd "Bot" vs "Bot Pro") không bị đếm trùng → tránh kích hoạt orchestrate sai.
        _msg_lower = message.lower()
        _consume = _msg_lower
        for _n in sorted(name_map, key=len, reverse=True):
            _needle = f"@{_n}"
            if _needle in _consume:
                _known.append(name_map[_n].name)
                _consume = _consume.replace(_needle, " ")
        if len(set(_known)) >= 2:
            return RouteDecision(agent_name=MASTER_AGENT_NAME, routed_by="orchestrate")

        # 1. "@slug" mention ở bất kỳ vị trí — explicit override sticky session.
        #    @master xử lý riêng vì master không có trong candidates/slug_map.
        m = _MENTION_RE.search(message)
        if m:
            slug = m.group(1)
            if slug == MASTER_AGENT_NAME:
                return RouteDecision(agent_name=MASTER_AGENT_NAME, routed_by="mention")
            if slug in slug_map:
                return RouteDecision(agent_name=slug_map[slug].name, routed_by="mention")
            # @slug không tìm thấy → route master kèm note để UI hiển thị cho user biết
            log.warning("@mention slug '%s' không khớp agent nào (user=%s)", slug, user_id)
            return RouteDecision(
                agent_name=MASTER_AGENT_NAME,
                routed_by="fallback_unknown_mention",
                note=f"Không tìm thấy agent '@{slug}' — có thể chưa tồn tại hoặc chưa được duyệt. Chuyển về Master để hỗ trợ.",
            )

        # 1b. Mention theo TÊN hiển thị (vd "@Bé Gà") — regex slug ở trên không bắt được tên
        #     có dấu/dấu cách. Match tên dài nhất trước để tránh tên ngắn nuốt tên dài.
        for _n in sorted(name_map, key=len, reverse=True):
            if f"@{_n}" in _msg_lower:
                return RouteDecision(agent_name=name_map[_n].name, routed_by="mention")

        # 2. UI chọn / sticky session → dùng luôn (kể cả master).
        if agent_name:
            if agent_name == MASTER_AGENT_NAME or agent_name in candidates:
                return RouteDecision(agent_name=agent_name, routed_by="explicit")
            # L-09: sticky agent không còn visible (bị reject/private) → fallback master,
            # KHÔNG classify lại vì có thể route sang agent không liên quan mà user không hay.
            log.warning("agent_name '%s' không khả dụng với user %s → fallback master", agent_name, user_id)
            return RouteDecision(
                agent_name=MASTER_AGENT_NAME,
                routed_by="fallback_stale_agent",
                note=f"Agent '@{agent_name}' hiện không khả dụng (có thể đang chờ duyệt hoặc bị từ chối) — chuyển về Master.",
            )

        # 3. Classify ý định bằng 1 call MaaS (model rẻ) — JSON output.
        if candidates:
            listing = "\n".join(f"- {a.name}: {a.description}" for a in candidates.values())
            try:
                result = self._llm.classify_json(
                    system=self._prompt_template.format(agent_list=listing),
                    message=message,
                    schema_hint=_SCHEMA_HINT,
                    model=self._router_model,
                )
                name = result.get("agent_name")
                confidence = str(result.get("confidence", "low"))
                if name in candidates and confidence in ("high", "medium"):
                    return RouteDecision(agent_name=name, routed_by="classify", confidence=confidence)
            except Exception as e:  # noqa: BLE001 — classify lỗi thì về master, không chặn chat
                log.warning("router classify lỗi → fallback master: %s", e)

        # 4. null / low / không có ứng viên → MASTER (Flow 5 kịch bản: master đề nghị tạo mới).
        return RouteDecision(agent_name=MASTER_AGENT_NAME, routed_by="fallback_master")
