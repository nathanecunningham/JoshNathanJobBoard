---
date: 2026-07-25
topic: tech-stack
---

# Job Search Dashboard — Tech Stack Decision

## Problem Frame

Joshua Marcus (Python/scientific-computing developer) and Nathan Cunningham (UX designer/researcher, Axure-fluent, learning Figma and AI tooling) are building a job search dashboard together in a shared repo (https://github.com/nathanecunningham/JoshNathanJobBoard). The app serves both of them on the job market and doubles as a portfolio piece for Nathan and a Claude Code learning vehicle for him. Neither collaborator hand-writes frontend code: Nathan produces design prototypes, Joshua builds the backend and wires the two together, and Claude Code implements the UI from the prototypes. The stack must fit this exact division of labor.

---

## Actors

- A1. Joshua: owns the backend (data model, job search, resume/AI logic) and the API seam that connects frontend to backend. Python is his working language.
- A2. Nathan: owns UI/UX direction. Prototypes in Axure now, Figma later. Learns Claude Code by driving frontend implementation sessions. Will present the design work (prototype) in his portfolio; a live app is optional.
- A3. Claude Code: translates Nathan's prototypes into working frontend components and writes the fetch-layer boilerplate on the frontend side of the seam.

---

## Key Flows

- F1. Design-to-implementation handoff
  - **Trigger:** Nathan completes a prototype for a screen or feature.
  - **Actors:** A2, A3, A1
  - **Steps:** Nathan exports annotated screens (all states) from Axure/Figma → Claude Code implements them as React components in `frontend/` → Joshua defines/extends the matching FastAPI endpoints in `backend/` → Claude wires fetch calls to the API → both review the running result.
  - **Outcome:** The implemented screen matches the prototype and displays live data from the backend.
  - **Covered by:** R1, R2, R5, R6

---

## Requirements

**Stack**
- R1. Backend is Python: FastAPI serving a JSON API, with SQLite for local storage. All job-search, resume, and AI logic lives here.
- R2. Frontend is React + Vite + TypeScript + Tailwind CSS + shadcn/ui, implemented from prototypes via Claude Code — kept conventional and boring so any future session (or Nathan) can read and modify it.
- R3. Both halves live in the shared GitHub repo as `backend/` and `frontend/` directories (monorepo).
- R4. Real job-search data stays local (SQLite file, git-ignored). Secrets in `.env`, never committed.

**Collaboration model**
- R5. The API contract is the seam between owners: Joshua's endpoint definitions (with FastAPI's auto-generated docs) are the reference Nathan and Claude build against.
- R6. Prototype handoffs must include: every screen in every state (empty/loading/error/populated), the data fields shown per screen, interactions/flows, and a component inventory. Screens define the schema.
- R7. The repo must be runnable by a Claude Code beginner: documented one-command startup for both dev servers, and a CLAUDE.md that explains the project to future sessions.

---

## Success Criteria

- Joshua can build and debug the entire backend in Python without touching TypeScript internals.
- Nathan can run Claude Code sessions scoped to `frontend/` and see his prototype become a working UI without risk of breaking the backend.
- A planning session (`/ce-plan`) can scaffold the project from this doc without inventing stack choices.
- The repo reads as a credible portfolio artifact: designed in Axure/Figma, shipped as a React app.

---

## Scope Boundaries

- No deployment/hosting in v1 — the app runs locally. A public demo (seeded fake data; backend on Fly.io/Railway, frontend on Vercel/Netlify) is a possible later addition, and the stack choice deliberately keeps that path open.
- No multi-user accounts or auth in v1 — each collaborator runs their own local instance with their own data.
- Nathan's portfolio presentation (prototype, case study) is his workstream, not part of this codebase.
- App features themselves (job discovery, resume tailoring, application tracker, resume versions, experience history) are defined in `CLAUDE.md` and will get their own brainstorm/plan — this doc only fixes the stack.

---

## Key Decisions

- **FastAPI + React monorepo over full-stack Next.js:** Next.js would put Joshua's backend work in TypeScript, discarding his Python fluency exactly where he contributes most. Rejected.
- **FastAPI + React over Python-only HTMX:** HTMX maximizes Joshua's self-sufficiency but converts Nathan's role to spec-writer — no design/AI tooling targets HTMX, and it weakens his portfolio story and learning goals. Rejected.
- **The prototype tool is not a stack constraint:** Axure and Figma output design specs, not code, so every stack consumes them the same way (Claude re-implements). The stack was chosen on wiring language (Python for Joshua) and AI-tooling strength (React/Tailwind), where the trade lands on both collaborators' strengths.
- **SQLite over hosted database:** personal job-search data stays private as a local file; swapping in a seeded demo DB later is trivial.

---

## Dependencies / Assumptions

- Nathan can export annotated screens/images from Axure at the completeness level in R6 (Axure is strong at interaction specs, so this is low-risk).
- Claude API key available for resume-parsing/tailoring features (billing on Joshua's account — unverified assumption).
- Local dev machines can run Node and Python side-by-side.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R1][Needs research] Which job-search data source to use (search API, job-board APIs, scraping) — cost, terms of service, and result quality need investigation.
- [Affects R3][Technical] Exact monorepo layout, dev-server orchestration (one-command startup), and CORS config.
- [Affects R6][Technical] Whether to add a lightweight shared type/contract mechanism (e.g., OpenAPI-generated TypeScript types from FastAPI) or keep the contract informal at first.

---

## Next Steps

-> `/ce-plan` for structured implementation planning (scaffolding the monorepo in the shared repo, first vertical slice).
-> Before planning: clone https://github.com/nathanecunningham/JoshNathanJobBoard and move `CLAUDE.md` + `docs/` into it so both collaborators share this context.
