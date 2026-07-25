# JoshNathanJobBoard

Josh and Nathan's Job Board

## Start here (Nathan)

Copy and paste this into a fresh terminal to jump into the project and open Claude Code:

```bash
cd ~/Documents/JoshNathanJobBoard
claude
```

**First time only** — if that folder doesn't exist yet, run this once to download the project, then use the command above from then on:

```bash
git clone https://github.com/nathanecunningham/JoshNathanJobBoard.git ~/Documents/JoshNathanJobBoard
```

## Backend

The API server lives in [`backend/`](backend/README.md). After a one-time
`uv sync` in that folder, start it with:

```bash
cd backend && uv run uvicorn app.main:app --reload
```

See [backend/README.md](backend/README.md) for setup, tests, and API docs.

## What's in this repo

- `CLAUDE.md` — project charter: who we are, planned features, and the tech stack we chose
- `CONTRIBUTING.md` — how we work together with git (read this before making changes)
- `docs/brainstorms/` — decision records from our planning sessions
