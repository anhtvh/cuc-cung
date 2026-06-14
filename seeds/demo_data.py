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
Xưng **em**, gọi user là **anh/chị** — tone thân thiện, gần gũi, dễ thương như đồng nghiệp
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


def _demo(name, tagline, desc, domain, skill_name, skill_desc, skill_content, persona):
    """Tạo cặp (Skill, Agent, skill_name) cho seed demo — bypass governance (SEED-ONLY)."""
    skill = Skill(
        name=skill_name, description=skill_desc, content=skill_content, domain=domain,
        status=ItemStatus.public, created_by="admin", reviewed_by="admin",
    )
    agent = Agent(
        name=name, tagline=tagline, description=desc, system_prompt=persona,
        connectors=[], domain=domain, status=ItemStatus.public,
        visibility=Visibility.company, created_by="admin", reviewed_by="admin",
    )
    return skill, agent, skill_name


# Agent demo đa domain — chỉ để Kho Agent không trống lúc demo (D1). Persona ≥200 ký tự.
_DEMO_AGENTS = [
    _demo(
        "Bé Tài Chính", "Phân tích báo cáo & chỉ số tài chính",
        "Đọc và giải thích báo cáo tài chính, tính các chỉ số cơ bản. Dùng khi cần phân tích số liệu tài chính, đánh giá sức khỏe tài chính.",
        "finance", "finance-phan-tich-bao-cao",
        "Quy trình đọc báo cáo tài chính cơ bản.",
        "# Phân tích báo cáo tài chính\n1. Xác định loại báo cáo (KQKD, CĐKT, LCTT).\n2. Tính chỉ số: thanh khoản, đòn bẩy, sinh lời.\n3. So sánh kỳ trước & ngành.\n4. Nêu rủi ro và khuyến nghị.",
        "Bạn là trợ lý tài chính. Xưng em, gọi user là anh/chị, tone thân thiện gần gũi. "
        "Phạm vi: phân tích báo cáo tài chính, giải thích chỉ số, đánh giá sức khỏe tài chính doanh nghiệp. "
        "Ngoài tài chính (pháp lý, kỹ thuật...) thì escalate để tìm người phù hợp. "
        "Format output: trình bày theo chỉ số, có nhận xét và khuyến nghị rõ ràng. "
        "Tuyệt đối không: tư vấn đầu tư cụ thể hay cam kết lợi nhuận.",
    ),
    _demo(
        "Bé Sales", "Soạn email & kịch bản bán hàng",
        "Soạn email tiếp cận, kịch bản gọi điện, theo dõi khách hàng B2B. Dùng khi cần nội dung bán hàng, chăm sóc khách.",
        "sales", "sales-kich-ban-tiep-can",
        "Quy trình soạn nội dung tiếp cận khách hàng.",
        "# Kịch bản tiếp cận\n1. Xác định chân dung khách & nỗi đau.\n2. Mở đầu cá nhân hoá.\n3. Nêu giá trị + bằng chứng.\n4. CTA rõ ràng.\n5. Lịch follow-up.",
        "Bạn là trợ lý kinh doanh. Xưng em, gọi user là anh/chị, tone thân thiện nhiệt tình. "
        "Phạm vi: soạn email/kịch bản bán hàng, chăm sóc khách hàng, xử lý từ chối. "
        "Ngoài kinh doanh thì escalate để tìm người phù hợp. "
        "Format output: nội dung sẵn dùng (tiêu đề + thân bài + CTA). "
        "Tuyệt đối không: bịa số liệu sản phẩm, hứa hẹn sai sự thật.",
    ),
    _demo(
        "Bé Nhân Sự", "Tư vấn quy trình & chính sách HR",
        "Hỗ trợ onboarding, mô tả công việc, chính sách nhân sự nội bộ. Dùng khi hỏi về nhân sự, tuyển dụng, quy trình HR.",
        "hr", "hr-quy-trinh-onboarding",
        "Quy trình onboarding nhân viên mới.",
        "# Onboarding\n1. Chuẩn bị tài khoản & thiết bị.\n2. Giới thiệu team & văn hoá.\n3. Lộ trình 30-60-90 ngày.\n4. Checkpoint phản hồi.",
        "Bạn là trợ lý nhân sự. Xưng em, gọi user là anh/chị, tone thân thiện gần gũi. "
        "Phạm vi: onboarding, mô tả công việc, chính sách nhân sự, quy trình tuyển dụng. "
        "Ngoài nhân sự (pháp lý, tài chính...) thì escalate để tìm người phù hợp. "
        "Format output: checklist rõ ràng theo bước, có heading. "
        "Tuyệt đối không: tư vấn pháp lý lao động thay luật sư; nhắc 'cần HR xác nhận' khi nhạy cảm.",
    ),
    _demo(
        "Bé IT", "Hỗ trợ kỹ thuật & xử lý sự cố cơ bản",
        "Hướng dẫn xử lý sự cố CNTT thường gặp, tài khoản, thiết bị. Dùng khi gặp lỗi kỹ thuật, cần hỗ trợ IT.",
        "it", "it-xu-ly-su-co-co-ban",
        "Quy trình xử lý sự cố IT cơ bản.",
        "# Xử lý sự cố\n1. Ghi nhận hiện tượng & phạm vi.\n2. Kiểm tra nguyên nhân thường gặp.\n3. Hướng dẫn từng bước khắc phục.\n4. Khi không giải quyết được → chuyển bộ phận chuyên trách.",
        "Bạn là trợ lý hỗ trợ IT. Xưng em, gọi user là anh/chị, tone thân thiện kiên nhẫn. "
        "Phạm vi: xử lý sự cố CNTT thường gặp, hướng dẫn tài khoản/thiết bị/phần mềm nội bộ. "
        "Ngoài kỹ thuật thì escalate để tìm người phù hợp. "
        "Format output: hướng dẫn từng bước đánh số, dễ làm theo. "
        "Tuyệt đối không: yêu cầu user cung cấp mật khẩu; thao tác gây mất dữ liệu mà chưa cảnh báo.",
    ),
]


# Danh tính hiển thị của master (Cục cưng) — nguồn sự thật, seed tự đồng bộ mỗi lần khởi động.
_MASTER_SLUG = "cuc-cung"
_MASTER_DESCRIPTION = "Cục cưng — tạo agent mới và điều phối khi chưa có agent phù hợp."


def ensure_seed(agents, skills) -> None:
    # Master: tạo nếu chưa có; system_prompt + slug + description luôn refresh.
    master_prompt = load_master_system_prompt()
    master = agents.get("master")
    if master is None:
        agents.create(
            Agent(
                name="master",
                slug=_MASTER_SLUG,
                description=_MASTER_DESCRIPTION,
                system_prompt=master_prompt,
                domain="system",
                status=ItemStatus.public,
                visibility=Visibility.company,
                created_by="admin",
                reviewed_by="admin",
            )
        )
        log.info("seed: tạo master agent (slug=%s)", _MASTER_SLUG)
    else:
        needs_update = False
        if master.system_prompt != master_prompt:
            master.system_prompt = master_prompt
            needs_update = True
            log.info("seed: cập nhật master system prompt từ master_system.md")
        if master.slug != _MASTER_SLUG:
            master.slug = _MASTER_SLUG
            needs_update = True
            log.info("seed: cập nhật master slug → %s", _MASTER_SLUG)
        if master.description != _MASTER_DESCRIPTION:
            master.description = _MASTER_DESCRIPTION
            needs_update = True
            log.info("seed: cập nhật master description")
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

        # D1: seed thêm agent demo đa domain để Kho Agent không trống lúc demo.
        for skill, demo_agent, skill_name in _DEMO_AGENTS:
            if skills.get(skill_name) is None:
                skills.create(skill.model_copy(deep=True))
            a = demo_agent.model_copy(deep=True)
            agents.create(a)
            agents.attach_skill(a.name, skill_name)
            log.info("seed: tạo agent demo (%s @%s)", a.name, a.slug)
