# Public sample demonstration

Deploy only the React sample library publicly. The demo does not use Supabase,
the metadata API, the storage service or the AI worker. It opens automatically
without login and disables server access. Gallery search, filters and detail
dialogs demonstrate the UI; uploads, playback and live AI are not demonstrated.
Your normal local development configuration remains unchanged.

## Netlify (Git deployment)

1. Push the demo changes, including root netlify.toml, to your GitHub repository.
2. Sign in to Netlify and choose to add/import a project from Git.
3. Connect GitHub and grant access only to MediaNest-AI. The repository can remain private.
4. Select MediaNest-AI and branch main.
5. Use the settings in netlify.toml: base frontend, build npm run build,
   publish dist (relative to frontend), Node 22.
6. Confirm VITE_DEMO_ONLY=true. Do not add Supabase keys, backend secrets,
   private storage addresses or your local environment files.
7. Deploy, then explicitly publish/enable public access if Netlify prompts for it.
8. Open the provided HTTPS URL in a private browser window. Confirm it opens
   the sample library without sign-in and shows the public-demo notice.
9. Test search/filtering, open an item, and refresh /settings directly.
10. Share the Netlify URL. Future pushes to the configured branch rebuild it.

Do not upload an existing local dist folder: it may have been built with your
private installation's configuration. Git deployment makes a fresh demo build.
Do not expose your PC or run a public storage tunnel for this demo.

Netlify Free uses a monthly credit allowance; it is not unlimited hosting or a
lifetime guarantee. Check current pricing and usage in the hosting dashboard.

## Cloudflare Pages alternative

Use a Git-connected static Pages project with root frontend, build npm run build,
output dist, Node 22 and VITE_DEMO_ONLY=true. Do not add backend credentials.
Pages supports SPA fallback when there is no top-level 404.html. Verify direct
route refreshes after deployment. Netlify-specific headers do not transfer:
configure equivalent response headers on Pages if choosing that provider.

## Local demo verification

From frontend in PowerShell:

```powershell
$env:VITE_DEMO_ONLY="true"
npm run build
npm run test:demo
Remove-Item Env:VITE_DEMO_ONLY
```

This replaces the local dist with a demo build. Run npm run build again without
that flag before serving a private production installation. npm run dev remains
the normal private development app when the flag is not set.
