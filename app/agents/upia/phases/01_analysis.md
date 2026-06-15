# Phase 1 — Analysis

**Goal:** Parse partner API docs → produce a structured JSON schema → generate 7 markdown files in `docs/`.

---

## Step 1: Extract docs

Tài liệu API của đối tác do user **upload** (PDF/DOCX/TXT) — Agent Hub đã trích sẵn
thành text và đính vào hội thoại dưới dạng `attachment`. **Đọc thẳng nội dung text đó**;
KHÔNG có MCP tool `parse_docs` hay thư mục `input/docs/` trong môi trường này.

Nếu user CHƯA upload tài liệu: dừng và yêu cầu user upload file API trước khi phân tích.

---

## Step 2: Build the JSON schema

Analyze the extracted content and produce the following structure.
Save it to `input/partner_schema.json` so it can be reused in later phases.

```json
{
  "partner": "<partner_name from config.yaml>",
  "base_url": "<API base URL>",
  "auth": {
    "type": "<apikey | basic | hmac | rsa | oauth2 | none>",
    "header": "<header name if API key>",
    "username_field": "<field name if basic auth>",
    "password_field": "<field name if basic auth>",
    "signature_fields": "<fields joined for HMAC/RSA, e.g. 'action#username#password#trans_id'>",
    "oauth2": {
      "token_url": "<endpoint to exchange refresh_token for access_token — if type=oauth2>",
      "refresh_token_field": "<request field name carrying the refresh token>",
      "access_token_field": "<response field name carrying the access token>",
      "access_token_ttl_hours": 0,
      "early_refresh_margin_hours": 1
    },
    "notes": "<anything unusual about auth>"
  },
  "endpoints": [
    {
      "name": "<human-readable name>",
      "method": "<GET | POST>",
      "path": "<path relative to base_url>",
      "purpose": "<GetBill | PayBill | CheckPay | CheckBalance>",
      "content_type": "<application/json | application/x-www-form-urlencoded | ...>",
      "request_fields": [
        {
          "name": "<field name>",
          "type": "<string | int | bool | float>",
          "required": true,
          "description": "<what it means>"
        }
      ],
      "response_fields": [
        {
          "name": "<field name>",
          "type": "<string | int | bool | float>",
          "description": "<what it means>"
        }
      ]
    }
  ],
  "error_codes": [
    {
      "code": "<provider error code>",
      "description": "<what it means>",
      "retryable": false,
      "maps_to": "<internal constant — see mapping rules below>"
    }
  ],
  "ambiguities": [
    "<anything unclear, missing, or contradictory in the docs>"
  ]
}
```

### Error code mapping rules

For the full list of zalopay internal constants, see `agent/context/zalopay-provider-pattern.md`.

When filling `maps_to` for each error code:

- **Query endpoints (GetBill):** partner success code → `ProviderSuccess`. All other codes → pick the most specific constant that fits (see context file), default `ProviderErrorCodeNotDefined`.
- **Payment endpoints (PayBill, CheckPay):** partner success code → `DeliverSuccess`. **Everything else → `DeliverManualCheck` (-400)**. No exceptions for the default case.

---

## Step 2b: Annotate schema fields with confidence scores

**Read `agent/context/observability-protocol.md`** for the annotation format.

For every extracted value in the schema, add five metadata keys:
- `_confidence`: `HIGH` | `LOW` | `CONFLICT`
- `_source`: document name, page, section (or `null` if not found)
- `_quote`: exact excerpt supporting the value (or `null`)
- `_assumption`: what the agent inferred and why (LOW only, else `null`)
- `_conflict_detail`: description of the contradiction (CONFLICT only, else `null`)

Fields to annotate:
- `base_url`, all `auth.*` subfields (including all OAuth2 config)
- Per endpoint: `path`, `method`, `content_type`, every request/response field name/type/required flag
- Every error code: `code`, `description`, `retryable`, `maps_to`

After annotating, compute and record totals:

```
Confidence totals:
  HIGH    : N
  LOW     : N  → [list field names]
  CONFLICT: N  → [list field names]
```

Save the annotated schema to `input/partner_schema.json` (overwrite in place).

---

## Step 3: Generate `docs/` files

Create a `docs/` directory and produce these 7 files:

### `docs/requirements.md`
- All endpoints: method, path, purpose
- All request/response fields with types and descriptions
- Business rules from the docs (min amount, supported services, partial payment, etc.)

### `docs/api-analysis.md`
- Auth flow diagram (ASCII)
- Request/response examples for each endpoint
- Edge cases: empty bill list, multiple bills, partial payment, duplicate transaction
- Anything the docs are silent about (flag as "needs confirmation with partner")

### `docs/open-questions.md`
- All items from `ambiguities` in the schema
- Additional questions raised during analysis:
  - Date format? (YYYY-MM-DD vs DD/MM/YYYY?)
  - Amount unit? (VND or xu?)
  - Partner-side timeout/retry policy?
  - What happens on duplicate `trans_id`?

### `docs/impact.md`
Map each schema element to the Go file it will affect:
- `constant/provider.go` — list every error code that needs a case in the switch
- `entity/provider/provider.go` — list the request/response structs to create
- `provider/client.go` — auth type and endpoint call structure
- `business/manager/{type}/service.go` — converter logic to implement

### `docs/action-plan.md`
Ordered task list for Phase 3:
1. Write error code constants and mapping functions (`constant/provider.go`)
2. Write request/response structs (`entity/provider/provider.go`)
3. Write provider HTTP DTOs (`provider/dto.go`)
4. Write HTTP client with auth (`provider/client.go`)
5. Write converter strategy (`business/manager/{type}/service.go`)
6. Update config struct (`config/config.go`)
7. Update YAML config files

### `docs/test-plan.md`
Testing strategy:
- **Unit tests:** every public method of the `Provider` interface, table-driven
- **Error mapping coverage:** `MapQueryStatusCode` and `MapPaymentStatusCode` must test ALL error codes from the schema, including the default/unknown case
- **Mock:** use `mockgen` on `httpclient.Client` so tests don't make real HTTP calls
- **Integration tests:** only if `sandbox_base_url` is set in config
- **Race detector:** run with `-race` flag

### `docs/test-cases.md`
Detailed test cases table:

| Test | Input | Expected result |
|---|---|---|
| GetBill — success | valid customer code | `ProviderSuccess`, bill list populated |
| GetBill — not found | unknown code | `ProviderCustomerCodeNotExist` |
| GetBill — unavailable | HTTP 500 | `ProviderUnavailable` |
| GetBill — empty | customer exists, no bills | `ProviderBillEmpty` |
| PayBill — success | valid request | `DeliverSuccess` |
| PayBill — manual check | ambiguous status | `DeliverManualCheck` |
| PayBill — duplicate | same trans_id | `DeliverManualCheck` |
| CheckPay — success | known trans_id | `DeliverSuccess` |
| MapPaymentStatusCode — unknown code | `"XYZ"` | `DeliverManualCheck` |
| MapQueryStatusCode — unknown code | `"XYZ"` | `ProviderErrorCodeNotDefined` |

Add one row per error code listed in `schema.error_codes`.

---

## Step 3b: Generate `docs/source-map.md`

Build the source map from confidence annotations in `input/partner_schema.json`.
Sort rows: CONFLICTs first, then LOW, then HIGH.

```markdown
# Source Map — {partner_name}

Generated: {RFC3339 timestamp}

| Field / Decision | Document | Page / Section | Quote | Confidence |
|---|---|---|---|---|
| `auth.signature_fields` | api-guide.pdf | Page 3 AND Page 8 | "fields: A,B" vs "sign: A,B,C" | CONFLICT |
| `amount_unit` | — | — | Not found in docs | LOW |
| `base_url` | api-guide.pdf | Page 2, Section 1.0 | "Base URL: https://..." | HIGH |
```

One row per annotated leaf field in the schema.

---

## Step 3c: Append assumptions to `docs/open-questions.md`

Append this section (never overwrite the file):

```markdown
---
## Assumptions logged — Phase 1 ({RFC3339 timestamp})

### LOW confidence items (agent assumptions)
{for each LOW field in the schema}
- **`{field}`**: {_assumption}. _Confirm with partner before go-live._

### CONFLICT items (must resolve before Phase 2)
{for each CONFLICT field in the schema}
- **`{field}`**: {_conflict_detail}
  - Source A: "{quote}" ({doc}, {page})
  - Source B: "{quote}" ({doc}, {page})
```

If no LOW or CONFLICT items exist: append "No assumptions or conflicts logged in Phase 1."

---

## Step 3d: Generate `docs/verification-checklist.md`

Overwrite `docs/verification-checklist.md` with the Phase 1 checklist:

```markdown
# Verification Checklist — Phase 1: Analysis

Generated: {RFC3339 timestamp}

## Auto-Verified by Agent
- [x] `input/partner_schema.json` saved ({n} endpoints, {n} error codes)
- [x] All endpoints have: method, path, purpose, content_type
- [x] All error codes have `maps_to` assigned
- [x] 7 docs/ files generated
- [x] `docs/source-map.md` generated ({n_total} entries: {n_high} HIGH / {n_low} LOW / {n_conflict} CONFLICT)
- [x] `docs/open-questions.md` appended with Phase 1 assumptions

## Requires Human Review
{for each LOW field}
- [ ] [LOW] `{field}`: Assumed "{_assumption}". Confirm correct value.

{for each CONFLICT field}
- [ ] [CONFLICT] `{field}`: {_conflict_detail} — must resolve before Phase 2.

## BLOCKING — Must Resolve Before Phase 2
{if CONFLICT_COUNT == 0: write "None."}
{if CONFLICT_COUNT > 0: one bullet per CONFLICT field}
- [ ] `{field}`: {_conflict_detail}
```

---

## Step 4: Save state

Write `input/state.json`:

```json
{
  "phase": 1,
  "partner_name": "<from config.yaml>",
  "started_at": "<RFC3339 timestamp>",
  "repo_url": "",
  "repo_ssh_url": "",
  "local_path": "",
  "feature_branch": "",
  "schema": "input/partner_schema.json",
  "docs_generated": [
    "requirements.md", "api-analysis.md", "open-questions.md",
    "impact.md", "action-plan.md", "test-plan.md", "test-cases.md"
  ],
  "service_ids": [],
  "mr_url": "",
  "build_status": "",
  "last_commit": "",
  "confidence_totals": {
    "high": 0,
    "low": 0,
    "conflict": 0
  },
  "decisions": {
    "auth_type": "",
    "delete_list": [],
    "test_files_to_rewrite": [],
    "mock_files_to_update": [],
    "open_questions_resolved": 0,
    "open_questions_pending": 0,
    "impl_decisions": []
  }
}
```

Write `input/phase1_checkpoint.md`:
```markdown
# Phase 1 Checkpoint

## Schema summary
- Partner   : {partner_name}
- Base URL  : {base_url}
- Auth type : {auth_type}
- Endpoints : {n} — {list names}
- Error codes: {n}

## Confidence totals
- HIGH    : {n}
- LOW     : {n}  → [list field names, or "none"]
- CONFLICT: {n}  → [list field names, or "none"]

## Open questions
{copy list from open-questions.md}

## Docs generated
requirements.md, api-analysis.md, open-questions.md, impact.md, action-plan.md, test-plan.md, test-cases.md
```

---

## Human Checkpoint #1

Compute confidence totals from the `_confidence` annotations in `input/partner_schema.json`.
Then follow the branching logic — **stop after presenting the appropriate message**.

---

### Branch A: CONFLICT_COUNT > 0 — BLOCKED

Present this message and **do not ask for confirmation**:

```
Phase 1 complete — BLOCKED ✗

Confidence summary:
  HIGH    : {HIGH_COUNT} fields  ✅
  LOW     : {LOW_COUNT} fields   ⚠️
  CONFLICT: {CONFLICT_COUNT} fields  🚫

Verification checklist: docs/verification-checklist.md

🚫 BLOCKED — {CONFLICT_COUNT} conflict(s) must be resolved before proceeding to Phase 2.

{for each CONFLICT field}
CONFLICT [{i}]: `{field}`
  Source A: "{quote}" ({doc}, {page})
  Source B: "{quote}" ({doc}, {page})
  → Please provide the correct value.

Once all conflicts are resolved, run these steps in order:
1. Update `input/partner_schema.json` — correct the value, set `_confidence` to `HIGH`.
2. Re-run **Step 2b** — recompute confidence totals.
3. Re-run **Step 3b** — regenerate `docs/source-map.md` from scratch.
4. Re-run **Step 3c** — re-append to `docs/open-questions.md` (remaining unresolved items only).
5. Re-run **Step 3d** — regenerate `docs/verification-checklist.md`.
6. Update `confidence_totals` in `input/state.json`.
Then re-evaluate which branch (A, B, or C) applies and present the appropriate message.
```

---

### Branch B: CONFLICT_COUNT == 0, LOW_COUNT > 0 — confirm assumptions

Present this and **stop after collecting answers**:

```
Phase 1 complete ✓

Confidence summary:
  HIGH    : {HIGH_COUNT} fields  ✅
  LOW     : {LOW_COUNT} fields   ⚠️
  CONFLICT: 0  ✅

Verification checklist: docs/verification-checklist.md

Generated docs/:
  ├── requirements.md
  ├── api-analysis.md
  ├── open-questions.md   (updated with Phase 1 assumptions)
  ├── impact.md
  ├── action-plan.md
  ├── test-plan.md
  └── test-cases.md

Schema: {n} endpoints, {n} error codes, auth: {type}

⚠️  {LOW_COUNT} assumption(s) need confirmation:

{for each LOW field}
LOW [{i}]: `{field}`
  Assumed: {_assumption}
  → Confirm (Enter to accept) or provide correct value:
```

For each answered item: update `input/partner_schema.json` and `docs/source-map.md`.
After all LOWs are confirmed or accepted: re-run Step 3d to refresh `docs/verification-checklist.md`.
Then ask: "Confirm to proceed to Phase 2 (Scaffold)?"

---

### Branch C: CONFLICT_COUNT == 0, LOW_COUNT == 0 — clean

Present this and **stop**:

```
Phase 1 complete ✓

Confidence summary:
  HIGH    : {HIGH_COUNT} fields  ✅
  LOW     : 0  ✅
  CONFLICT: 0  ✅

Verification checklist: docs/verification-checklist.md

Generated docs/:
  ├── requirements.md
  ├── api-analysis.md
  ├── open-questions.md
  ├── impact.md
  ├── action-plan.md
  ├── test-plan.md
  └── test-cases.md

Schema summary:
  Base URL : {url}
  Auth     : {type}
  Endpoints: {n} — {list names}
  Errors   : {n} codes

Open questions (need partner clarification):
{list from open-questions.md}

If you can clarify any of these now, I'll update the schema before Phase 2.
Otherwise I'll note them in open-questions.md and continue.

Confirm to proceed to Phase 2 (Scaffold)?
```

**Do not take any further action until all CONFLICTs are resolved and LOWs are confirmed or accepted.**
