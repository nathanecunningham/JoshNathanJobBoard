---
date: 2026-07-25
topic: backend-build
---

# Backend v1 — Thin Slices of All Three Features

How `backend/` gets built to serve the features in `2026-07-25-app-features-requirements.md` (which distills Nathan's board, `ideas/2026-07-25-job-board-feature-flow.pdf`). Stack per the tech-stack doc: FastAPI + SQLite, conventional and boring. This doc is technical on purpose — the brainstorm was about the build.

---

## Build Strategy (decided)

- **All three features ship as thin slices** rather than one feature deep-first: the whole app shape exists early, each part minimal.
- **Job source: one free-tier jobs API** (candidate: Adzuna; exact pick researched in planning). Claude scores fetched jobs against the experience profile.
- **Master resume: structured sections in the DB** (summary, experience entries, skills, education, ...). Imported once — paste text or upload a PDF, Claude parses it into sections. Tailoring and Nathan's visual builder map directly onto sections.

---

## Requirements

**Data model (what must exist, schema details in planning)**
- R1. Job: company, position, description, link(s), source (manual vs recommended), status (`not_started`, `applied`, `denied`, `accepted`), relevant dates, comments, contacts.
- R2. Master resume as ordered, named sections; tailored resumes are derived copies that record which job they're for and which sections changed. The master is never modified by tailoring.
- R3. Configuration: job-side parameters (experience, location, pay) and experience-match sources (resume, case studies, webpages, manual input). All four source types are stored; v1 matching reads resume + manual input only.
- R4. Everything lives in the local SQLite file (git-ignored); Claude API key in `.env`.

**API (the seam Nathan's screens build against)**
- R5. Jobs CRUD plus search and filtering (status, text) to power the landing page.
- R6. Per-job sub-resources: comments, contacts, links, status changes (with dates).
- R7. Config endpoints: read/update parameters and experience sources.
- R8. Resume endpoints: import master (paste or PDF upload → parsed sections), read sections, request a tailored copy for a job (from the job's stored description or pasted text), edit tailored sections (what the visual builder calls).
- R9. Recommendations: a manual "refresh" endpoint fetches from the jobs API, scores matches via Claude, and inserts recommended jobs; recommended jobs are dismissible. No background scheduler in v1 — refresh is a button.
- R10. FastAPI auto-docs stay accurate — they are the API contract reference for the frontend.

**AI integration (Claude API)**
- R11. Two AI services, kept separate and small: match-scoring (job description vs experience profile → score + short rationale) and section-tailoring (job description + selected sections → rewritten sections for review, never auto-applied).

---

## Success Criteria

- The landing page can be fully driven by R5/R6 with zero AI configured — tracker works even if AI/API keys are missing.
- One "refresh recommendations" call fills the home page with scored real jobs.
- Import master resume → pick a job → get a tailored copy with only the chosen sections changed, master untouched.
- Nathan can prototype every screen against the auto-generated API docs without asking what data exists.

---

## Scope Boundaries

- No background jobs/scheduling — recommendation refresh is user-triggered in v1.
- No webpage/case-study fetching for the experience profile in v1 (stored in config, unused by the engine).
- No PDF/docx *export* of tailored resumes in v1 — sections in, sections out; export is a later slice.
- No auth, no deployment, no multi-user (per tech-stack doc).

---

## Key Decisions

- **Thin slices over depth-first:** the app is only compelling when the loop (find → tailor → track) exists; each slice can deepen independently later.
- **Free jobs API over scraping or manual-only:** real auto-population from day one without ToS risk; provider swap stays cheap behind one fetch service.
- **Structured sections over document blobs:** section-level tailoring (board: "defining which section will change") and the visual builder need addressable sections; parsing happens once at import instead of on every tailor.
- **Tracker must work without AI (R5/R6 standalone):** keeps the daily-use anchor immune to API limits, key problems, or provider changes.
- **AI billing: each user's own Claude API key, pay-as-you-go (decided 2026-07-25):** Claude Pro/Max subscriptions cannot power the app's API calls — Anthropic bills API usage separately, and using subscription login tokens from third-party apps is against their terms. Each of us creates a developer account at console.anthropic.com, buys the $5 minimum credit block, and puts the key in our local `.env`.

---

## AI Cost Model

Estimated per-action costs (Haiku 4.5 for scoring, Sonnet for tailoring; API prices as of 2026-07):

- Parse master resume (rare): ~3–5¢
- Tailor a resume for one job: ~1–4¢
- Score one job against the profile: ~0.3¢ → a 50-job refresh ≈ 15–20¢

Expected monthly spend: **~$1.50–3 for an active daily search**, ~$5–8 for heavy use. A $5 credit block should last months. Three cost levers are already in the requirements: refresh is a manual button (R9, no background scheduler), dedup means already-seen jobs are never re-scored (R9), and prompt-caching the experience profile cuts repeat input costs ~90%. If AI features go unused, cost is $0. Check the console.anthropic.com usage dashboard after the first week of real use to confirm the burn rate.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R9][Needs research] Which free jobs API: coverage for Josh's field (microscopy/science) and Nathan's (UX), rate limits, terms. Adzuna is the starting candidate.
- [Affects R9][Technical] Dedup strategy when a refresh returns jobs already tracked or previously dismissed.
- [Affects R2][Technical] Section granularity for experience entries (one section per employer vs one "experience" block) — affects how precise tailoring can be.
- [Affects R8][Technical] PDF import parsing approach (Claude-vision vs text extraction first).

---

## Next Steps

-> `/ce-plan` to plan the backend scaffold and build order of the slices (suggested: tracker → resume import/tailor → recommendations, since each builds on the previous).
-> Nathan prototypes the three screens; his landing-page prototype resolves how recommended jobs mix with tracked ones (Q1 in the features doc).
