# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

**Greenfield — no code exists yet.** This file is the project charter. Once the project is scaffolded, update this file with the actual build/run/test commands and remove this notice.

Shared repo: https://github.com/nathanecunningham/JoshNathanJobBoard (currently just a README). Clone it and move this charter + `docs/` into it before scaffolding, so both collaborators share the context. The tech stack decision and its rationale live in `docs/brainstorms/2026-07-25-tech-stack-requirements.md`.

## What This Project Is

A personal job search dashboard built collaboratively by two people:

- **Joshua Marcus** (drpemulis@gmail.com) — does microscopy analysis; the primary user of the dashboard. Drives features, data model, and AI-powered functionality. (Note: the machine username `leelab` refers to the Lee Lab computer Joshua develops on — any "Lee" artifacts in paths or configs are the machine, not a person.)
  - LinkedIn: https://www.linkedin.com/in/joshuammarcus/
  - GitHub: https://github.com/marcusjoshm
- **Nathan Cunningham** — UX designer/researcher; owns UI/UX direction and will add this app to his portfolio. Learning Claude Code through this project.
  - Portfolio: https://nathancunningham.webflow.io/
  - LinkedIn: https://www.linkedin.com/in/ncunningham003/

Because one collaborator is learning Claude Code, prefer clear, well-explained changes over clever ones. When making non-obvious decisions, briefly explain the reasoning so both collaborators can follow along.

### What Nathan's portfolio tells us

His portfolio showcases UX design and research (forms engines, admin portals, an interface redesign with tested user outcomes) with a clean, minimalist, whitespace-heavy aesthetic — it is a design portfolio, not a code portfolio, and is hosted on Webflow. Implications for this project:

- Nathan's strength is design direction, research, and visual polish, not necessarily heavy frontend engineering. Claude Code should carry more of the implementation load while Nathan drives design decisions.
- The app's UI should aim for the same minimalist, typography-forward quality as his portfolio so it fits alongside his existing work.
- Stack choice should favor an approachable, conventional frontend (component-based, well-documented patterns) over clever architecture, so Nathan can read, tweak, and learn from it.

## Planned Features

1. **Job discovery** — search the web for jobs matching the user's experience, driven either by a free-text prompt or by parsing the stored resume/CV.
2. **Resume tailoring** — edit/adapt a resume against keywords from a specific job posting (AI-assisted).
3. **Application tracker** — organize submitted applications, their status, and related correspondence (emails, follow-ups, interview notes).
4. **Resume version storage** — keep multiple resume versions, each linkable to the applications it was used for.
5. **Experience history** — a full master record of work/education/skills history, richer than any single resume, used as the source of truth when tailoring resumes.

## Architecture (decided 2026-07-25)

Stack chosen to match the division of labor — Joshua owns the backend in Python, Nathan's prototypes become the frontend via Claude Code. Full rationale in `docs/brainstorms/2026-07-25-tech-stack-requirements.md`.

- **Backend (`backend/`, Joshua's domain):** FastAPI + SQLite. All job-search, resume, and AI logic. The auto-generated API docs are the reference for what data exists.
- **Frontend (`frontend/`, Nathan's domain):** React + Vite + TypeScript + Tailwind CSS + shadcn/ui, implemented from Nathan's Axure/Figma prototypes by Claude Code. Keep it conventional — no clever architecture.
- **Claude API** — powers resume parsing, keyword tailoring, and matching job postings to experience.
- **Collaboration seam:** the JSON API contract. Nathan's Claude Code sessions stay scoped to `frontend/`; prototype handoffs must cover every screen state, the data fields per screen, and a component inventory — his screens define the schema.

Key data-model relationships to preserve whatever the final schema looks like:

- Experience history is the canonical source; resume versions are derived/tailored views of it.
- Each application links to the resume version submitted with it and to its correspondence thread.

## Working Agreements

- The UX collaborator owns UI/UX direction; don't restyle or redesign components beyond the scope of the task at hand.
- Resume content, correspondence, and API keys are personal data — keep them in the local DB / `.env.local`, never committed.
