/* ════════════════════════════════════════════════════════════
   demo-data.js — chỉ chạy khi URL có ?demo=1
   Mock các endpoint GET + giả lập SSE /chat để xem giao diện khi
   KHÔNG có backend. Production (/web/) không kích hoạt — vô hại.
   ════════════════════════════════════════════════════════════ */
(function () {
  if (!new URLSearchParams(location.search).has("demo")) return;

  const J = (obj, status) => Promise.resolve(new Response(JSON.stringify(obj), {
    status: status || 200, headers: { "Content-Type": "application/json" },
  }));
  const mk = (o) => Object.assign({ skills: [], connectors: [], has_pending_changes: false, visibility: "company", status: "public", calls: 0 }, o);

  const PUBLIC = [
    mk({ id: 1, name: "Bé Pháp", slug: "be-phap", domain: "legal", calls: 18, created_by: "admin", tagline: "Rà soát & thẩm định hợp đồng theo checklist Pháp chế.", description: "Thẩm định hợp đồng, đánh giá rủi ro pháp lý theo checklist 12 mục." }),
    mk({ id: 2, name: "Sale Sói", slug: "sale-soi", domain: "sales", calls: 27, created_by: "minh.tran", tagline: "Soạn pitch, theo dõi pipeline, dự báo doanh số.", description: "Hỗ trợ đội sales soạn pitch, quản lý pipeline và forecast." }),
    mk({ id: 3, name: "Thần Tài", slug: "than-tai", domain: "finance", calls: 11, created_by: "huong.le", tagline: "Phân tích ngân sách, dòng tiền và báo cáo tài chính.", description: "Đọc số liệu tài chính, lập báo cáo, phân tích dòng tiền." }),
    mk({ id: 4, name: "IT Cứu Hộ", slug: "it-cuu-ho", domain: "it", calls: 14, created_by: "admin", tagline: "Xử lý sự cố, hướng dẫn dùng công cụ nội bộ.", description: "Hỗ trợ kỹ thuật, troubleshooting, hướng dẫn tool nội bộ." }),
    mk({ id: 5, name: "Anh HR", slug: "anh-hr", domain: "hr", calls: 5, created_by: "thu.nguyen", tagline: "Giải đáp chính sách nhân sự, hỗ trợ tuyển dụng.", description: "Trả lời chính sách nhân sự, quy định nội bộ, hỗ trợ tuyển dụng." }),
    mk({ id: 6, name: "Ops Cô Ba", slug: "ops-co-ba", domain: "ops", calls: 3, created_by: "minh.tran", tagline: "Chuẩn hoá & tối ưu quy trình vận hành.", description: "Chuẩn hoá quy trình vận hành, lập SOP, theo dõi checklist." }),
  ];

  const MINE = [
    mk({ id: 21, name: "Trợ lý Báo giá", slug: "tro-ly-bao-gia", domain: "sales", status: "private", visibility: "private", created_by: "minh.tran", tagline: "Tự soạn báo giá theo bảng giá nội bộ.", description: "Soạn báo giá nhanh theo bảng giá và chính sách chiết khấu.", system_prompt: "Bạn là trợ lý báo giá. Luôn hỏi rõ số lượng và áp đúng bảng giá." }),
    mk({ id: 22, name: "Bé Thuế", slug: "be-thue", domain: "finance", status: "pending_review", created_by: "minh.tran", tagline: "Tư vấn nghiệp vụ thuế & hoá đơn.", description: "Giải đáp nghiệp vụ thuế, hoá đơn điện tử theo quy định mới nhất.", system_prompt: "Bạn là chuyên viên thuế..." }),
    mk({ id: 2, name: "Sale Sói", slug: "sale-soi", domain: "sales", status: "public", created_by: "minh.tran", calls: 27, tagline: "Soạn pitch, theo dõi pipeline, dự báo doanh số.", description: "Hỗ trợ đội sales soạn pitch, quản lý pipeline và forecast.", system_prompt: "Bạn là Sale Sói..." }),
    mk({ id: 23, name: "Bot Onboard", slug: "bot-onboard", domain: "hr", status: "rejected", visibility: "private", created_by: "minh.tran", review_note: "Cần bổ sung nguồn chính sách chính thức trước khi chia sẻ.", tagline: "Đồng hành nhân viên mới tuần đầu.", description: "Hướng dẫn nhân viên mới onboarding tuần đầu.", system_prompt: "Bạn là bot onboarding..." }),
  ];

  const PENDING = {
    agents: [Object.assign({}, MINE[1], {
      skills: [{ name: "quy-trinh-thue", status: "pending_review", version: 1, content: "# Checklist nghiệp vụ thuế\n- Kiểm tra hoá đơn đầu vào\n- Đối chiếu VAT\n- Lập tờ khai" }],
      connectors: [], dedup_candidates: [], system_prompt: "Bạn là chuyên viên thuế, trả lời theo quy định hiện hành.",
    })],
    skills: [],
  };

  const STATS = {
    counts: { agents_active: 6, skills_active: 9, users: 42 },
    tokens: { total: 1284000 },
    usage_by_agent: [
      { agent: "sale-soi", calls: 27, in_tokens: 210000, out_tokens: 142000, total_tokens: 352000 },
      { agent: "be-phap", calls: 18, in_tokens: 180000, out_tokens: 96000, total_tokens: 276000 },
      { agent: "it-cuu-ho", calls: 14, in_tokens: 90000, out_tokens: 54000, total_tokens: 144000 },
    ],
    feedback_by_agent: [
      { agent: "sale-soi", up: 22, down: 2 },
      { agent: "be-phap", up: 15, down: 1 },
      { agent: "anh-hr", up: 3, down: 2 },
    ],
  };

  const HIST = [
    { agent_name: "Bé Pháp", title: "Rà soát HĐ thuê văn phòng", last_text: "Em đã lưu ý 3 điểm rủi ro...", updated_at: Date.now() - 3600000 },
    { agent_name: "master", title: "Tạo trợ lý báo giá", last_text: "Đã tạo xong, anh thử nhé!", updated_at: Date.now() - 7200000 },
  ];

  function demoChat(opts) {
    let body = {};
    try { body = JSON.parse(opts.body || "{}"); } catch (_) {}
    const isMaster = body.agent_name === "master";
    const name = isMaster ? "master" : (body.agent_name && body.agent_name !== "null" ? body.agent_name : "Bé Pháp");
    const reply = isMaster
      ? "Chào anh/chị! Em là **Cục cưng** đây 😊\n\nAnh/chị muốn *hỏi nhanh* một việc, hay để em giúp **tạo một trợ lý riêng**? Cứ mô tả nhu cầu, em lo phần còn lại nhé."
      : "Dạ em xem qua rồi ạ. Với hợp đồng này em lưu ý **3 điểm rủi ro** chính:\n\n1. Điều khoản thanh toán chưa nêu rõ thời hạn.\n2. Thiếu điều khoản phạt vi phạm.\n3. Phạm vi bảo mật còn chung chung.\n\nAnh/chị muốn em soạn bản chỉnh sửa gợi ý không ạ?";
    const parts = reply.match(/[\s\S]{1,16}/g) || [reply];
    const enc = new TextEncoder();
    const stream = new ReadableStream({
      start(ctrl) {
        ctrl.enqueue(enc.encode("event: meta\ndata: " + JSON.stringify({ agent_name: name, agent_tagline: "", agent_description: "", agent_slug: "be-phap", routed_by: isMaster ? "explicit" : "classify", confidence: "high", note: null }) + "\n\n"));
        let i = -1;
        const tick = () => {
          i++;
          if (i < parts.length) {
            ctrl.enqueue(enc.encode("event: delta\ndata: " + JSON.stringify({ text: parts[i] }) + "\n\n"));
            setTimeout(tick, 35);
          } else {
            ctrl.enqueue(enc.encode("event: done\ndata: " + JSON.stringify({ input_tokens: 120, output_tokens: 80, stop_reason: "end_turn" }) + "\n\n"));
            ctrl.close();
          }
        };
        setTimeout(tick, 260);
      },
    });
    return Promise.resolve(new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } }));
  }

  window.fetch = function (url, opts) {
    opts = opts || {};
    const u = String(url).split("?")[0];
    if (u === "/auth/me") return J({ role: "admin", id: 1, email: "minh.tran@vng.com.vn", name: "Minh Trần", picture: null, guest_mode: true });
    if (u === "/auth/google") return J({}, 501);
    if (u === "/agents") return J(PUBLIC);
    if (u === "/agents/mine") return J(MINE);
    if (u === "/history") return J(HIST);
    if (u.indexOf("/history/") === 0) return J([]);
    if (u === "/review/pending") return J(PENDING);
    if (u === "/review/admin/stats") return J(STATS);
    if (u === "/chat") return demoChat(opts);
    if (u.indexOf("/agents/") === 0) return J(PUBLIC[0]);
    return J({});
  };
})();
