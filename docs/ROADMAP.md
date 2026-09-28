# MediaNest AI roadmap

## 1. Repository foundation

- [x] Create an independently owned MediaNest AI repository.
- [x] Preserve the inherited backend and original license.
- [x] Apply product branding and document architecture.
- [x] Document current implementation limits.

## 2. React foundation

- [x] Scaffold React + TypeScript with Vite.
- [x] Add responsive navigation, gallery layout, and an API client.
- [x] Add Supabase login and authenticated metadata requests.
- [x] Verify mocked login/account switching in desktop and mobile browser tests,
  and owner-scoped backend queries with two test users.
- [ ] Verify two real Supabase users against a configured project.
- [x] Implement signup, email confirmation, resend, password recovery, and
  session restoration with automated browser verification.
- [ ] Verify real confirmation/reset email delivery and dashboard redirect URLs.
- [x] Implement Account settings for display name, email changes, password
  updates and local/other-session signout, with desktop/mobile tests.

## 3. First working media flow

- [x] Implement and locally test Supabase ownership constraints, atomic metadata
  sync, model/version-isolated vector search, and server-only database grants.
- [x] Prepare a fresh-project SQL bundle and Supabase setup guide.
- [x] Create the hosted Supabase project, apply migrations 001–003, and verify
  database readiness. User confirmed sign-in works.

- [x] Implement owner-scoped storage registration and storage-reference records;
  tested locally. This is not authenticated device enrollment.
- [x] Apply migration 004 to the hosted project; user confirmed registration.
- [x] Implement node-specific, short-lived upload/read grants and online revocation checks.
- [x] Implement and locally test one-photo uploads, local thumbnails, metadata
  completion retries, and authenticated gallery previews.
- [x] User confirmed the first photo upload, thumbnail and original view work
  against hosted Supabase and the running PC service.
- [x] Display thumbnails in React and show a fallback when storage is unavailable.

## 4. Reliable archive

- [ ] Durable jobs, retry/backoff, resumable transfers, and deduplication.
- [ ] User-editable tags, pagination, deletion, and metadata synchronization.
- [ ] Video/audio range playback and compatible local derivatives.
- [ ] Backup and restore verification.

## 5. AI search

- [ ] License review and hardware benchmark for each chosen model.
- [ ] Object tags and semantic scene search.
- [ ] Face embeddings, user-confirmed naming, and calibrated matching.
- [ ] Timestamped transcripts and full-text search.
- [ ] Model-version tracking and incremental re-indexing.

## 6. Installation and deployment

- [ ] PWA manifest and deliberate metadata caching policy.
- [ ] Android and Windows browser testing.
- [ ] Family access through Tailscale with scoped permissions.
- [ ] Measured cloud deployment costs and quotas.

Complete each working milestone before adding the next major subsystem.
