# Ideas — Nathan's Folder

This is Nathan's home in the repo. Everything that shapes what we build starts here:

- **Miro board exports** — screenshots (PNG) or PDFs of the idea board
- **Wire diagrams and prototypes** — exported screens from Axure or Figma
- **Notes** — anything written, in any format

## How to add something

1. Name the file with the date and topic, e.g. `2026-07-28-tracker-wireframe.png`.
2. Drop it in this folder (subfolders are fine, e.g. `ideas/prototypes/`).
3. Commit and push:
   ```bash
   git add -A
   git commit -m "Add tracker wireframe"
   git push
   ```
   Or just tell Claude Code: *"commit and push my new ideas."*

You can also drag an image straight into a Claude Code chat if you want to discuss it before committing it.

## What happens next

Claude Code reads what lands here, and Josh + Claude turn it into the brainstorming docs (`docs/brainstorms/`) and then working code (`backend/`, `frontend/`). Ideas in, app out.
