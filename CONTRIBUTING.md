# How We Work Together — Git Workflow Guide

For Josh and Nathan. One of us is brand new to git and the other is a novice, so this guide favors simple, repeatable habits over git wizardry. When in doubt, ask Claude Code to do the git steps for you — that's a legitimate way to work, and how we both learn.

## The Short Version

We both work directly on the `main` branch. No feature branches, no pull requests. Instead of branches keeping our work separate, **our lanes do**: Josh works in `backend/`, Nathan works in `frontend/`. Pull before you start, commit as you go, push when something works.

## Core Principles

1. **Stay in your lane.** Josh owns `backend/`, Nathan owns `frontend/` (see `CLAUDE.md`). Since we edit different folders, our changes almost never collide — that's what makes the no-branches workflow safe. If you need to change something in the other person's half or in shared files (`README.md`, `CLAUDE.md`, docs), give them a heads-up first.
2. **Pull before you start.** Always run `git pull` before working, so you build on the other person's latest changes instead of colliding with them.
3. **Push working code.** `main` is the shared version of the project, so push when the thing you were doing works — not mid-experiment with the app broken. If you do accidentally push something broken, that's fixable; just tell the other person and fix it as the next priority.
4. **Small and often beats big and rare.** Commit and push in small pieces, at least at the end of each work session. The longer your local copy drifts from GitHub, the messier the eventual sync.
5. **Never commit secrets or personal data.** API keys go in `.env` files and job-search data lives in local database files — both are git-ignored. If it would be bad on a public webpage, it doesn't get committed.

## The Workflow Loop

This is the cycle for every work session. Claude Code can run any or all of these steps — just describe what you want.

**1. Sync up before you start:**
```bash
git pull
```

**2. Work and commit as you go.** A commit is a saved checkpoint. Commit whenever something coherent works:
```bash
git add -A
git commit -m "Add status field to application cards"
```
Write commit messages as short commands: "Add X", "Fix Y", "Update Z".

**3. Push your changes to the shared repo:**
```bash
git push
```

That's it. Next time either of us runs `git pull`, we get each other's work automatically.

## When Git Fights Back

**"Your branch is behind / push rejected."** The other person pushed since you last pulled. Run `git pull` — git usually merges automatically because we work in different folders — then `git push` again.

**Merge conflict.** Git found overlapping edits and needs a human to choose. The files will contain markers like `<<<<<<<`. Don't panic and don't guess — this is a great moment to ask Claude Code: *"I have a merge conflict, help me resolve it."* Conflicts are normal and fixable; nothing is lost. (If we stay in our lanes, these should be rare.)

**"I committed something I shouldn't have"** (a secret, a database file, a mistake). Stop — don't try to fix history yourself. Tell the other person and ask Claude Code for help. If a secret (API key) was pushed to GitHub, treat it as exposed: revoke/rotate the key first, then clean up.

## Never Do These

- Never run `git push --force`. Force-pushing rewrites shared history and can destroy the other person's work.
- Never commit `.env` files, database files, or anything with real resume/application data. The `.gitignore` protects you, but don't fight it.
- Never edit the other person's half of the app without telling them first.

## Cheat Sheet

| I want to... | Command |
|---|---|
| Get the latest shared code | `git pull` |
| Save a checkpoint | `git add -A && git commit -m "Do thing"` |
| Share my work | `git push` |
| See what state I'm in | `git status` |

Or ask Claude Code in plain English — "commit and push my changes," "pull Nathan's latest work" — and it will run the right commands.
