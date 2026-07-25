# Backend

The FastAPI + SQLite backend for the job search dashboard. All commands below
are run from this `backend/` folder.

## Prerequisites

You need [uv](https://docs.astral.sh/uv/) (a Python package manager — it also
installs the right Python version for you):

```bash
brew install uv
```

## Setup

Install the dependencies (one command, safe to re-run anytime):

```bash
uv sync
```

Optional — set up API keys for the AI and recommendation features:

```bash
cp .env.example .env
```

Then open `.env` and follow the comments inside. **You can skip this
entirely** — the application tracker works with no keys configured.

## Run the dev server

```bash
uv run uvicorn app.main:app --reload
```

The API is now at http://127.0.0.1:8000. Two useful pages:

- http://127.0.0.1:8000/health — quick "is it alive" check
- http://127.0.0.1:8000/docs — interactive API docs, auto-generated from the
  code. This is the reference for what data the frontend can get.

Stop the server with `Ctrl+C`.

## Run the tests

```bash
uv run pytest
```

## Where your data lives

Everything is stored in a single SQLite file, `backend-local.db`, in this
folder (created on first use). It is git-ignored, so your personal job-search
data never leaves this machine.

**Back up before migrating:** whenever you run a database migration
(`uv run alembic upgrade head` — arrives in a later step), copy the database
file first:

```bash
cp backend-local.db backend-local.db.backup
```

If a migration ever goes wrong, rename the backup file back and you've lost
nothing.

## Good to know

- **Re-importing your master resume changes future recommendation scoring.**
  The recommendation engine reads your resume sections to build its picture of
  your experience, so a fresh import means fresh (possibly different) match
  scores on new jobs. That's by design — the scores follow your latest resume.
