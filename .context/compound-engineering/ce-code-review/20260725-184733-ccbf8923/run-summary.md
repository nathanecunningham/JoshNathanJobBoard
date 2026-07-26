# ce-code-review run 20260725-184733-ccbf8923 (mode: autofix)
Scope: git diff c070f2a (backend build, U1-U6, commits af7a401..eb38e7b)
Reviewers: 11 (correctness, testing, maintainability, project-standards, agent-native, security, api-contract, data-migrations, reliability, adversarial, kieran-python). ce-learnings-researcher skipped (docs/solutions/ absent).
Raw findings: 24 + 2 unstructured agent reports. Merges: health(K1+AC1→100), malformed-payload(C3+A4→75), partial-discard(R1+A5). Suppressed@50: 6. Mode-demoted (testing/maintainability advisory): 2. Validators: 11 dispatched (anchor-75 set; anchor-100 findings carried reproduced evidence), 11 confirmed, 0 dropped.

## Applied fixes (1)
- safe_auto@100 models.py docstring drift corrected (maintainability)

## Residual actionable (16)
P1 gated: ai.py:81 wrap_untrusted delimiter escapable (security)
P1 manual: 422 dual error shapes, no RequestValidationError handler (api-contract)
P1 gated: naive datetimes on the wire — JS parses as local time (api-contract)
P2 manual: quota floor unreachable — fresh provider each refresh, remaining_quota=None (correctness)
P2 manual: tailor FK window — re-import during Claude call → IntegrityError 500 (adversarial)
P2 manual@100: explicit-null PATCH on non-nullable fields → 500 (adversarial)
P2 manual@100: dead JobSource Protocol (maintainability)
P2 manual: JobSource enum vs job_source module name collision (maintainability)
P2 manual: get-or-404 duplicated 4x + cross-router private import (maintainability)
P2 manual@100: enum columns lack DB CHECK constraints (data-migrations)
P2 gated@100: multi-page fetch failure discards quota-charged results (reliability+adversarial)
P2 gated: no Anthropic client timeout override (600s default) (reliability)
P2 gated@100: /health untyped bare dict + discarded exception (api-contract+kieran-python)
P2 manual: systemic scoring failure invisible — invalid key = silent all-unscored 200 (correctness+kieran-python)
P3 gated: PDF parse branch lacks untrusted-data framing (security)
P3 manual: malformed JSearch 200 → unstructured 500 (correctness+adversarial)

## Advisory (report-only)
- No rescore path for unscored recommended jobs; dedup locks them out (adversarial+agent-native)
- No refresh concurrency lock — double-click doubles quota/AI spend (adversarial)
- Agent-native polish: snapshot restore primitive absent; Query param descriptions; responses= blocks for error shapes
- CLAUDE.md still says .env.local (project-standards residual)

## Verdict: Ready with fixes (no P0; fix the three P1s before frontend work starts)

## Fix phase (user chose Apply/fix now)
All 16 residual findings fixed by a single fixer pass (113→128 tests). Round-2 focused re-review found 1 real regression (quota cache permanent lockout after month rollover) + 2 hardening items (429 header read ordering; aware-datetime input normalization) — all three fixed inline with regression tests (131 tests final). Round cap (2) reached; loop closed.
Remaining recorded risks: delimiter neutralization is exact-match (case/whitespace variants rely on the prose instruction); score_failures counter can exceed unscored in a rare concurrent-refresh race; 422 openapi schema still advertises the default list shape though responses are normalized strings.
Advisory follow-ups (not fixes): rescore endpoint for unscored jobs, refresh concurrency lock, snapshot-restore primitive, Query/responses OpenAPI polish.
