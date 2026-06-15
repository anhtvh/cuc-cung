# Phase 4 — Test

**Goal:** Build the adapter, run tests, generate a test report, push everything, and open a GitLab MR.

---

## Step 1: Read state

Read `input/state.json` → `local_path`, `repo_url`, `partner_name`, `decisions`.
Read `input/phase3_checkpoint.md` if it exists — it has a concise summary of what Phase 3 did without requiring you to re-read source files.
Read `docs/test-cases.md` → expected pass/fail for each test case.

---

## Step 2: Vet + Build

```bash
# Vet first — catches real bugs go build misses
go vet ./... 2>&1 | head -20

# Build
go build ./... 2>&1 | grep -E "^#|error:" | head -30
```

If vet or build fails:
1. Read **only the failing file** — not the whole codebase.
2. Fix the error.
3. Re-run until both commands produce empty output.
4. Push fixes:
   ```bash
   cd {local_path}
   git add -A
   git commit -m "fix: resolve build errors"
   git push origin {feature_branch}
   ```

Do not proceed to testing until both vet and build output are empty.

---

## Step 3: Test

```bash
# Summary view — one line per package (ok/FAIL + coverage %)
go test ./... -cover -race 2>&1 | grep -E "^(ok|FAIL|---)" | head -60
```

If any package FAILs, get details for that package only:
```bash
go test ./{failing_package}/... -v -cover -race 2>&1 | tail -60
```

Do not run `go test ./... -v` on the full repo — the verbose output of all packages is too large.

Extract:
- Total tests: passed / failed / skipped
- Coverage per package (run `go test ./... -cover` separately if needed)
- Race condition warnings
- Any panics

---

## Step 4: Cross-reference with test cases

Compare actual results against `docs/test-cases.md`:
- For each test case in the table: did the corresponding test pass?
- Mark each row: ✅ passed / ❌ failed / ⚠️ no test written yet

---

## Step 4b: Build verification checklist items

From the cross-reference above, record coverage status for each test case:
- ✅ covered — test written and passing
- ❌ failing — test written but fails
- ⚠️  missing — no test written (LOW confidence — behavior unverified)

Compute:

```
Test case coverage:
  Covered : N / N_total
  Failing : N
  Missing : N  → (LOW confidence — implementation behavior unverified)
```

Append missing coverage to `docs/open-questions.md`:

```markdown
---
## Assumptions logged — Phase 4 ({RFC3339 timestamp})

### Missing test coverage (LOW confidence)
{for each ⚠️ test case}
- **`{test_case_id}`**: No automated test written. Behavior of `{code path}` is unverified.
```

---

## Step 5: Integration tests (optional)

Read `config.yaml`. If `sandbox_base_url` is non-empty:
- Note that integration tests can be run against the sandbox.
- Do NOT automatically call the sandbox — ask the human first.
- If the human confirms, run the integration test suite (if one exists) or advise how to write it.

If `sandbox_base_url` is empty: note "Integration tests skipped — no sandbox URL in config."

---

## Step 6: Generate test report files

### `docs/test-results.md`

```markdown
# Test Results — provider-{partner_name}

**Date:** {timestamp}
**Commit:** {git commit SHA}

## Summary

| | Count |
|---|---|
| Total tests | {n} |
| Passed | {n} |
| Failed | {n} |
| Skipped | {n} |

## Coverage by package

| Package | Coverage |
|---|---|
| internal/provider | XX% |
| internal/business/manager/{type} | XX% |
| internal/constant | XX% |

## Test case coverage

| Test case | Result |
|---|---|
| GetBill — success | ✅ |
| ... | ... |

## Integration tests
{Passed / Skipped with reason / Failed with details}
```

### `docs/known-issues.md`

For each failed test or build error:
```markdown
## Known Issues

### {test name or build error}
**Status:** Failed
**Error:** {exact error message}
**Root cause:** {your analysis}
**Suggested fix:** {concrete recommendation}
```

If all tests pass: "No known issues."

---

## Step 6b: Generate QC test case file

Generate `docs/qc-test-cases.md` — a manual test-case document the QC team runs as-is.

**Match the format the QC team already uses.** The canonical reference is
`agent/context/qc-test-case-reference.md` (a real QC sheet for a bill-payment provider —
**read it before generating**). The generated file MUST follow it:

- One main table with these **exact columns**:
  `| ID | Type | Summary | Steps | Expected Result | Status Dev | Status QC | NOTE |`
- Written in Vietnamese business language, from the **buyer's app flow** — NOT from API
  call names. QC does not "call GetBill"; QC does: *Choose provider → Chọn supplier →
  Input customer code → (Nhập số tiền khác) → Click Thanh toán → màn Cashier →
  Click Xác nhận → check notification / transaction history*.
- `Type`: leave blank for functional UI cases | `Integration` (needs real provider/sandbox
  or backend round-trip) | `Source of fun (SOFs)`.
- `Expected Result`: concrete UI behavior, **plus** the zalopay return code where one
  surfaces, **plus** the error dialog copy (Title / Des / CTA) when an error is shown to
  the user — mirror the style of reference rows (e.g. error `-554` → Title *Không tìm thấy
  hóa đơn*, Des, CTA **Đóng**).
- `Status Dev` / `Status QC`: leave **blank** — QC fills these during execution.
- `NOTE`: flag items needing confirmation or special test env (mock timeout, multi-invoice
  support, push-notification feature, reconciliation with provider…).

This is **distinct** from `docs/test-cases.md` (developer unit-test table with Go constants).

### Source inputs
- `input/partner_schema.json` → field names, error codes, types, min amount, business rules
- `input/state.json` → partner name, service IDs
- `docs/test-results.md` (just written) → which cases already have automated coverage
- `agent/context/qc-test-case-reference.md` → canonical QC format & baseline scenarios

### Mandatory coverage — adapt each to this partner from the schema

Do not drop any category below. Generate at least the listed cases, then add one row per
applicable `schema.error_codes` entry. Mark backend/integration-only ones as `Integration`.
If a case is app/UI-only and the adapter can't drive it, still include it for manual QC and
note it in `NOTE`.

**A. Query bill (tra cứu hoá đơn)**
- Query FAIL — sai customer code → zalopay code (e.g. `-554`) + dialog Title/Des/CTA
- Query thành công — có nợ trong kỳ
- Query — chưa tới kỳ nợ (nếu provider hỗ trợ)
- Query — khách hàng không có nợ / zero debt → không cho thanh toán (`Integration`)
- Query — nhiều kỳ nợ / multiple invoices → tổng tiền đúng (`Integration`, NOTE: confirm UI)
- Query — timeout provider không phản hồi → dialog timeout + retry (`Integration`)
- Input validation — để trống mã KH → button disabled / inline error
- Input validation — ký tự đặc biệt / khoảng trắng → chặn hoặc báo lỗi định dạng

**B. UI hiển thị hoá đơn**
- Logo + bill example đúng supplier
- Thứ tự bill detail đúng define (Thông tin thanh toán / Thông tin khách hàng)
- Description tại màn Cashier đúng define
- Field mapping: raw API response vs UI (tên KH, mã hợp đồng, số tiền, kỳ hạn) — `Integration`

**C. Số tiền / "Nhập số tiền khác"** (chỉ khi schema/business rule cho phép partial)
- Nhập `< min_amount` → alert *"Cần tối thiểu {{min_amount}} để thực hiện giao dịch"*
- Nhập `>= min_amount` → cho phép thanh toán
- Partial payment → số tiền còn lại = total − số vừa thanh toán

**D. Thanh toán (PayBill) + Cashier**
- Thanh toán thành công → notification + transaction history "thành công" (`Integration`)
- Số dư ví không đủ → báo lỗi, KHÔNG tạo giao dịch, không gạch nợ
- SOFs trên cashier / gateways / autodebit hiển thị đúng (`Type = Source of fun (SOFs)`)

**E. Sau thanh toán / đối soát (CheckPay, reconciliation)** — `Integration`
- Query lại sau payment → dư nợ còn lại = total − đã thanh toán
- Trùng `trans_id` / idempotency → `-400` DeliverManualCheck, không gọi partner lần 2
- Trạng thái không xác định từ partner → `-400`, không tự hoàn tiền

**F. Entry point**
- Deep link / notification → mở đúng màn bill detail của provider (NOTE: nếu có feature)

### File structure

```markdown
# QC Test Cases — provider-{partner_name}

> Tài liệu cho QC chạy tay. Format theo chuẩn QC team (test_cases_bill_payment.md).
> Môi trường: {sandbox_url from config.yaml, or "Chưa có sandbox URL — cần xác nhận với partner"}
> Service IDs: {list from state.json}
> Ngày tạo: {date}

| ID | Type | Summary | Steps | Expected Result | Status Dev | Status QC | NOTE |
|----|------|---------|-------|-----------------|-----------|-----------|------|
| 1 |  | Query bill FAIL — sai customer code | 1. Choose provider {partner} 2. Chọn supplier 3. Input customer code **sai** 4. Check result | Query FAIL. **Error code:** `{code}` **Dialog:** Title: *...* / Des: *...* / CTA: **Đóng** |  |  |  |
| 2 |  | Check UI bill input (logo, bill example) | 1. Choose provider 2. Check logo + bill example | Logo đúng supplier, bill example hiển thị đúng |  |  |  |
| ... | Integration | ... | ... | ... |  |  | ... |

---

## Lưu ý cho QC

- **DeliverManualCheck (-400):** GD cần đối soát thủ công — zalopay KHÔNG tự hoàn tiền.
- **Idempotency:** cùng `trans_id` gọi 2 lần → kết quả giống nhau, không gọi partner lần 2.
- **Phạm vi adapter:** unit test tự động chỉ phủ hành vi backend/API. Các case UI (logo,
  bill detail, cashier, deep link, notification) cần QC chạy tay trên app.
- **Automated coverage:** {list TC IDs already covered by unit tests from test-results.md}
```

### Rules for filling sample data
- `customer_code`, `trans_id`, `reference_code`: realistic fake values matching the field's
  format from schema (numeric if partner uses numeric IDs, alphanumeric otherwise)
- Amount values: round VND numbers (e.g. 150000, 320000) — never 0 or negative; use real
  `min_amount` from schema for the validation cases
- Service codes: actual service IDs from `state.json`
- Dialog copy: reuse the partner's real message from the docs if present; otherwise write a
  sensible Vietnamese message and flag it in `NOTE` as "cần confirm với team UI"
- Do NOT use real customer codes or transaction IDs — illustrative only

Add one row per entry in `schema.error_codes`, mapped to the QC-visible behavior (which
endpoint surfaces it, zalopay code, dialog copy if shown to the user).

### Appendix — API-level return-code reference (dev ↔ QC cross-check)

After the QC table, append a collapsed reference mapping each provider error code to the
zalopay constant per endpoint (GetBill→MapQueryStatusCode, PayBill/CheckPay→MapPaymentStatusCode),
so dev and QC can reconcile a UI symptom back to the internal code. One row per
`schema.error_codes` entry.

---

## Step 6c: Generate `docs/verification-checklist.md`

Overwrite `docs/verification-checklist.md` with the Phase 4 checklist:

```markdown
# Verification Checklist — Phase 4: Test

Generated: {RFC3339 timestamp}
Commit: {git_sha}

## Auto-Verified by Agent
- [x] `go vet ./...`: clean
- [x] `go build ./...`: {✅ zero errors / ❌ N errors}
- [x] `go test ./... -cover -race`: {passed}/{total} passed
- [x] Race detector: {✅ clean / ⚠️ N warnings}
- [x] Test case cross-reference: {n_covered}/{n_total} cases covered
- [x] `docs/test-results.md` generated
- [x] `docs/known-issues.md` generated
- [x] `docs/qc-test-cases.md` generated ({n} test cases)
- [x] All files pushed to `feat/integrate-{partner_name}`

## Requires Human Review
{for each ⚠️ missing test case from Step 4b}
- [ ] [LOW] Test case `{id}` (`{scenario}`) has no automated test — verify manually.

{for each known issue in docs/known-issues.md}
- [ ] [ISSUE] {test or build name}: {root cause summary}

## BLOCKING — Must Resolve Before MR
{if no failures and no missing critical tests: "None."}
{if test failures: list them}
```

---

## Step 7: Push all

```bash
cd {local_path}
git add -A
git commit -m "test: add test results, known issues and QC test cases"
git push origin feat/integrate-{partner_name}
```

Update `input/state.json`:
```json
{
  "phase": 4,
  "build_status": "passing",
  "last_commit": "{git commit SHA}"
}
```

Write `input/phase4_checkpoint.md`:
```markdown
# Phase 4 Checkpoint

## Results
- Build    : ✅ clean
- Tests    : {passed}/{total} passed
- Race     : ✅ clean / ⚠️ issues (see known-issues.md)
- Coverage : ~{n}% overall

## Confidence (test coverage)
- Covered  : {n_covered}/{n_total} test cases  ✅
- Missing  : {n_missing} cases  ⚠️
- Issues   : {n_issues}

## MR
- URL: {mr_url or "pending"}

## Known issues
{list or "none"}
```

---

## Step 8: Generate MR description

Use the MR description template from `agent/context/zalopay-provider-pattern.md` (section "MR description template").
Fill in all placeholders with actual values from the test results and schema.

---

## Step 9: Create the MR

Ask the human first:

```
All done. Create a GitLab MR now?
  Source branch : feat/integrate-{partner_name}
  Target branch : master
  Title         : feat: integrate {partner_name} adapter
```

If the human confirms:

```bash
MR_URL=$(glab mr create \
  --repo {namespace}/provider-{partner_name} \
  --source-branch feat/integrate-{partner_name} \
  --target-branch master \
  --title "feat: integrate {partner_name} adapter" \
  --description "$(cat <<'EOF'
{generated description from Step 8}
EOF
)" 2>&1 | grep "https://")

echo "MR: $MR_URL"
```

Update `input/state.json` → `"mr_url": "<MR URL>"`.
Update `input/phase4_checkpoint.md` → set MR URL.

---

## Human Checkpoint #4

Compute confidence totals (missing test coverage from Step 4b + known issues from `docs/known-issues.md`).
Then follow the branching logic — **stop after presenting the appropriate message**.

---

### Branch A: Test failures — BLOCKED

Present this and **do not ask for confirmation**:

```
Phase 4 complete — BLOCKED ✗

Build : {✅ / ❌}
Tests : {passed}/{total}  ❌ {n_failing} failing

Verification checklist: docs/verification-checklist.md

🚫 BLOCKED — test failures must be fixed before creating an MR.
Failing tests:
{list from docs/known-issues.md}
```

---

### Branch B: All passing

Present this and **stop**:

```
Phase 4 complete ✓

Build   : ✅ clean
Tests   : {passed}/{total} passed  (coverage: ~{n}%)
Race    : ✅ clean  /  ⚠️ issues (see docs/known-issues.md)
Integration: ✅ passed  /  ⚠️ skipped (no sandbox URL)

Confidence summary:
  Test cases covered : {n_covered}/{n_total}  ✅
  Missing coverage   : {n_missing} cases  ⚠️
  Known issues       : {n_issues}

Verification checklist: docs/verification-checklist.md

{if n_missing > 0}
⚠️  {n_missing} test case(s) lack automated coverage — manual QC recommended.

QC deliverables committed:
  docs/qc-test-cases.md  — {n} test cases across GetBill / PayBill / CheckPay
  docs/test-results.md
  docs/known-issues.md

MR created: {mr_url}

The adapter is ready for Tech Lead review.
```
