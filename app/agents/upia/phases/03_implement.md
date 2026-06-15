# Phase 3 — Implement

**Goal:** Generate the 6 partner-specific Go files in the scaffolded repo, following zalopay's provider pattern exactly.

**Before starting:** Read `agent/context/zalopay-provider-pattern.md` in full.
It contains all zalopay-internal constants, interface signatures, patterns, and the MR template.
Everything in that file must be followed as-is — do not invent alternatives.

---

## Step 1: Gather inputs

Read:
- `input/state.json` → `decisions` (if resuming), `local_path`, `partner_name`
- `input/partner_schema.json` → full schema detail

If `input/state.json` contains a `decisions` block from a previous run, use it directly — skip to whichever step was interrupted. Do **not** re-read large source files to reconstruct context you already have in state.json.

Then **ask the human** for the following before writing any code:

```
Before I implement, I need a few details:

1. Service IDs this partner supports (e.g. DIEN, NUOC, NET, CAP, TTTG).
   Each service ID corresponds to a bill type. List all that apply.

2. For each service ID: what is its "converter type name" in Go?
   Example: DIEN → "electricity", NUOC → "water", TTTG → "consumer-finance"
   (Used as the package name under internal/business/manager/{type}/)

3. If there is only ONE service type, I'll skip the type subdirectory and put
   the converter directly in the common service. Confirm if that's the case.
```

Wait for the human's answer. Save the confirmed service IDs into `input/state.json` under `service_ids`.

---

## Step 1b: Template Delta Analysis — MANDATORY before writing any code

Read `input/partner_schema.json` and compare against what the template provides.
Produce a **delete list** and a **keep/replace list** before touching a single file.

**Do NOT read the contents of files on the DELETE LIST** — just delete them outright.
Reading them wastes context window space and adds no value.

### What to evaluate

| Template component | Delete if… |
|---|---|
| `internal/provider/utils/` (RSA signing) | `schema.auth.type` ≠ `rsa` |
| `internal/metrics/balance.go` + test | No endpoint with `purpose: CheckBalance` in schema |
| `internal/provider/mocks/` — `CheckBalance` method | `CheckBalance` deleted from interface |
| `internal/business/manager/consumer-finance/` | `TTTG` not in confirmed service IDs |
| `internal/business/manager/water/` | `NUOC` not in confirmed service IDs |
| `internal/business/manager/internet/` | `NET` not in confirmed service IDs |
| Any other `manager/{type}/` package | type not in confirmed service IDs |
| `entity/provider` — `BaseDataRequest` | auth type is `oauth2` or `apikey` |
| `entity/provider` — `BalanceResponse` | CheckBalance deleted |

### Auth-specific provider struct fields

| auth type | Config fields to ADD | provider struct fields to ADD |
|---|---|---|
| `basic` | `Username`, `Password` | — |
| `apikey` | `APIKey`, `APIKeyHeader` | — |
| `hmac` | `SecretKey` | — |
| `rsa` | `PrivateKeyPath`, `PublicKeyPath` | `rsaUtils utils.RSAUtils` |
| `oauth2` | `RefreshToken` + partner-specific auth fields | `accessToken string`, `tokenExpiry time.Time`, `mu sync.Mutex` |

### Output required

Before proceeding to Step 2, explicitly state the delta and save it to `input/state.json` under `decisions`:

```
DELETE LIST:
  - internal/provider/utils/         (reason: auth=oauth2, not rsa)
  - internal/metrics/balance.go      (reason: no CheckBalance endpoint)
  - ...

KEEP/REPLACE LIST:
  - internal/provider/client.go      → REPLACE (auth logic, endpoints)
  - internal/entity/provider/...     → REPLACE (new structs)
  - ...

AUTH PATTERN: oauth2
  Token cache: accessToken + tokenExpiry + sync.Mutex in provider struct
  Refresh endpoint: {schema.auth.oauth2.token_url}
  TTL: {schema.auth.oauth2.access_token_ttl_hours}h, refresh {schema.auth.oauth2.early_refresh_margin_hours}h early
```

Update `input/state.json`:
```json
"decisions": {
  "auth_type": "{schema.auth.type}",
  "delete_list": ["..."],
  "test_files_to_rewrite": ["internal/business/manager/common/service_test.go", "internal/provider/client_test.go"],
  "mock_files_to_update": ["internal/provider/mocks/client.go"],
  "open_questions_resolved": 0,
  "open_questions_pending": 0
}
```

Do not start Step 2 until this analysis is written out and saved.

---

## Step 1c: Tag implementation decisions with confidence scores

**Read `agent/context/observability-protocol.md`** for the annotation format.

For each decision in the DELETE LIST / KEEP/REPLACE LIST from Step 1b, assign a confidence level.
Save these under `decisions.impl_decisions` in `input/state.json`:

```json
"impl_decisions": [
  {
    "decision": "Delete internal/provider/utils/ (RSA signing)",
    "confidence": "HIGH",
    "source": "input/partner_schema.json: auth.type = 'oauth2' — RSA utils not needed"
  },
  {
    "decision": "oauth2 token TTL = 24h, early refresh = 1h",
    "confidence": "LOW",
    "source": null,
    "assumption": "TTL not specified in docs. Using 24h as safe default. Confirm with partner."
  },
  {
    "decision": "MapPaymentStatusCode default → DeliverManualCheck",
    "confidence": "HIGH",
    "source": "zalopay-provider-pattern.md: mandatory rule for all payment endpoints"
  }
]
```

Compute Phase 3 confidence totals:

```
Implementation decision confidence:
  HIGH    : N
  LOW     : N  → [list decisions]
  CONFLICT: N  → [list decisions]
```

If CONFLICT_COUNT > 0: **stop here** and report the conflicts to the human before writing any code.

Append LOW/CONFLICT implementation decisions to `docs/open-questions.md`:

```markdown
---
## Assumptions logged — Phase 3 ({RFC3339 timestamp})

### LOW confidence implementation decisions
{for each LOW impl_decision}
- **`{decision}`**: {assumption}. _Confirm before code review._

### CONFLICT implementation decisions
{for each CONFLICT impl_decision}
- **`{decision}`**: {conflict_detail}
```

Also append implementation-level rows to `docs/source-map.md` for traceability:

```markdown
{for each impl_decision}
| {decision} | zalopay-provider-pattern.md / partner_schema.json | — | {source note} | {confidence} |
```

---

## Step 2: Directory layout — write from scratch

Phase 2 has already deleted all partner-specific files from the cloned template.
There is nothing to "modify" — only new files to write.

**Source of truth for every file you write:**
1. **Interface signatures and constants** → `agent/context/zalopay-provider-pattern.md`
2. **File-by-file struct patterns** → tool `read_template` (see steps below)
3. **Partner-specific values** → `input/partner_schema.json`
4. **Coding style** → Go coding standards in `zalopay-provider-pattern.md` ("About the template project" section)

Do **not** open or reference any files from the template repo (`provider-imedia`).
The template was cleaned in Phase 2; its implementation code is not a quality reference.

### Directory layout

```
internal/
  constant/
    core.go             — exists, copy unchanged (zalopay internal error codes)
    provider.go         — NEW: partner error codes + mapping functions
  entity/
    base/base.go        — exists, copy unchanged
    provider/
      provider.go       — NEW: partner request/response structs
  provider/
    client.go           — NEW: Provider interface implementation
    dto.go              — NEW: partner HTTP DTOs
    mocks/              — generate after client.go is final
  business/
    base.go             — exists, copy unchanged
    manager/
      interface.go      — exists, copy unchanged (ConverterStrategy interface)
      common/
        service.go      — exists, copy unchanged (orchestrator)
      {type}/
        service.go      — NEW: ConvertBillEntity per service type
  config/
    config.go           — UPDATE: rewrite Provider struct (keep other structs intact)
  cmd/
    server.go           — NEW: wire up new types
```

---

## Step 3: Generate `internal/constant/provider.go`

→ **Read template:** gọi tool `read_template` với `name="provider-constants"`

Key rules:
- One constant per code in `schema.error_codes` — no omissions.
- `MapQueryStatusCode` default: `ProviderErrorCodeNotDefined`.
- `MapPaymentStatusCode` default: `DeliverManualCheck` (-400).
- Add `serviceID string` parameter to `MapPaymentStatusCode` **only** if payment mapping differs between service types.

---

## Step 4: Generate `internal/entity/provider/provider.go`

→ **Read template:** gọi tool `read_template` với `name="entity-provider"`

Key rules:
- Omit `BaseDataRequest` entirely if `schema.auth.type` is `oauth2` or `apikey`.
- Field names: PascalCase Go; JSON tags: exact partner field names from schema.
- `omitempty` on optional response fields.
- `FinalStatus`, `Message`, `OriginalStatus`, `DescriptionStatus`: always `json:"-"` (set by provider, not deserialized).
- Mark PII fields (name, phone, address) with `// PII — do not log` comment.

---

## Step 5: Generate `internal/provider/dto.go`

→ **Read template:** gọi tool `read_template` với `name="provider-dto"`

Include `RefreshTokenRequest` / `RefreshTokenResponse` only if `schema.auth.type == "oauth2"`.

---

## Step 6: Generate `internal/provider/client.go`

→ **Read template:** gọi tool `read_template` với `name="provider-client"`

For each method, follow the observability pattern exactly (see `zalopay-provider-pattern.md` → "Observability Standards"):

1. `spanCtx := tracing.StartSpan(ctx, "provider.client.{method}")`
2. `tracing.SetAttribute(spanCtx, "http.url", endpoint{Method})`
3. Declare `httpStatus`, `providerCode`, `returnCode` vars before the defer — they are set during execution and captured by the defer closure
4. `defer` block: call `p.collector.Observe(metrics.EgressLabels{...})` + set remaining span attributes + `tracing.EndSpan(spanCtx)`
5. Build auth per `schema.auth.type` (see template for each pattern)
6. Call HTTP helper — capture `httpStatus` from HTTP response code
7. Parse response DTO — capture `providerCode` from `dto.BaseResponse.StatusCode`
8. Handle provider return message:
   - `providerMsg := utils.Truncate(dto.BaseResponse.Description, 100)`
   - `logging.FromContext(spanCtx).WithField("provider_message", providerMsg).Warn(...)`
   - `tracing.SetAttribute(spanCtx, "partner.return_message", providerMsg)`
   - **Do NOT add `providerMsg` to `EgressLabels`** — free-text → unbounded cardinality
9. `resp.FinalStatus = providerCode`; set `returnCode` using the mapper that matches the endpoint purpose:
   - **Query endpoints** (GetBill / CheckBalance): `returnCode = constant.MapQueryStatusCode(providerCode)`
   - **Payment endpoints** (PayBill / CheckPay): `returnCode = constant.MapPaymentStatusCode(providerCode)` — default `DeliverManualCheck` (-400). **Never** use MapQueryStatusCode here.
10. Return entity response

**oauth2 token cache pattern:**
```go
func (p *provider) getAccessToken(ctx context.Context) (string, error) {
    p.mu.Lock()
    defer p.mu.Unlock()
    earlyRefresh := {early_refresh_margin_hours} * time.Hour
    if p.accessToken != "" && time.Now().Before(p.tokenExpiry.Add(-earlyRefresh)) {
        return p.accessToken, nil
    }
    // POST to endpointToken with p.cfg.RefreshToken
    // p.accessToken = resp.AccessToken
    // p.tokenExpiry = time.Now().Add({ttl_hours} * time.Hour)
    return p.accessToken, nil
}
```

### Regenerate mocks after finalising the interface

After `client.go` is complete (including all DELETE LIST removals), sync the mock file:

```bash
# Option A — mockgen available:
go generate ./internal/provider/...

# Option B — manual edit of internal/provider/mocks/client.go:
#   Remove Mock methods for deleted interface methods
#   Add Mock methods for new interface methods
#   Keep the generated file header intact
```

Then verify:
```bash
go build ./... 2>&1 | grep -E "^#|error:" | head -20
```

---

## Step 7: Generate `internal/business/manager/{type}/service.go`

→ **Read template:** gọi tool `read_template` với `name="converter-service"`

One file per service type. If only one service type, create `internal/business/manager/{type}/` with the converter there.

---

## Step 8: Update `internal/config/config.go`

Modify the `Provider` struct to include only the fields this partner needs.
**Delete** template fields that don't apply — do not comment them out.
Dead config fields cause confusion for developers reading the code later.

```go
type Provider struct {
    Endpoint      string `mapstructure:"endpoint"`
    // Fields determined by Step 1b auth table
    SkipVerifySSL bool   `mapstructure:"skip_verify_ssl"`
}
```

Update all `config/*.yaml` files: add correct key names, leave values empty (or Vault placeholders for stg/prod).

---

## Step 9: Write `*_test.go` files

### Rule: rewrite, never patch

If a `*_test.go` file already exists and references types from the **DELETE LIST** — delete the entire file and write a new one from scratch. Do not patch with sed/regex — it produces syntax errors.

Files that almost always need full rewrites:
- `internal/business/manager/common/service_test.go` (template version references deleted entity types)
- `internal/provider/client_test.go` (template version uses deleted auth mocks)

Do **not** read these files before rewriting — their content is irrelevant.

### What to write

For each new test file:
- `TestMapQueryStatusCode`: one case per code in `schema.error_codes` + one `"UNKNOWN_XYZ"` default case
- `TestMapPaymentStatusCode`: same coverage
- `TestProvider_GetBill/PayBill/CheckPay`: mock `httpclient.IHttpClient`, cover success + each provider error path
- `TestService_GetBillInfo/PayBill/ReDeliver/CheckTransaction`: mock `provider.Provider`, cover:
  - success path
  - service-not-found (unknown ServiceID)
  - provider error (err != nil)
  - each meaningful non-success status code
- `TestConvertBillEntity`: happy path + empty bill list

Use `testify/assert`. Use `gomock` for mocks.
Only test service IDs from Step 1 — do not write tests for deleted service types.

---

## Step 9b: Delete unused template packages

Execute the DELETE LIST from Step 1b. For each item: delete without reading content first.

```bash
rm -rf {path}   # one per delete list entry
```

Then verify imports are clean:
```bash
go build ./... 2>&1 | grep -E "^#|error:" | head -20
```

Fix any broken imports before continuing.

---

## Step 10: Verify — REQUIRED before push

Run in order. **Do not push if any step fails.**

```bash
# 1. Tidy dependencies
go mod tidy

# 2. Vet — catches issues build misses (format strings, mutex copies, etc.)
go vet ./... 2>&1 | head -20

# 3. Build — must be zero errors
go build ./... 2>&1 | grep -E "^#|error:" | head -30

# 4. Tests — must all pass; show summary + failures only
go test ./... -cover -race 2>&1 | grep -E "^(ok|FAIL|---)" | head -50
```

If `go vet` fails:
- Fix the flagged issues before proceeding — vet catches real bugs

If `go build` fails:
- Import path referencing a deleted package → fix import in the caller
- Undefined type from deleted entity field → update the caller

If `go test` fails:
- Rewrite the failing test file from scratch — do not patch line-by-line
- Never comment out or skip a failing test to make the suite green

When both are green, push and update state:

```bash
cd {local_path}
git add -A
git commit -m "feat: implement {partner_name} adapter"
git push origin feat/integrate-{partner_name}
```

Print the branch URL after push:
```bash
echo "Branch: {repo_url}/-/tree/feat/integrate-{partner_name}"
```

Update `input/state.json`:
```json
{
  "phase": 3,
  "build_status": "passing",
  "last_commit": "{git commit SHA after push}",
  "decisions": { ... (keep as written in Step 1b) }
}
```

Write `input/phase3_checkpoint.md`:
```markdown
# Phase 3 Checkpoint

## Decisions
- Auth: {auth_type}
- Services: {service_ids}
- Deleted: {delete_list}
- Test files rewritten: {list}

## Confidence (implementation decisions)
- HIGH    : {n}
- LOW     : {n}  (accepted as placeholders)
- CONFLICT: 0

## Files changed
- internal/constant/provider.go     ({n} error codes)
- internal/entity/provider/...
- internal/provider/client.go       (auth: {auth_type})
- internal/provider/dto.go
- internal/business/manager/{type}/service.go
- internal/config/config.go

## Build: PASSING
## Tests: PASSING ({n} packages)

## Placeholder items (pending partner confirmation)
{list of [PLACEHOLDER] comments added, or "none"}
```

---

## Step 10b: Generate `docs/verification-checklist.md`

Overwrite `docs/verification-checklist.md` with the Phase 3 checklist:

```markdown
# Verification Checklist — Phase 3: Implement

Generated: {RFC3339 timestamp}

## Auto-Verified by Agent
- [x] `internal/constant/provider.go`: {n} error codes, MapQueryStatusCode, MapPaymentStatusCode
- [x] `internal/entity/provider/provider.go`: {n} structs
- [x] `internal/provider/dto.go`: generated
- [x] `internal/provider/client.go`: auth = {auth_type}
- [x] `internal/business/manager/{type}/service.go`: {n} service types
- [x] `internal/config/config.go`: Provider struct updated
- [x] `go vet ./...`: {clean / N warnings}
- [x] `go build ./...`: {✅ zero errors / ❌ N errors}
- [x] `go test ./... -cover -race`: {✅ all pass / ❌ N failures}

## Requires Human Review
{for each LOW impl_decision}
- [ ] [LOW] {decision}: {assumption} — confirm before merge.

{for each [PLACEHOLDER] comment added}
- [ ] [PLACEHOLDER] {file:line}: {what needs confirmation with partner}

## BLOCKING — Must Resolve Before Phase 4
{if no conflicts and build/tests pass: "None."}
{if build or tests fail: "Build/test failures — see above."}
{if CONFLICT impl_decisions exist: list them}
```

---

## Human Checkpoint #3

Compute confidence totals from `decisions.impl_decisions` in `input/state.json`.
Then follow the branching logic — **stop after presenting the appropriate message**.

---

### Branch A: CONFLICT_COUNT > 0 or build/tests failing — BLOCKED

Present this and **do not ask for confirmation**:

```
Phase 3 complete — BLOCKED ✗

Confidence summary (implementation decisions):
  HIGH    : {HIGH_COUNT}  ✅
  LOW     : {LOW_COUNT}   ⚠️
  CONFLICT: {CONFLICT_COUNT}  🚫

Build : {✅ passing / ❌ failing}
Tests : {✅ passing / ❌ failing}

Verification checklist: docs/verification-checklist.md

{if CONFLICT_COUNT > 0}
🚫 BLOCKED — {CONFLICT_COUNT} implementation conflict(s) must be resolved:

CONFLICT [{i}]: {decision}
  {conflict_detail}
  → Please clarify which approach is correct.

{if build/tests failing}
🚫 BLOCKED — fix build/test failures before proceeding.
```

---

### Branch B: CONFLICT_COUNT == 0 — confirm LOWs and proceed

Present this and **stop**:

```
Phase 3 complete ✓

Confidence summary (implementation decisions):
  HIGH    : {HIGH_COUNT}  ✅
  LOW     : {LOW_COUNT}   ⚠️
  CONFLICT: 0  ✅

Build : ✅  Tests : ✅

Verification checklist: docs/verification-checklist.md

Generated / modified files:
  internal/constant/provider.go       ({n} error codes, MapQueryStatusCode, MapPaymentStatusCode)
  internal/entity/provider/provider.go ({n} structs)
  internal/provider/dto.go
  internal/provider/client.go         (auth: {auth_type})
  internal/business/manager/{type}/service.go  (for each service type)
  internal/config/config.go
  *_test.go files

Service types : {list}
Auth mechanism: {auth_type}

{if LOW_COUNT > 0}
⚠️  {LOW_COUNT} LOW-confidence decision(s) accepted as placeholders:
{for each LOW impl_decision}
  - `{decision}`: {assumption} → marked [PLACEHOLDER] in code

Please review the code at: {repo_url}

If you have corrections, tell me before confirming.
Confirm to proceed to Phase 4 (Test)?
```

**Do not take any further action until the user explicitly confirms.**
