"""Mock MCP server `gitlab` (Flow 5) — bộ tool cho agent MrReviewer review Merge Request.

`is_mock=True`: dữ liệu MR (info/diff/discussion) là FIXTURE tĩnh và thao tác
post note / save review là MÔ PHỎNG — agent con Agent Hub chạy trên MaaS, không có
`glab` / GitLab API thật. Tái hiện đúng các lệnh của skill mr-review gốc:

    glab mr view   → get_mr
    glab mr diff   → get_mr_diff
    glab mr note --per-page 100 → get_mr_discussions
    glab mr note -m "..."       → post_mr_note

Riêng `save_review` ghi FILE THẬT ra thư mục reviews/ (output markdown review).

Nâng cấp sau: thay nhóm tool fixture bằng MCP server out-of-process (glab/GitLab API)
qua AgentBase Gateway — cùng interface `ToolProvider`, KHÔNG đổi flow/prompt.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.llm.base import ToolDef

log = logging.getLogger(__name__)

_REVIEWS_DIR = PROJECT_ROOT / "reviews"
_GITLAB_BASE = "https://gitlab.zalopay.vn"


# ── Fixtures: 3 MR mẫu. !101 cố tình vi phạm RC để demo agent bắt lỗi thật. ──
_SAMPLE_MRS: dict[int, dict[str, Any]] = {
    101: {
        "iid": 101,
        "project": "aqr/payment/asset-exchange-v2",
        "title": "Map provider timeout về FAILED để refund nhanh hơn",
        "author": "dev.nguyenvana",
        "source_branch": "feat/fast-refund",
        "target_branch": "master",
        "state": "opened",
        "description": (
            "## What\n"
            "Fix bug refund chậm.\n\n"
            "## How\n"
            "Tested on QC.\n"
        ),
        "diff": """\
diff --git a/internal/payment/mapping.go b/internal/payment/mapping.go
index 1a2b3c4..5d6e7f8 100644
--- a/internal/payment/mapping.go
+++ b/internal/payment/mapping.go
@@ -20,10 +20,15 @@ func MapProviderError(err error) Status {
-	if status.Code(err) == codes.DeadlineExceeded {
-		return StatusPending // outcome unknown, để reconciliation xử lý
-	}
+	// map mọi lỗi downstream thành FAILED để trigger refund ngay
+	if status.Code(err) == codes.DeadlineExceeded ||
+		status.Code(err) == codes.ResourceExhausted {
+		return StatusFailed
+	}
 	return StatusUnknown
 }

diff --git a/internal/payment/client.go b/internal/payment/client.go
index aa11bb..cc22dd 100644
--- a/internal/payment/client.go
+++ b/internal/payment/client.go
@@ -10,7 +10,7 @@ func (c *Client) Deliver(req Request) (*Resp, error) {
-	ctx, cancel := context.WithTimeout(context.Background(), c.cfg.Timeout)
-	defer cancel()
+	ctx := context.Background() // bỏ timeout cho chắc ăn
 	return c.grpc.Deliver(ctx, req)
 }
""",
        "discussions": [
            {
                "author": "reviewer.tranb",
                "created_at": "2026-06-13T09:00:00+07:00",
                "body": "Sao lại bỏ context timeout ở Deliver? Cần giải thích flow refund.",
            }
        ],
    },
    102: {
        "iid": 102,
        "project": "aqr/common/go-utils",
        "title": "Thêm helper TrimAndValidate cho input string",
        "author": "dev.lethic",
        "source_branch": "feat/trim-validate",
        "target_branch": "master",
        "state": "opened",
        "description": (
            "## Why\n"
            "Nhiều service tự viết logic trim + check empty cho field tên, dễ sai lệch.\n\n"
            "## What\n"
            "- Thêm hàm TrimAndValidate(s, min, max) trả lỗi rõ ràng.\n"
            "- Cover empty / quá dài / khoảng trắng.\n\n"
            "## How to verify\n"
            "Unit test: go test ./stringutil -run TrimAndValidate (pass, coverage 100%).\n\n"
            "## Risk\n"
            "LOW — thêm hàm mới, không đổi hàm cũ. Rollback: revert commit.\n"
        ),
        "diff": """\
diff --git a/stringutil/validate.go b/stringutil/validate.go
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/stringutil/validate.go
@@ -0,0 +1,18 @@
+package stringutil
+
+import (
+	"errors"
+	"strings"
+)
+
+// TrimAndValidate cắt khoảng trắng và kiểm tra độ dài [min, max].
+func TrimAndValidate(s string, min, max int) (string, error) {
+	s = strings.TrimSpace(s)
+	if len(s) < min {
+		return "", errors.New("giá trị quá ngắn")
+	}
+	if len(s) > max {
+		return "", errors.New("giá trị quá dài")
+	}
+	return s, nil
+}

diff --git a/stringutil/validate_test.go b/stringutil/validate_test.go
new file mode 100644
index 0000000..def5678
--- /dev/null
+++ b/stringutil/validate_test.go
@@ -0,0 +1,20 @@
+package stringutil
+
+import "testing"
+
+func TestTrimAndValidate(t *testing.T) {
+	cases := []struct{ in string; min, max int; wantErr bool }{
+		{"  hello  ", 1, 10, false},
+		{"   ", 1, 10, true},
+		{"toolongvalue", 1, 5, true},
+	}
+	for _, c := range cases {
+		_, err := TrimAndValidate(c.in, c.min, c.max)
+		if (err != nil) != c.wantErr {
+			t.Fatalf("in=%q wantErr=%v got=%v", c.in, c.wantErr, err)
+		}
+	}
+}
""",
        "discussions": [],
    },
    103: {
        "iid": 103,
        "project": "aqr/payment/wallet-core",
        "title": "Refactor wallet: drop cột legacy + đổi error code + thêm feature flag",
        "author": "dev.phamd",
        "source_branch": "hotfix/wallet-cleanup",
        "target_branch": "master",
        "state": "opened",
        "description": (
            "## What\n"
            "Bao gồm: migration drop cột balance_old, đổi error code -5009, thêm flag "
            "new_wallet, fix bug tính phí. Cần merge gấp deploy Friday trước Tết.\n"
        ),
        "diff": """\
diff --git a/migrations/0042_drop_balance_old.sql b/migrations/0042_drop_balance_old.sql
new file mode 100644
--- /dev/null
+++ b/migrations/0042_drop_balance_old.sql
@@ -0,0 +1,1 @@
+ALTER TABLE wallet DROP COLUMN balance_old;

diff --git a/internal/wallet/fee.go b/internal/wallet/fee.go
--- a/internal/wallet/fee.go
+++ b/internal/wallet/fee.go
@@ -30,7 +30,7 @@ func CalcFee(amount int64) int64 {
-	if amount > 0 && tier == TierVIP {
+	if amount > 0 || tier == TierVIP {
 		return 0
 	}
 	return amount / 100
 }
""",
        "discussions": [],
    },
}


def _parse_mr_ref(ref: str) -> int:
    """Lấy iid từ: URL đầy đủ .../-/merge_requests/101, 'group/repo!101', '!101', '101'."""
    ref = str(ref).strip()
    m = re.search(r"/merge_requests/(\d+)", ref)
    if m:
        return int(m.group(1))
    m = re.search(r"!(\d+)", ref)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\d+", ref)
    if m:
        return int(ref)
    raise ValueError(f"không parse được MR từ '{ref}' (dùng URL, group/repo!iid, hoặc iid)")


def _get_mr(ref: str) -> dict[str, Any]:
    iid = _parse_mr_ref(ref)
    mr = _SAMPLE_MRS.get(iid)
    if mr is None:
        raise ValueError(f"không tìm thấy MR !{iid} (mock chỉ có: {sorted(_SAMPLE_MRS)})")
    return mr


# ── Chế độ GIẢ LẬP (simulation) ───────────────────────────────────────────────
# Khi MR không có trong fixture (vd repo nội bộ thật như aqr/bill/provider-evnhcm),
# nghĩa là môi trường này CHƯA kết nối được GitLab nội bộ. Thay vì raise (chặn flow),
# tool trả payload báo "giả lập" để agent tự dựng MR hợp lý + review đầy đủ, và NÓI RÕ
# với user đây là kết quả mô phỏng. Note do agent post / file review vẫn lưu được.
_SIM_NOTE = (
    "MÔI TRƯỜNG GIẢ LẬP — chưa kết nối được GitLab nội bộ (gitlab.zalopay.vn). "
    "Không có MR thật để fetch. Hãy NÓI RÕ với user đây là kết quả MÔ PHỎNG, tự giả "
    "lập một MR hợp lý cho repo này (mục đích thay đổi + diff điển hình của loại repo đó) "
    "rồi review đầy đủ theo checklist RC/IM/GP — nêu cả điểm được lẫn chưa được."
)


def _try_parse_mr_ref(ref: str) -> int | None:
    """Như `_parse_mr_ref` nhưng trả None thay vì raise (ref không có iid → giả lập)."""
    try:
        return _parse_mr_ref(ref)
    except ValueError:
        return None


def _project_from_ref(ref: str) -> str:
    """Đoán đường dẫn repo (group/.../name) từ ref để hiển thị/đặt tên file giả lập."""
    ref = str(ref).strip()
    m = re.search(r"gitlab\.[\w.]+/(.+?)(?:/-/|$)", ref)  # URL: .../<path>/-/merge_requests...
    if m:
        return m.group(1).rstrip("/")
    m = re.match(r"([\w\-./]+)!\d+", ref)  # group/repo!iid
    if m:
        return m.group(1)
    if "/" in ref and not ref.lstrip().startswith("http"):  # 'group/repo' trần
        return ref.rstrip("/")
    return "(không rõ repo)"


def _review_key(ref: str, iid: int | None) -> str:
    """Khóa đặt tên file review: mr_{iid} nếu có iid, else slug hóa từ repo path."""
    if iid is not None:
        return f"mr_{iid}"
    slug = re.sub(r"[^\w\-]+", "_", _project_from_ref(ref)).strip("_") or "sim"
    return f"mr_{slug}"


class GitlabProvider:
    server_name = "gitlab"
    is_mock = True

    def __init__(self) -> None:
        # Note do agent post được lưu in-memory (sống theo vòng đời app) — demo append vào MR.
        self._posted_notes: dict[int, list[dict[str, Any]]] = {}

    def list_tools(self) -> list[ToolDef]:
        _ref_schema = {
            "type": "object",
            "properties": {
                "mr": {
                    "type": "string",
                    "description": "MR link đầy đủ, hoặc group/repo!iid, hoặc số iid (vd 101).",
                }
            },
            "required": ["mr"],
        }
        return [
            ToolDef(
                name="get_mr",
                description=(
                    "(MÔ PHỎNG) Lấy thông tin MR: title, description, author, branch, state. "
                    "Tương đương `glab mr view`. Gọi đầu tiên để hiểu ngữ cảnh + check template."
                ),
                input_schema=_ref_schema,
            ),
            ToolDef(
                name="get_mr_diff",
                description=(
                    "(MÔ PHỎNG) Lấy toàn bộ diff của MR (tương đương `glab mr diff`). "
                    "Đọc HẾT diff trước khi review — miss phần cuối dễ bỏ sót lỗi."
                ),
                input_schema=_ref_schema,
            ),
            ToolDef(
                name="get_mr_discussions",
                description=(
                    "(MÔ PHỎNG) Lấy các discussion/note hiện có của MR (tương đương "
                    "`glab mr note --per-page 100`). Đọc để tránh raise trùng, check fix cũ."
                ),
                input_schema=_ref_schema,
            ),
            ToolDef(
                name="post_mr_note",
                description=(
                    "(MÔ PHỎNG) Post comment review lên MR (tương đương `glab mr note -m`). "
                    "Gọi sau khi đã review xong. Trả note id giả lập."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "mr": {"type": "string", "description": "MR link / group/repo!iid / iid."},
                        "body": {"type": "string", "description": "Nội dung comment markdown."},
                    },
                    "required": ["mr", "body"],
                },
            ),
            ToolDef(
                name="save_review",
                description=(
                    "(THẬT) Lưu nội dung review ra file markdown reviews/mr_{iid}.md và trả path. "
                    "Gọi cùng với post_mr_note để có bản file của review."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "mr": {"type": "string", "description": "MR link / group/repo!iid / iid."},
                        "content": {"type": "string", "description": "Nội dung review markdown."},
                    },
                    "required": ["mr", "content"],
                },
            ),
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> str:
        ref = args.get("mr", "")
        iid = _try_parse_mr_ref(ref)
        simulated = _SAMPLE_MRS.get(iid) is None  # MR không có trong fixture → giả lập

        if tool_name == "get_mr":
            if simulated:
                # Không fetch được MR thật → báo agent chuyển sang giả lập.
                return json.dumps(
                    {
                        "simulation": True,
                        "fetched": False,
                        "ref": ref,
                        "iid": iid,
                        "project": _project_from_ref(ref),
                        "note": _SIM_NOTE,
                    },
                    ensure_ascii=False,
                )
            mr = _get_mr(ref)
            return json.dumps(
                {
                    "iid": mr["iid"],
                    "project": mr["project"],
                    "title": mr["title"],
                    "author": mr["author"],
                    "source_branch": mr["source_branch"],
                    "target_branch": mr["target_branch"],
                    "state": mr["state"],
                    "description": mr["description"],
                    "web_url": f"{_GITLAB_BASE}/{mr['project']}/-/merge_requests/{mr['iid']}",
                    "note": "MÔ PHỎNG — fixture tĩnh, không phải MR thật",
                },
                ensure_ascii=False,
            )

        if tool_name == "get_mr_diff":
            if simulated:
                return json.dumps(
                    {
                        "simulation": True,
                        "fetched": False,
                        "ref": ref,
                        "project": _project_from_ref(ref),
                        "note": _SIM_NOTE + " Tự dựng một diff điển hình cho repo này để review.",
                    },
                    ensure_ascii=False,
                )
            return _get_mr(ref)["diff"]

        if tool_name == "get_mr_discussions":
            if simulated:
                return json.dumps(
                    {"discussions": [], "simulation": True, "note": _SIM_NOTE},
                    ensure_ascii=False,
                )
            mr = _get_mr(ref)
            existing = list(mr["discussions"]) + self._posted_notes.get(mr["iid"], [])
            return json.dumps({"discussions": existing}, ensure_ascii=False)

        if tool_name == "post_mr_note":
            body = str(args.get("body", "")).strip()
            if not body:
                raise ValueError("body rỗng — không có nội dung để post")
            if simulated:
                # Không có MR thật để post → mô phỏng thao tác, không gắn vào fixture nào.
                project = _project_from_ref(ref)
                return json.dumps(
                    {
                        "note_id": "sim",
                        "mr_ref": ref,
                        "project": project,
                        "simulation": True,
                        "note": "GIẢ LẬP — chưa kết nối GitLab nội bộ nên không post note thật.",
                    },
                    ensure_ascii=False,
                )
            mr = _get_mr(ref)
            note = {
                "author": "MrReviewer",
                "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
                "body": body,
            }
            self._posted_notes.setdefault(mr["iid"], []).append(note)
            note_id = sum(len(v) for v in self._posted_notes.values())
            return json.dumps(
                {
                    "note_id": note_id,
                    "mr_iid": mr["iid"],
                    "url": f"{_GITLAB_BASE}/{mr['project']}/-/merge_requests/{mr['iid']}#note_{note_id}",
                    "note": "MÔ PHỎNG — chưa post note thật lên GitLab",
                },
                ensure_ascii=False,
            )

        if tool_name == "save_review":
            content = str(args.get("content", "")).strip()
            if not content:
                raise ValueError("content rỗng — không có nội dung review để lưu")
            # File review LUÔN lưu thật, kể cả khi MR là giả lập (key = iid hoặc slug repo).
            key = _review_key(ref, iid)
            _REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
            path = _REVIEWS_DIR / f"{key}.md"
            path.write_text(content, encoding="utf-8")
            log.info("save_review: ghi review %s ra %s (simulation=%s)", key, path, simulated)
            return json.dumps(
                {
                    "saved": True,
                    "path": str(path),
                    "mr_iid": iid,
                    "simulation": simulated,
                },
                ensure_ascii=False,
            )

        raise ValueError(f"tool không tồn tại: {tool_name}")
