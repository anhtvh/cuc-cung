# Observability Protocol

This protocol defines four mandatory observability outputs that every phase must produce.
Load this file **only when entering a phase that requires confidence scoring** — do not load at session start.

---

## 1. Confidence Scoring

Every field, decision, or value that the agent extracts or infers must be assigned one of three levels:

| Level | Meaning | When to use |
|---|---|---|
| **HIGH** | Explicit, unambiguous source in the docs | Value is stated directly; no inference needed |
| **LOW** | Agent assumption — no direct source found | Inferred from context, naming patterns, or analogies |
| **CONFLICT** | Contradictory information found | Two or more sources state different values for the same field |

### Annotation format (applied in `input/partner_schema.json`)

Add five metadata keys to every leaf value in the schema:

```json
{
  "name": "trans_id",
  "type": "string",
  "_confidence": "HIGH",
  "_source": "api-guide.pdf, Page 5, Section 3.1 — Request Parameters",
  "_quote": "trans_id: unique transaction ID, maximum 50 characters",
  "_assumption": null,
  "_conflict_detail": null
}
```

For **LOW**:
```json
{
  "name": "amount_unit",
  "type": "int",
  "_confidence": "LOW",
  "_source": null,
  "_quote": null,
  "_assumption": "Assumed VND (integer, no decimal) based on standard zalopay convention. No explicit statement in docs.",
  "_conflict_detail": null
}
```

For **CONFLICT**:
```json
{
  "name": "timeout_seconds",
  "type": "int",
  "_confidence": "CONFLICT",
  "_source": "api-guide.pdf, Page 3 AND Page 11",
  "_quote": null,
  "_assumption": null,
  "_conflict_detail": "Page 3 states 'timeout is 30s'; Page 11 states 'maximum wait time is 60 seconds'."
}
```

---

## 2. Source Map — `docs/source-map.md`

Generated during Phase 1 (Step 3b). Phase 3 may append implementation-level rows.
Sort rows: CONFLICTs first, then LOW, then HIGH.

```markdown
# Source Map — {partner_name}

Generated: {RFC3339 timestamp}

| Field / Decision | Document | Page / Section | Quote | Confidence |
|---|---|---|---|---|
| `error.timeout_sec` | api-guide.pdf | Page 3 AND Page 11 | "30s" vs "60 seconds" | CONFLICT |
| `auth.signature_fields` | — | — | Not found in docs | LOW |
| `base_url` | api-guide.pdf | Page 2, Section 1.0 | "Base URL: https://api.partner.com" | HIGH |
```

---

## 3. Verification Checklist — `docs/verification-checklist.md`

Overwrite this file after each phase. Use this structure:

```markdown
# Verification Checklist — Phase {N}: {Phase Name}

Generated: {RFC3339 timestamp}

## Auto-Verified by Agent
- [x] {item}: {result}

## Requires Human Review
- [ ] [LOW] `{field}`: {assumption made} — confirm correct value.
- [ ] [CONFLICT] `{field}`: {conflict summary} — must resolve before Phase {N+1}.

## BLOCKING — Must Resolve Before Phase {N+1}
None.
```

If there are blocking items, replace "None." with one bullet per CONFLICT.

---

## 4. Assumption Log — append to `docs/open-questions.md`

**Never overwrite.** Always append a dated section at the end of the file.

```markdown
---
## Assumptions logged — Phase {N} ({RFC3339 timestamp})

### LOW confidence items (agent assumptions)
- **`{field}`**: {_assumption}. _Confirm with partner before go-live._

### CONFLICT items (must resolve before Phase {N+1})
- **`{field}`**: {_conflict_detail}
  - Source A: "{quote}" ({doc}, {page})
  - Source B: "{quote}" ({doc}, {page})

### Implementation assumptions (Phase 3+)
- **`{decision}`**: {reason this choice was made without explicit docs backing}.
```

---

## Human Checkpoint Confidence Gate

**This gate is mandatory at every Human Checkpoint.**
Before presenting any confirmation prompt, compute the confidence totals and follow the branch:

### Branch A — CONFLICT_COUNT > 0: BLOCKED

Do **not** ask "Confirm to proceed?" Present this and stop:

```
Phase {N} complete — BLOCKED ✗

Confidence summary:
  HIGH    : {n} items  ✅
  LOW     : {n} items  ⚠️
  CONFLICT: {n} items  🚫

Verification checklist: docs/verification-checklist.md

🚫 BLOCKED — {n} conflict(s) must be resolved before proceeding to Phase {N+1}.

CONFLICT [{i}]: `{field}`
  Source A: "{quote}" ({doc}, {page})
  Source B: "{quote}" ({doc}, {page})
  → Please provide the correct value.

Once resolved: update `input/partner_schema.json` and `docs/source-map.md`, then tell me to continue.
```

### Branch B — CONFLICT_COUNT == 0, LOW_COUNT > 0: confirm assumptions

Present LOW items for confirmation before the proceed prompt:

```
⚠️  {n} LOW-confidence assumption(s) — please confirm or provide correct values:

LOW [{i}]: `{field}`
  Assumed: {_assumption}
  → Confirm (Enter to accept) or provide correct value:
```

Update schema and source-map for each answered item. Then ask: "Confirm to proceed to Phase {N+1}?"

### Branch C — CONFLICT_COUNT == 0, LOW_COUNT == 0: clean

Show the normal checkpoint summary and ask: "Confirm to proceed to Phase {N+1}?"
