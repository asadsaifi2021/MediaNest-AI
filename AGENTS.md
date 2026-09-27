# MediaNest AI development guidance

Read README.md, docs/ARCHITECTURE.md, and docs/ROADMAP.md before making changes.

- Keep the product name MediaNest AI.
- Build the frontend with React and TypeScript.
- Keep all original files, thumbnails, and playback derivatives on local storage.
- Keep central searchable metadata in the server database.
- Run AI processing locally in a background worker.
- Never expose server or worker secrets to the frontend or Git.
- Verify ownership for every metadata operation and media-access grant.
- Preserve inherited license attribution.
- Follow the phased roadmap; mark features complete only after verification.
- Do not describe mocked tests as proof of a live Supabase connection.
- Run pytest and Ruff for Python changes; add frontend checks when implemented.
