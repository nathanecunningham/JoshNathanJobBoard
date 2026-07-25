---
date: 2026-07-25
topic: app-features
---

# Job Search Dashboard — Principal Feature Brainstorm

This is the living brainstorming document for the app's features. Raw ideation happens on Nathan's Miro board; exports of the board land in `docs/miro-exports/` and get distilled here. The tech stack is already decided in `2026-07-25-tech-stack-requirements.md` — this doc is about **what the app does**, not how it's built.

---

## Problem Frame

Josh and Nathan are both on the job market and need one place to run a job search: find jobs worth applying to, tailor a resume quickly for each one, and keep track of every application without spreadsheet sprawl. The app is also Nathan's portfolio piece and Claude Code learning vehicle, so features should stay simple enough to design, build, and explain.

---

## Actors

- A1. Josh: primary user driving features and the backend; provides resume/experience content.
- A2. Nathan: primary user for design; ideates on the Miro board and prototypes screens.
- A3. Claude Code: reads Miro exports, distills them here, and implements from prototypes.

---

## The Three Core Ideas

As stated by Josh (2026-07-25), in priority order for the user experience:

1. **Job recommendations** — recommend jobs based on a resume, portfolio, case studies, or any other input values the user provides.
2. **Quick resume keyword updates** — quickly produce a job-specific copy of a master resume with keywords adapted to the posting.
3. **Application tracker** — a list of jobs with application statuses, notes, dates, etc. **This is the landing page of the app.**

---

## Requirements

**Application tracker (landing page)**
- R1. Opening the app lands on the tracker: a list of jobs, each with at minimum a status, notes, and relevant dates.
- R2. Details to be defined from the Miro board: exact columns/fields, the set of statuses, and how jobs enter the list (see Q1, Q2).

**Job recommendations**
- R3. The app recommends jobs matched to user-provided inputs: resume, portfolio, case studies, or other free-form material.
- R4. Details to be defined from the Miro board: where recommended jobs come from and how a recommendation becomes a tracked application (see Q3).

**Resume keyword tailoring**
- R5. A master resume is the source document; tailoring produces a *copy* with keywords quickly adapted to a specific job posting — the master is never modified.
- R6. Details to be defined from the Miro board: what "quick" looks like in the UI and how tailored copies link to tracked applications (see Q4).

**Brainstorming workflow (Miro board)**
- R7. Nathan's Miro board is the ideation space. Ideas reach the repo as exports — PNG screenshots or PDF, plus wire diagrams — committed to `docs/miro-exports/` (dated filenames) or pasted directly into a Claude Code chat.
- R8. Claude Code reads each export and updates this document; this doc, not the board, is the durable record of decisions.

---

## Success Criteria

- Either user can open the app and see the current state of their whole job search in one glance (the tracker).
- Going from "found an interesting posting" to "tailored resume submitted and tracked" takes minutes, not an evening.
- A Miro export can be dropped in the repo and a Claude session updates this doc from it without further explanation.
- `/ce-plan` can plan the first build from this doc once the "Resolve Before Planning" questions are answered.

---

## Scope Boundaries

- Feature depth (email/correspondence tracking, interview notes, resume version history UI) is deferred until the three core ideas exist in basic form — the charter lists them, but they are not v1 of these screens.
- No live Miro integration (API/MCP): rejected — it requires a Miro sign-in Josh doesn't have and doesn't want to pay for. Exports are the interface.
- Stack, deployment, and collaboration workflow are out of scope here (covered by the tech-stack doc and `CONTRIBUTING.md`).

---

## Key Decisions

- **Tracker is the landing page:** the app opens on the application list, not on search or recommendations — tracking is the daily-use anchor; discovery and tailoring are actions taken from it.
- **Miro-by-export, not Miro-by-API:** screenshots/PDFs committed to `docs/miro-exports/` keep the workflow free and simple, and double as dated snapshots of the team's thinking.
- **Master resume is copy-source, not editable target (R5):** aligns with the charter's rule that experience history/master content is canonical and resume versions are derived views.

---

## Dependencies / Assumptions

- Nathan will export the board (or wire diagrams) with enough detail to answer the questions below — screens and stickies, all readable as images.
- The charter's data-model rule holds: each application links to the resume version submitted with it.

---

## Outstanding Questions

### Resolve Before Planning (answers expected from the Miro board)

- [Affects R2][User decision] Q1: What are the tracker's fields and statuses (e.g., saved / applied / interviewing / offer / rejected)?
- [Affects R2, R4][User decision] Q2: How do jobs enter the tracker — manual entry (paste a URL / type details), saved from recommendations, or both from day one?
- [Affects R3][User decision] Q3: What inputs does the recommender use first (resume only? portfolio and case studies too?), and where do recommended jobs come from?
- [Affects R5, R6][User decision] Q4: What does the quick keyword-update flow look like — paste a posting and get a tailored copy? Review/approve each change?

### Deferred to Planning

- [Affects R3][Needs research] Job-listing data source (search API, job-board APIs, scraping) — cost, terms of service, result quality. (Carried over from the tech-stack doc.)

---

## Next Steps

-> Nathan exports the Miro board (PNG/PDF) into `docs/miro-exports/` — see the README there for the convention.
-> Resume `/ce-brainstorm` with the export: Claude reads it, answers Q1–Q4 into this doc, and marks it ready for planning.
-> Then `/ce-plan` to plan the first vertical slice (likely the tracker landing page).
