# How We Work Together — Git Workflow Guide

For Josh and Nathan. One of us is brand new to git and the other is a novice, so this guide favors simple, repeatable habits over git wizardry. When in doubt, ask Claude Code to do the git steps for you — that's a legitimate way to work, and how we both learn.

## Core Principles

1. **`main` always works.** The `main` branch is the shared, working version of the project. Nobody edits it directly — changes arrive only by merging pull requests. If `main` is ever broken, fixing it is the top priority.
2. **All work happens on branches.** A branch is a private sandbox copied from `main`. You can commit half-finished, broken, experimental work there without affecting anyone.
3. **Every contribution goes through a pull request (PR).** No exceptions, even tiny ones — one consistent rule is easier than judgment calls. A PR is a proposal to merge your branch into `main`, and it gives the other person a chance to see what changed.
4. **Pull before you start.** Always sync your local `main` with GitHub before creating a new branch, so you build on the latest version.
5. **Small and often beats big and rare.** Short-lived branches (hours or days, not weeks) with focused changes merge easily. Giant branches cause merge conflicts.
6. **Never commit secrets or personal data.** API keys go in `.env` files and job-search data lives in local database files — both are git-ignored. If it would be bad on a public webpage, it doesn't get committed.
7. **Stay in your lane, visit politely.** Josh owns `backend/`, Nathan owns `frontend/` (see `CLAUDE.md`). You *can* change anything, but if a PR touches the other person's half, ask them to review it before merging.

## The Workflow Loop

This is the cycle for every piece of work, however small. Claude Code can run any or all of these steps — just describe what you want.

**1. Sync up:**
```bash
git checkout main
git pull
```

**2. Create a branch** named `<yourname>/<what-it-does>`:
```bash
git checkout -b josh/application-tracker-api     # Josh's example
git checkout -b nathan/dashboard-layout          # Nathan's example
```

**3. Work and commit as you go.** A commit is a saved checkpoint. Commit whenever something coherent works:
```bash
git add -A
git commit -m "Add status field to application cards"
```
Write commit messages as short commands: "Add X", "Fix Y", "Update Z".

**4. Push your branch to the shared repo:**
```bash
git push -u origin josh/application-tracker-api
```

**5. Open a pull request** (easiest with the GitHub CLI, or the yellow banner on the repo page):
```bash
gh pr create --fill
```
In the description, say what changed and why in a sentence or two.

**6. Review and merge.**
- If your PR touches the other person's half of the app, or you want feedback: ask them to look before merging.
- If it's clearly within your own area: you may merge your own PR.
- Merge using the **"Squash and merge"** button on GitHub. This combines your branch's commits into one tidy commit on `main`, which keeps history readable.
- After merging, click **"Delete branch"** when GitHub offers.

**7. Everyone syncs:** next time either of us starts work, step 1 picks up the merged changes automatically.

## When Git Fights Back

**"Your branch is behind / push rejected."** Someone merged to `main` since you started. Run `git pull` on your branch — git usually merges automatically.

**Merge conflict.** Git found overlapping edits and needs a human to choose. The files will contain markers like `<<<<<<<`. Don't panic and don't guess — this is a great moment to ask Claude Code: *"I have a merge conflict, help me resolve it."* Conflicts are normal and fixable; nothing is lost.

**"I committed something I shouldn't have"** (a secret, a database file, a mistake). Stop — don't try to fix history yourself. Tell the other person and ask Claude Code for help. If a secret (API key) was pushed to GitHub, treat it as exposed: revoke/rotate the key first, then clean up.

## Never Do These

- Never run `git push --force` on `main` or on the other person's branch. Force-pushing rewrites shared history and can destroy work.
- Never commit directly to `main`, even for "just a typo." Branch + PR, always.
- Never commit `.env` files, database files, or anything with real resume/application data. The `.gitignore` protects you, but don't fight it.
- Never delete a branch that isn't yours without asking.

## Cheat Sheet

| I want to... | Command |
|---|---|
| Get the latest shared code | `git checkout main && git pull` |
| Start a new piece of work | `git checkout -b myname/thing` |
| Save a checkpoint | `git add -A && git commit -m "Do thing"` |
| Share my branch | `git push -u origin myname/thing` |
| Propose merging it | `gh pr create --fill` |
| See what state I'm in | `git status` |

Or ask Claude Code in plain English — "start a new branch for the login page," "commit this and open a PR" — and it will run the right commands.
