# MediaNest AI roadmap

## 1. Repository foundation

- [x] Create an independently owned MediaNest AI repository.
- [x] Preserve the inherited backend and original license.
- [x] Apply product branding and document architecture.
- [x] Document current implementation limits.

## 2. React foundation

- [ ] Scaffold React + TypeScript with Vite.
- [ ] Add responsive navigation, gallery layout, and an API client.
- [ ] Add Supabase login and authenticated metadata requests.
- [ ] Verify login and ownership behavior with two users.

## 3. First working media flow

- [ ] Register a local storage node and define storage-reference records.
- [ ] Implement scoped upload/access authorization.
- [ ] Upload one photo directly to the local service.
- [ ] Generate a local thumbnail and synchronize metadata.
- [ ] Display that thumbnail in React and handle NAS-offline status.

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
