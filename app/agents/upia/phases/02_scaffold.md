# Phase 2 — Scaffold

**Goal:** Clone the template repo, create a new GitLab project, rename placeholders, push docs.

All GitLab operations use **`glab` CLI** — never MCP GitLab tools.

---

## Step 1: Read config

Read `config.yaml` and extract:
- `gitlab_base_url` — used to verify glab is pointing at the right instance
- `namespace` — GitLab group path (e.g. `aqr/bill`)
- `template_repo` — source template path (e.g. `aqr/bill/provider-imedia`)
- `partner_name`
- `dry_run`

Also read `input/state.json` to get the schema path from Phase 1.

Feature branch: `feat/integrate-{partner_name}` (all work here → MR → `master` in Phase 4)
New repo name: `provider-{partner_name}`
New module path: `gitlab.zalopay.vn/{namespace}/provider-{partner_name}`
Template module path: `gitlab.zalopay.vn/{template_repo}` (derived from config — do NOT hardcode `provider-imedia`)

**dry_run note:** If `dry_run: true`, prefix every `glab` and `git push` command with `echo "[DRY RUN]"` — print the command but do not execute it.

---

## Step 2: Clone the template repo

**Before cloning**, remove any stale directory from a previous session:

```bash
if [ -d "/tmp/provider-{partner_name}" ]; then
  rm -rf /tmp/provider-{partner_name}
fi
```

Clone the template using git:

```bash
git clone git@gitlab.zalopay.vn:{template_repo}.git /tmp/provider-{partner_name}
```

Remove the `.git` directory so we start with a clean history:

```bash
rm -rf /tmp/provider-{partner_name}/.git
```

---

## Step 3: Create new GitLab project

```bash
# Get the numeric group ID (required by the projects API)
GROUP_ID=$(glab api "groups/{namespace_url_encoded}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

# Create the project under that group
PROJECT_JSON=$(glab api projects --method POST \
  -f "name=provider-{partner_name}" \
  -f "namespace_id=$GROUP_ID" \
  -f "visibility=internal" \
  -f "initialize_with_readme=false")

# Extract URLs
WEB_URL=$(echo "$PROJECT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['web_url'])")
SSH_URL=$(echo "$PROJECT_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['ssh_url_to_repo'])")

echo "Created: $WEB_URL"
echo "SSH:     $SSH_URL"
```

> **namespace_url_encoded**: replace `/` with `%2F` (e.g. `aqr%2Fbill`).

Save `WEB_URL` and `SSH_URL` — needed in Step 6.

---

## Step 4: Replace module path and placeholders

Replace every occurrence of the template module path in all `.go` and `go.mod` files:

`old` is derived from `template_repo` in config — never hardcode `provider-imedia`:

```bash
python3 -c "
import pathlib
old = 'gitlab.zalopay.vn/{template_repo}'          # from config.yaml
new = 'gitlab.zalopay.vn/{namespace}/provider-{partner_name}'
for p in pathlib.Path('/tmp/provider-{partner_name}').rglob('*'):
    if p.is_file() and p.suffix in ('.go', '.mod'):
        text = p.read_text()
        if old in text:
            p.write_text(text.replace(old, new))
"
```

**Config YAML files** (`config/dev.yaml`, `config/local.yaml`, etc.):
Clear the `provider` section values — leave keys, set values to empty strings.
The developer fills in real credentials after Phase 3.

---

## Step 4b: Delete partner-specific implementation files

The template carries `provider-imedia`'s own business logic. Delete every file Phase 3 will generate fresh — **do not read them first**, their content is irrelevant.

```bash
REPO=/tmp/provider-{partner_name}

# Partner-specific entities — Phase 3 writes from scratch
rm -f  $REPO/internal/constant/provider.go
rm -f  $REPO/internal/entity/provider/provider.go
rm -f  $REPO/internal/provider/client.go
rm -f  $REPO/internal/provider/dto.go
rm -rf $REPO/internal/provider/mocks/
rm -rf $REPO/internal/provider/utils/           # rsa utils — deleted if not rsa auth

# All converter strategies — Phase 3 creates only what schema needs
rm -rf $REPO/internal/business/manager/consumer-finance/
rm -rf $REPO/internal/business/manager/water/
rm -rf $REPO/internal/business/manager/internet/
rm -rf $REPO/internal/business/manager/electricity/

# Partner-specific metrics
rm -f  $REPO/internal/metrics/balance.go

# Application wiring — Phase 3 rewrites to match new types
rm -f  $REPO/cmd/server.go

# Remove all *_test.go files in partner-specific paths — Phase 3 writes from scratch
find $REPO/internal/provider      -name "*_test.go" -delete
find $REPO/internal/constant      -name "*_test.go" -delete
find $REPO/internal/entity/provider -name "*_test.go" -delete
find $REPO/internal/business/manager -name "*_test.go" -delete
```

**What remains after this step:**
- Infrastructure (kept, copy-as-is): `internal/httpclient/`, `internal/logging/`, `internal/metrics/` (framework), `internal/tracing/`, `internal/caching/`, `internal/middleware/`, `internal/handler/`, `internal/utils/`
- Contracts (kept, copy-as-is): `internal/entity/base/`, `internal/business/base.go`, `internal/business/manager/interface.go`, `internal/business/manager/common/service.go`
- Config (kept, Provider struct will be updated in Phase 3 Step 8)
- `go.mod` / `go.sum` — kept with updated module path

Phase 3 will write all deleted files from scratch — **there is nothing left to "modify from the template".**

---

## Step 4c: Scan for residual template identifiers (leak guard) — MANDATORY

The Step 4 replace only rewrites the **module path**. The template is a real partner
(`provider-imedia`), so its name can still survive as plain literals in the KEPT
infrastructure files: service name, metric namespace/subsystem, tracer/app name,
default config values, README. These must NOT carry into the new partner's repo.

Compute the template's bare identifier from config — the last path segment of
`template_repo` (e.g. `aqr/bill/provider-imedia` → `provider-imedia`), plus its short
form (`imedia`). Then scan the repo (after deletions, excluding `.git/` and `docs/`):

```bash
REPO=/tmp/provider-{partner_name}
TEMPLATE_NAME="provider-imedia"   # = basename of {template_repo}
SHORT="imedia"                    # short form, if any

grep -rni -E "$TEMPLATE_NAME|$SHORT" "$REPO" \
  --include="*.go" --include="*.mod" --include="*.yaml" --include="*.yml" \
  --include="*.md" --include="*.env" --exclude-dir=.git --exclude-dir=docs
```

For every hit:
- **Replace** the literal with the new partner's equivalent (service name → `{partner_name}`,
  metric namespace → `{partner_name}`, app/tracer name → `provider-{partner_name}`, etc.).
- If a hit is in a file Phase 3 will rewrite anyway (constant/entity/provider/manager),
  ignore it — it will be overwritten.

After fixing, re-run the grep — **it must return zero hits in kept infrastructure files**
before pushing. Record any replacements made under Step 5b assumptions.

---

## Step 5: Copy `docs/` into the new repo

```bash
cp -r ./docs /tmp/provider-{partner_name}/docs
```

---

## Step 5b: Log scaffold assumptions to `docs/open-questions.md`

Append a Phase 2 section to `docs/open-questions.md` for any decisions not explicitly stated in `config.yaml`:

```markdown
---
## Assumptions logged — Phase 2 ({RFC3339 timestamp})

### Scaffold decisions
{for each assumption made, for example:}
- **namespace URL encoding**: Encoded `{namespace}` as `{encoded}` (standard URL percent-encoding).
- **repo visibility**: Set to `internal` (zalopay default — confirm if `private` is required).
- **branch naming**: Used `feat/integrate-{partner_name}` (derived from config convention).
```

If all values came directly from `config.yaml` with no inference: append "No scaffold assumptions in Phase 2."

---

## Step 6: Push to feature branch (initial push)

```bash
cd /tmp/provider-{partner_name}

git init
git remote add origin {SSH_URL}
git checkout -b feat/integrate-{partner_name}

git add -A
git commit -m "chore: initial scaffold from {template_repo} template"
git push -u origin feat/integrate-{partner_name}
```

Print the repo URL after push:
```bash
echo "Repo: {WEB_URL}"
echo "Branch: {WEB_URL}/-/tree/feat/integrate-{partner_name}"
```

---

## Step 7: Update state

Write `input/state.json`, updating:
```json
{
  "phase": 2,
  "repo_url": "{WEB_URL}",
  "repo_ssh_url": "{SSH_URL}",
  "local_path": "/tmp/provider-{partner_name}",
  "feature_branch": "feat/integrate-{partner_name}",
  "build_status": "",
  "last_commit": "",
  "decisions": {
    "auth_type": "",
    "delete_list": [],
    "test_files_to_rewrite": [],
    "mock_files_to_update": [],
    "open_questions_resolved": "{n_resolved}",
    "open_questions_pending": "{n_pending}",
    "impl_decisions": []
  }
}
```

Write `input/phase2_checkpoint.md`:
```markdown
# Phase 2 Checkpoint

## Repo
- URL          : {WEB_URL}
- SSH          : {SSH_URL}
- Module path  : gitlab.zalopay.vn/{namespace}/provider-{partner_name}
- Branch       : feat/integrate-{partner_name}

## Scaffold
- Template cloned from: {template_repo}
- Module path replaced: ✅
- docs/ copied: ✅ (7 files)

## Confidence totals (Phase 1, after Phase 2 Q&A)
- HIGH    : {n}
- LOW     : {n}  (accepted as placeholders)
- CONFLICT: 0

## Open questions status
- Resolved before Phase 3: {n_resolved}/{n_total}
- Pending as [PLACEHOLDER]: {n_pending}
```

---

## Step 7b: Generate `docs/verification-checklist.md`

Overwrite `docs/verification-checklist.md` with the Phase 2 checklist:

```markdown
# Verification Checklist — Phase 2: Scaffold

Generated: {RFC3339 timestamp}

## Auto-Verified by Agent
- [x] Template cloned from: {template_repo}
- [x] Stale `/tmp/provider-{partner_name}` removed before clone
- [x] Old `.git` directory removed (clean history)
- [x] Module path replaced in all .go and go.mod files
- [x] Residual template-identifier scan clean (Step 4c): {0 hits / N hits fixed} — no `{template_basename}` literal left in kept infra
- [x] GitLab project created: {WEB_URL}
- [x] Implementation files deleted (Phase 3 writes from scratch)
- [x] `docs/` copied into repo ({n} files)
- [x] Initial commit pushed to `feat/integrate-{partner_name}`
- [x] Phase 1 open questions status: {n_resolved}/{n_total} resolved

## Requires Human Review
- [ ] Verify module path in `go.mod`: `gitlab.zalopay.vn/{namespace}/provider-{partner_name}`
- [ ] Confirm repo visibility (`internal`) is appropriate for this partner
- [ ] config/*.yaml have blank provider credentials — fill in after Phase 3
{if n_pending_open_questions > 0}
- [ ] {n_pending_open_questions} open question(s) still unresolved — review `docs/open-questions.md`

## BLOCKING — Must Resolve Before Phase 3
{if no unresolved CONFLICTs from Phase 1: "None."}
{if unresolved CONFLICTs remain from Phase 1: list them}
```

---

## Human Checkpoint #2

Check whether any Phase 1 CONFLICTs remain unresolved (scan `docs/open-questions.md`).
Then follow the branching logic — **stop after presenting the appropriate message**.

---

### Branch A: Unresolved CONFLICTs from Phase 1 — BLOCKED

Present this and **do not ask for confirmation**:

```
Phase 2 complete — BLOCKED ✗

Phase 1 confidence conflicts are still unresolved.
Agent cannot proceed to Phase 3 (code generation) with open contradictions.

Verification checklist: docs/verification-checklist.md

Unresolved conflicts (from docs/open-questions.md):
{list each unresolved CONFLICT item}

Resolve these first, then confirm to continue.
```

---

### Branch B: No blocking conflicts

Present this:

```
Phase 2 complete ✓

Verification checklist: docs/verification-checklist.md

New repo created : {WEB_URL}
Template cloned  : {template_repo}
Module path      : gitlab.zalopay.vn/{namespace}/provider-{partner_name}
Branch           : feat/integrate-{partner_name}  →  master

Pushed to feat/integrate-{partner_name}:
  - Full template scaffold (module path updated)
  - docs/ from Phase 1 (7 files)

Note: config/*.yaml have blank provider credentials — fill in after Phase 3.
```

Then read `docs/open-questions.md` and present **each unresolved question** individually:

```
⚠️  Open questions from Phase 1 that affect Phase 3 implementation:

{for each question in open-questions.md}
Q{n}: {question text}
     Impact: {which file/logic this affects if unanswered}
     → Your answer (or press Enter to skip and use placeholder):
```

For each answered question:
- Update `docs/open-questions.md` with the answer
- Update `input/partner_schema.json` if the answer changes a field type, error code, or endpoint detail
- Update `_confidence` from `LOW` to `HIGH` in the schema annotation

For each skipped question:
- Note it as `[PLACEHOLDER — confirm with partner before go-live]` in the relevant code comment during Phase 3

After collecting all answers: re-run Step 7b to refresh `docs/verification-checklist.md` and update `confidence_totals` in `input/state.json` with the final values.

After collecting answers, present the final confirmation:

```
Open questions resolved: {n_resolved}/{n_total}
Remaining as placeholders: {n_skipped}
Phase 1 confidence after updates:
  HIGH    : {HIGH_COUNT} fields  ✅
  LOW     : {LOW_COUNT} fields   ⚠️  (accepted as placeholders)
  CONFLICT: 0  ✅

Confirm to proceed to Phase 3 (Implement)?
```

**Do not take any further action until the user explicitly confirms.**
