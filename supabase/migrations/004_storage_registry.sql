-- Metadata only: registering a node does not enroll a trusted device or prove
-- availability. Media bytes and filesystem paths never belong in these tables.
begin;
create table public.storage_nodes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  device_id text not null check (device_id ~ '^[a-zA-Z0-9_-]{1,128}$'),
  display_name text not null check (length(btrim(display_name)) between 1 and 100),
  base_url text not null check (
    length(base_url) <= 2048 and
    (base_url ~ '^https://[a-zA-Z0-9.-]+(:[0-9]{1,5})?$' or
     base_url ~ '^http://(localhost|127\.0\.0\.1)(:[0-9]{1,5})?$')
  ),
  created_at timestamptz not null default now(),
  disabled_at timestamptz,
  unique (user_id, device_id),
  unique (id, user_id)
);
create table public.media_objects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  media_id uuid not null,
  storage_node_id uuid not null,
  kind text not null check (kind in ('original', 'thumbnail', 'playback')),
  object_key uuid not null default gen_random_uuid(),
  byte_size bigint not null check (byte_size >= 0),
  content_type text not null check (length(content_type) between 1 and 128),
  sha256 text check (sha256 ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now(),
  foreign key (media_id, user_id) references public.media_metadata(id, user_id) on delete cascade,
  foreign key (storage_node_id, user_id) references public.storage_nodes(id, user_id),
  unique (media_id, kind),
  unique (storage_node_id, object_key)
);
create index storage_nodes_owner_idx on public.storage_nodes(user_id, created_at, id);
create index media_objects_owner_idx on public.media_objects(user_id, media_id);
create index media_objects_node_owner_idx on public.media_objects(storage_node_id, user_id);
alter table public.storage_nodes enable row level security;
alter table public.media_objects enable row level security;
revoke all on public.storage_nodes, public.media_objects from public, anon, authenticated;
grant select, insert, update on public.storage_nodes to service_role;
grant select, insert, update, delete on public.media_objects to service_role;
comment on table public.storage_nodes is
  'Owner-declared storage origins. Not verified connectivity or authenticated node enrollment.';
comment on table public.media_objects is
  'Opaque local object references only. Actual files must remain on owner storage.';
notify pgrst, 'reload schema';
commit;
