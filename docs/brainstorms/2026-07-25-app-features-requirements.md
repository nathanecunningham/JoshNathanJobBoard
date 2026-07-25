---
date: 2026-07-25
topic: app-features
---

# Job Search Dashboard — Feature Requirements

Distilled from Nathan's idea board: `ideas/2026-07-25-job-board-feature-flow.pdf` (the board is the source; this doc is the durable record). Stack decisions live in `2026-07-25-tech-stack-requirements.md`.

---

## Problem Frame

Josh and Nathan are both on the job market and need one place to run a job search: see every application at a glance, get job recommendations matched to their actual experience, and produce a tailored resume for a posting in minutes. Nathan defines the ideas and prototypes; Josh + Claude Code build both halves of the app.

---

## Key Flows

- F1. Daily check-in (landing page)
  - **Trigger:** User opens the app.
  - **Steps:** Landing page shows the list of jobs → user scans statuses, filters/searches if the list is long → updates a status, adds comments/contacts/links, or adds a new job manually.
  - **Outcome:** The whole search's current state is visible and current in one screen.
  - **Covered by:** R1–R5

- F2. Automated job recommendations
  - **Trigger:** The recommendation engine runs (using the saved configuration).
  - **Steps:** Engine matches jobs against the user's experience profile → auto-populates the home page with matching jobs → user reviews them alongside tracked applications.
  - **Outcome:** New matching jobs appear on the landing page without the user searching for them.
  - **Covered by:** R6–R8

- F3. Tailored resume for a posting
  - **Trigger:** User wants to apply to a specific job.
  - **Steps:** Job description comes in from the job's link or pasted text → user defines which resume sections should change → visual builder shows the tailored copy for editing/approval.
  - **Outcome:** A job-specific resume copy exists; the master resume is untouched.
  - **Covered by:** R9–R11

---

## Requirements

**Application tracker (landing page)**
- R1. The landing page is a list of jobs; each row shows at minimum company and position.
- R2. Each job has one status: **Not Started → Applied → then Denied or Accepted**.
- R3. Each job also carries: dates, comments, contacts, and links.
- R4. Jobs can be added manually ("add new").
- R5. The list has modern search and filtering.

**Automated job recommendations**
- R6. A configuration section stores the matching setup: job-side parameters (experience, location, pay) and the user's experience-match sources (resume, case studies, webpages, manual input).
- R7. The engine auto-populates the home page with jobs that match the user's experience.
- R8. Recommended jobs surface on the landing page alongside tracked ones (they start as untracked/"Not Started" candidates the user can keep or dismiss).

**Automated resume updates**
- R9. A job's description can be captured two ways: followed from the job's link, or copy-pasted in.
- R10. The user defines which sections of the resume will change during tailoring; untouched sections stay as the master resume has them.
- R11. Tailoring happens in a visual builder element — the user sees and edits the tailored copy rather than getting an opaque AI rewrite. The master resume is never modified (charter rule: master/experience history is canonical; tailored resumes are derived copies).

---

## Success Criteria

- Opening the app answers "where does my whole search stand?" in one glance — no spreadsheet needed.
- Matching jobs show up on the landing page without the user hunting for them.
- "Found a posting → tailored resume ready" takes minutes, and the master resume is never at risk.
- Nathan's prototypes can be built screen-by-screen against these requirements without inventing behavior.

---

## Scope Boundaries

- Correspondence/email tracking and interview notes: the board's "comments" and "contacts" cover v1; a fuller correspondence thread (per the charter) comes later.
- Resume version history UI: v1 needs tailored copies to exist and be linked to applications; a browsing/management UI for versions is later.
- No live Miro integration — the board reaches the repo as exports in `ideas/` (decided 2026-07-25).
- No deployment, auth, or multi-user (per the tech-stack doc).

---

## Key Decisions

- **Tracker is the landing page**, and the recommendation engine feeds that same page — discovery and tracking share one surface instead of separate screens.
- **Statuses are a simple pipeline** (Not Started → Applied → Denied/Accepted) — no sub-stages until real use demands them.
- **Resume tailoring is visual and user-controlled** — the user picks which sections change and edits in a builder, rather than trusting a one-shot AI rewrite.

---

## Dependencies / Assumptions

- Claude API key available for matching and tailoring — resolved 2026-07-25: each user funds their own pay-as-you-go key (~$5 lasts months); Claude subscriptions can't power API calls. Details in the backend doc's AI Cost Model.
- "Webpages" as an experience source means user-provided URLs (e.g., portfolio pages) the engine can read — assumed, not spelled out on the board.

---

## Outstanding Questions

### Resolve Before Planning

- [Affects R8][User decision] Q1: How do recommended jobs mix with tracked ones on the landing page — same list with a "recommended" marker, or a separate section/tab? (Nathan's prototype will likely answer this.)

### Deferred to Planning

- [Affects R7][Needs research] Where the engine finds candidate jobs (search API, job-board APIs, scraping) — cost, terms of service, result quality.
- [Affects R9][Technical] Link-following reliability (many job sites block scraping) — copy-paste is the guaranteed path; links are best-effort.
- [Affects R11][Technical] What "visual builder element" means concretely — waiting on Nathan's prototype; backend just needs section-level resume structure to support it.

---

## Next Steps

-> Nathan prototypes the three screens (landing page, configuration section, resume builder) from this doc + his board.
-> `/ce-plan` to plan the backend build: data model (jobs, statuses, contacts/links, master resume + tailored copies) and the API the screens will need.
-> Q1 resolves whenever Nathan's landing-page prototype lands in `ideas/`.
