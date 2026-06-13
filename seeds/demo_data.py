"""Seed dữ liệu (rủi ro #6 — SQLite mất khi container restart thì tái tạo được).

- Master agent: row đặc biệt `name='master'` (§4) — system_prompt luôn đồng bộ
  lại từ builder/master_system.md mỗi lần khởi động (file là nguồn sự thật).
- Agent/skill mẫu cho demo: chỉ seed khi DB chưa có (không ghi đè dữ liệu thật).

L-10 NOTE: seed data bypass governance flow (status=public, reviewed_by="admin"
được set trực tiếp). Đây là SEED-ONLY exception — không dùng pattern này ở nơi khác.
Mọi tạo agent/skill runtime PHẢI đi qua Governance.submit_for_review + Governance.approve.
"""

import logging

from app.builder.master import load_master_system_prompt
from app.core.models import Agent, ItemStatus, Skill, Visibility

log = logging.getLogger(__name__)

_SAMPLE_SKILL = Skill(
    name="legal-tham-dinh-hop-dong",
    description="Checklist chuẩn 12 mục của phòng Pháp chế để thẩm định hợp đồng. Dùng khi cần review, đánh giá rủi ro một hợp đồng.",
    content="""# Checklist thẩm định hợp đồng (phòng Pháp chế — v1)

Thẩm định LẦN LƯỢT đủ 12 mục, mỗi mục kết luận: ĐẠT / RỦI RO / THIẾU.

1. **Chủ thể ký kết** — đúng pháp nhân, người ký đúng thẩm quyền?
2. **Phạm vi công việc/hàng hóa** — mô tả đủ rõ để nghiệm thu?
3. **Giá trị & điều khoản thanh toán** — mốc thanh toán gắn nghiệm thu? Giữ lại bao nhiêu %?
4. **Thời hạn & tiến độ** — có deadline cụ thể, chế tài chậm tiến độ?
5. **Giới hạn trách nhiệm (liability cap)** — BẮT BUỘC có (QD-PL-02); mức trần bao nhiêu?
6. **Phạt vi phạm & bồi thường** — mức phạt ≤ 8% giá trị phần vi phạm (Luật Thương mại)?
7. **Điều khoản chấm dứt** — quyền đơn phương chấm dứt, thời gian báo trước?
8. **Bảo mật thông tin** — BẮT BUỘC có (QD-PL-02)?
9. **Sở hữu trí tuệ** — ai sở hữu sản phẩm/dữ liệu phát sinh?
10. **Bất khả kháng** — định nghĩa và nghĩa vụ thông báo?
11. **Luật áp dụng & giải quyết tranh chấp** — luật Việt Nam, trọng tài VIAC (QD-PL-02)?
12. **Thẩm quyền phê duyệt nội bộ** — đối chiếu QD-PL-01: >1 tỷ cần CFO, >5 tỷ cần HĐQT.

Kết quả trình bày dạng bảng: | Mục | Kết luận | Ghi chú/rủi ro | — kết thúc bằng
mục "KHUYẾN NGHỊ" (ký / đàm phán lại / từ chối) kèm 3 rủi ro lớn nhất.""",
    domain="legal",
    status=ItemStatus.public,
    created_by="admin",
    reviewed_by="admin",
)

_SAMPLE_AGENT = Agent(
    name="Bé Pháp",
    tagline="Hỗ trợ review & thẩm định hợp đồng",
    description="Thẩm định hợp đồng theo checklist chuẩn 12 mục của phòng Pháp chế. Dùng khi user cần review, đánh giá rủi ro, hoặc cho ý kiến về một hợp đồng.",
    system_prompt="""Bạn là chuyên viên thẩm định hợp đồng của phòng Pháp chế.
Xưng **em**, gọi user là **bạn** — tone thân thiện, gần gũi, dễ thương như đồng nghiệp
nhiệt tình hỗ trợ. Cuối mỗi câu trả lời hỏi thêm nếu cần.

**Vai trò:** nhận nội dung hợp đồng (toàn văn hoặc tóm tắt) và thẩm định theo
quy trình chuẩn trong phần QUY TRÌNH CHUẨN bên dưới.

**Phạm vi:** chỉ thẩm định và tư vấn rủi ro hợp đồng thương mại. Không soạn
hợp đồng mới từ đầu, không tư vấn thuế/kế toán.

**Cách làm việc:** nếu user chưa cung cấp nội dung hợp đồng, hỏi xin nhẹ nhàng.
Có thể dùng connector contract-db để tìm hợp đồng tương tự trong kho làm chuẩn
đối chiếu khi user yêu cầu so sánh.

**Format output:** bảng kết quả theo đúng format quy định trong checklist,
tiếng Việt, kết luận rõ ràng, không vòng vo.

**Tuyệt đối không:** đưa ra cam kết pháp lý thay cho phòng Pháp chế; mọi kết
luận kèm khuyến nghị "cần phòng Pháp chế xác nhận trước khi ký".""",
    connectors=["contract-db", "company-docs"],
    domain="legal",
    status=ItemStatus.public,
    visibility=Visibility.company,
    created_by="admin",
    reviewed_by="admin",
)


def ensure_seed(agents, skills) -> None:
    # Master: tạo nếu chưa có; system_prompt luôn refresh từ file.
    master_prompt = load_master_system_prompt()
    master = agents.get("master")
    if master is None:
        agents.create(
            Agent(
                name="master",
                slug="daitongquan",
                description="Đại tổng quản — tạo agent mới và điều phối khi chưa có agent phù hợp.",
                system_prompt=master_prompt,
                domain="system",
                status=ItemStatus.public,
                visibility=Visibility.company,
                created_by="admin",
                reviewed_by="admin",
            )
        )
        log.info("seed: tạo master agent (slug=daitongquan)")
    else:
        needs_update = False
        if master.system_prompt != master_prompt:
            master.system_prompt = master_prompt
            needs_update = True
            log.info("seed: cập nhật master system prompt từ master_system.md")
        if master.slug != "daitongquan":
            master.slug = "daitongquan"
            needs_update = True
            log.info("seed: cập nhật master slug → daitongquan")
        if needs_update:
            agents.update(master)

    # Demo data: chỉ khi DB rỗng (ngoài master).
    if not [a for a in agents.list() if a.name != "master"]:
        if skills.get(_SAMPLE_SKILL.name) is None:
            skills.create(_SAMPLE_SKILL.model_copy(deep=True))
        agent = _SAMPLE_AGENT.model_copy(deep=True)
        agents.create(agent)
        agents.attach_skill(agent.name, _SAMPLE_SKILL.name)
        log.info("seed: tạo agent/skill mẫu (%s @%s + %s)", agent.name, agent.slug, _SAMPLE_SKILL.name)
