# How We Work Together — Git Workflow Guide

For Josh and Nathan. One of us is brand new to git and the other is a novice, so this guide favors simple, repeatable habits over git wizardry. When in doubt, ask Claude Code to do the git steps for you — that's a legitimate way to work, and how we both learn.

## The Short Version

We both work directly on the `main` branch. No feature branches, no pull requests. Instead of branches keeping our work separate, **our roles do**:

- **Nathan is the ideas guy.** His prototypes, wire diagrams, Miro board exports, and notes live in the `ideas/` folder (see `ideas/README.md`). He never needs to touch code.
- **Josh builds the app.** He works on both `backend/` and `frontend/` (with Claude Code), turning Nathan's ideas into the working product.

Since Nathan adds files to `ideas/` and Josh writes code everywhere else, our changes can't collide. Pull before you start, commit as you go, push when you're done.

## Core Principles

1. **Stay in your role.** Nathan adds ideas and prototypes to `ideas/`; Josh writes the code. That separation — not branches — is what keeps two git novices from stepping on each other. If either of us wants to change something in the other's territory (including shared docs like `CLAUDE.md`), give the other a heads-up first.
2. **Pull before you start.** Always run `git pull` before working, so you build on the latest shared version instead of colliding with it.
3. **Push freely (Nathan) / push working code (Josh).** Nothing in `ideas/` can break the app, so Nathan should push whenever he adds something. Josh pushes when the thing he was building works — not mid-experiment with the app broken. If something broken does land on `main`, that's fixable; just say so and fix it as the next priority.
4. **Small and often beats big and rare.** Commit and push in small pieces, at least at the end of each work session. The longer your local copy drifts from GitHub, the messier the eventual sync.
5. **Never commit secrets or personal data.** API keys go in `.env` files and job-search data lives in local database files — both are git-ignored. If it would be bad on a public webpage, it doesn't get committed.

## The Workflow Loop

Same three steps for both of us. Claude Code can run any of them — just describe what you want.

**1. Sync up before you start:**
```bash
git pull
```

**2. Work and commit as you go.** A commit is a saved checkpoint:
```bash
git add -A
git commit -m "Add tracker wireframe"
```
Write commit messages as short commands: "Add X", "Fix Y", "Update Z".

**3. Push to the shared repo:**
```bash
git push
```

That's it. Next time either of us runs `git pull`, we get each other's work automatically.

## When Git Fights Back

**"Your branch is behind / push rejected."** The other person pushed since you last pulled. Run `git pull` — git merges automatically because we work in different folders — then `git push` again.

**Merge conflict.** Git found overlapping edits and needs a human to choose. The files will contain markers like `<<<<<<<`. Don't panic and don't guess — ask Claude Code: *"I have a merge conflict, help me resolve it."* Conflicts are normal and fixable; nothing is lost. (With our role split, these should be very rare.)

**"I committed something I shouldn't have"** (a secret, a database file, a mistake). Stop — don't try to fix history yourself. Tell the other person and ask Claude Code for help. If a secret (API key) was pushed to GitHub, treat it as exposed: revoke/rotate the key first, then clean up.

## Never Do These

- Never run `git push --force`. Force-pushing rewrites shared history and can destroy the other person's work.
- Never commit `.env` files, database files, or anything with real resume/application data. The `.gitignore` protects you, but don't fight it.
- Never edit the other person's territory without telling them first.

## Cheat Sheet

| I want to... | Command |
|---|---|
| Get the latest shared work | `git pull` |
| Save a checkpoint | `git add -A && git commit -m "Do thing"` |
| Share my work | `git push` |
| See what state I'm in | `git status` |

Or ask Claude Code in plain English — "commit and push my new ideas," "pull Nathan's latest exports" — and it will run the right commands.
