create table if not exists public.archive_events (
  id uuid primary key,
  asset_id uuid not null,
  event_type text not null check (
    event_type in ('discovered', 'indexed', 'uploaded', 'deleted', 'failed')
  ),
  device_id text not null,
  occurred_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  user_id text not null,
  created_at timestamptz not null default now()
);

create index if not exists archive_events_user_time_idx
  on public.archive_events (user_id, occurred_at desc);

alter table public.archive_events enable row level security;

-- Only the trusted FastAPI backend uses these tables. Its secret/service-role
-- key bypasses RLS after the API has authenticated and scoped the user.
revoke all on public.archive_events from anon, authenticated;
revoke all on public.media_metadata from anon, authenticated;
revoke all on public.face_embeddings from anon, authenticated;

grant select, insert, update, delete on public.archive_events to service_role;
grant select, insert, update, delete on public.media_metadata to service_role;
grant select, insert, update, delete on public.face_embeddings to service_role;
