-- GENERATED: node supabase/build-setup.mjs
-- FRESH PROJECT ONLY. Run once in Supabase SQL Editor as postgres.
-- Existing projects: back up and apply only unapplied migrations.

-- Migration: 001_media_search.sql
create schema if not exists extensions;
create extension if not exists vector with schema extensions;

create table if not exists public.media_metadata (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  device_id text not null,
  local_file_id text not null,
  file_type text not null check (file_type in ('image', 'video', 'audio')),
  thumbnail_url text,
  tags text[] not null default '{}',
  transcription text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, device_id, local_file_id)
);

create table if not exists public.face_embeddings (
  id uuid primary key default gen_random_uuid(),
  media_id uuid not null references public.media_metadata(id) on delete cascade,
  user_id text not null,
  person_name text,
  embedding extensions.vector(512) not null,
  vector_version integer not null default 1 check (vector_version > 0),
  created_at timestamptz not null default now()
);

create index if not exists media_metadata_user_updated_idx
  on public.media_metadata (user_id, updated_at desc);
create index if not exists media_metadata_tags_idx
  on public.media_metadata using gin (tags);
create index if not exists face_embeddings_user_idx
  on public.face_embeddings (user_id);
create index if not exists face_embeddings_vector_idx
  on public.face_embeddings using hnsw (embedding extensions.vector_cosine_ops);

alter table public.media_metadata enable row level security;
alter table public.face_embeddings enable row level security;
grant select, insert, update, delete on public.media_metadata to service_role;
grant select, insert, update, delete on public.face_embeddings to service_role;

create or replace function public.sync_media_metadata(
  p_user_id text,
  p_device_id text,
  p_local_file_id text,
  p_file_type text,
  p_thumbnail_url text,
  p_tags text[],
  p_transcription text,
  p_faces jsonb
) returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_media_id uuid;
  v_face jsonb;
begin
  insert into public.media_metadata (
    user_id, device_id, local_file_id, file_type, thumbnail_url, tags, transcription
  ) values (
    p_user_id, p_device_id, p_local_file_id, p_file_type,
    p_thumbnail_url, coalesce(p_tags, '{}'), p_transcription
  )
  on conflict (user_id, device_id, local_file_id) do update set
    file_type = excluded.file_type,
    thumbnail_url = excluded.thumbnail_url,
    tags = excluded.tags,
    transcription = excluded.transcription,
    updated_at = now()
  returning id into v_media_id;

  delete from public.face_embeddings where media_id = v_media_id;
  for v_face in select value from jsonb_array_elements(coalesce(p_faces, '[]'::jsonb))
  loop
    insert into public.face_embeddings (
      media_id, user_id, person_name, embedding, vector_version
    ) values (
      v_media_id,
      p_user_id,
      nullif(v_face->>'person_name', ''),
      (v_face->'embedding')::text::extensions.vector(512),
      coalesce((v_face->>'vector_version')::integer, 1)
    );
  end loop;

  return v_media_id;
end;
$$;

create or replace function public.match_faces(
  query_embedding extensions.vector(512),
  match_threshold double precision,
  match_count integer,
  p_user_id text
) returns table (
  face_id uuid,
  media_id uuid,
  person_name text,
  similarity double precision
)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    face.id as face_id,
    face.media_id,
    face.person_name,
    1 - (face.embedding operator(extensions.<=>) query_embedding) as similarity
  from public.face_embeddings as face
  where face.user_id = p_user_id
    and 1 - (face.embedding operator(extensions.<=>) query_embedding) >= match_threshold
  order by face.embedding operator(extensions.<=>) query_embedding
  limit least(greatest(match_count, 1), 100);
$$;

revoke all on function public.sync_media_metadata(
  text, text, text, text, text, text[], text, jsonb
) from public, anon, authenticated;
revoke all on function public.match_faces(
  extensions.vector, double precision, integer, text
) from public, anon, authenticated;
grant execute on function public.sync_media_metadata(
  text, text, text, text, text, text[], text, jsonb
) to service_role;
grant execute on function public.match_faces(
  extensions.vector, double precision, integer, text
) to service_role;

-- Migration: 002_archive_events.sql
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

-- Migration: 003_database_integrity.sql
-- Apply once, after 001 and 002. Invalid legacy owners/data abort this entire
-- migration rather than silently deleting records. Back up existing projects.
begin;

alter table public.media_metadata alter column user_id type uuid using user_id::uuid;
alter table public.face_embeddings alter column user_id type uuid using user_id::uuid;
alter table public.archive_events alter column user_id type uuid using user_id::uuid;

alter table public.media_metadata
  add constraint media_auth_owner foreign key (user_id) references auth.users(id) on delete cascade,
  add constraint media_owner_identity unique (id, user_id),
  add constraint media_device_length check (length(btrim(device_id)) between 1 and 128),
  add constraint media_file_length check (length(btrim(local_file_id)) between 1 and 512),
  add constraint media_tag_count check (cardinality(tags) <= 50),
  add constraint media_transcript_length check (length(transcription) <= 200000);
alter table public.face_embeddings
  add constraint face_auth_owner foreign key (user_id) references auth.users(id) on delete cascade,
  add constraint face_media_owner foreign key (media_id, user_id)
    references public.media_metadata(id, user_id) on delete cascade,
  add constraint face_nonzero check (extensions.vector_norm(embedding) > 0),
  add constraint face_name_length check (length(person_name) <= 200),
  add column model_id text not null default 'legacy-512'
    check (length(btrim(model_id)) between 1 and 128);
alter table public.archive_events
  add constraint event_auth_owner foreign key (user_id) references auth.users(id) on delete cascade,
  add constraint event_device_length check (length(btrim(device_id)) between 1 and 128),
  add constraint event_metadata_object check (jsonb_typeof(metadata) = 'object');

-- Event asset_id intentionally has no media FK: discovery can precede indexing,
-- and deletion audit records must survive deletion of the metadata record.
create index media_owner_created_idx on public.media_metadata(user_id, created_at desc, id desc);
create index media_owner_type_idx on public.media_metadata(user_id, file_type, created_at desc, id desc);
create index face_owner_model_idx on public.face_embeddings(user_id, model_id, vector_version);
create index media_transcription_idx on public.media_metadata
  using gin (to_tsvector('simple', coalesce(transcription, '')));

create function public.touch_media_updated_at() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
revoke all on function public.touch_media_updated_at() from public, anon, authenticated;
create trigger media_updated_at before update on public.media_metadata
  for each row execute function public.touch_media_updated_at();

-- Keep existing API argument names for backwards-compatible callers.
create or replace function public.sync_media_metadata(
  p_user_id text, p_device_id text, p_local_file_id text, p_file_type text,
  p_thumbnail_url text, p_tags text[], p_transcription text, p_faces jsonb
) returns uuid language plpgsql security invoker set search_path = '' as $$
declare
  v_media_id uuid;
  v_face jsonb;
  v_owner uuid := p_user_id::uuid;
begin
  if jsonb_typeof(coalesce(p_faces, '[]')) <> 'array'
     or jsonb_array_length(coalesce(p_faces, '[]')) > 100 then
    raise exception 'faces must be an array with at most 100 items' using errcode = '22023';
  end if;
  if exists (select 1 from unnest(p_tags) tag
             where tag is null or length(btrim(tag)) not between 1 and 100) then
    raise exception 'invalid tag' using errcode = '22023';
  end if;
  insert into public.media_metadata
    (user_id, device_id, local_file_id, file_type, thumbnail_url, tags, transcription)
  values (v_owner, p_device_id, p_local_file_id, p_file_type, p_thumbnail_url,
          coalesce(p_tags, '{}'), p_transcription)
  on conflict (user_id, device_id, local_file_id) do update set
    file_type = excluded.file_type, thumbnail_url = excluded.thumbnail_url,
    tags = excluded.tags, transcription = excluded.transcription
  returning id into v_media_id;

  delete from public.face_embeddings where media_id = v_media_id and user_id = v_owner;
  for v_face in select value from jsonb_array_elements(coalesce(p_faces, '[]'))
  loop
    insert into public.face_embeddings
      (media_id, user_id, person_name, embedding, vector_version, model_id)
    values (v_media_id, v_owner, nullif(v_face->>'person_name', ''),
      (v_face->'embedding')::text::extensions.vector(512),
      coalesce((v_face->>'vector_version')::integer, 1),
      coalesce(v_face->>'model_id', 'legacy-512'));
  end loop;
  return v_media_id;
end;
$$;

-- Version/model filtering is essential: equal dimensions do not mean that
-- embeddings from different models can be compared.
create function public.match_faces_v2(
  query_embedding extensions.vector(512), match_threshold double precision,
  match_count integer, p_user_id text,
  p_model_id text default 'legacy-512', p_vector_version integer default 1
) returns table(face_id uuid, media_id uuid, person_name text, similarity double precision)
language plpgsql stable security invoker set search_path = '' as $$
begin
  if query_embedding is null or extensions.vector_dims(query_embedding) <> 512
     or extensions.vector_norm(query_embedding) = 0
     or match_threshold is null or match_threshold not between 0 and 1
     or match_count is null or match_count not between 1 and 100
     or p_vector_version is null or p_vector_version < 1 then
    raise exception 'invalid face search parameters' using errcode = '22023';
  end if;
  -- Filter before exact ranking. Avoid HNSW post-filter under-recall for small
  -- personal archives. Benchmark before switching to approximate search.
  return query
    with owned as materialized (
      select f.* from public.face_embeddings f
      where f.user_id = p_user_id::uuid and f.model_id = p_model_id
        and f.vector_version = p_vector_version
    )
    select f.id, f.media_id, f.person_name,
           1 - (f.embedding operator(extensions.<=>) query_embedding)
    from owned f
    where 1 - (f.embedding operator(extensions.<=>) query_embedding) >= match_threshold
    order by f.embedding operator(extensions.<=>) query_embedding, f.id
    limit match_count;
end;
$$;
create or replace function public.match_faces(
  query_embedding extensions.vector(512), match_threshold double precision,
  match_count integer, p_user_id text
) returns table(face_id uuid, media_id uuid, person_name text, similarity double precision)
language sql stable security invoker set search_path = '' as $$
  select * from public.match_faces_v2(query_embedding, match_threshold, match_count, p_user_id);
$$;

-- Server-only by design: no browser reads/writes, including biometric vectors.
-- RLS denies access even if table grants are accidentally added later.
revoke all on public.media_metadata, public.face_embeddings, public.archive_events
  from public, anon, authenticated;
revoke all on function public.match_faces_v2(extensions.vector, double precision, integer, text, text, integer)
  from public, anon, authenticated;
grant execute on function public.match_faces_v2(extensions.vector, double precision, integer, text, text, integer)
  to service_role;
grant usage on schema extensions to service_role;

notify pgrst, 'reload schema';
commit;

-- Migration: 004_storage_registry.sql
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

-- Migration: 005_photo_upload.sql
begin;
alter table public.media_metadata add column original_filename text
  check (length(original_filename) between 1 and 180);

create function public.complete_photo_upload(
  p_user_id uuid, p_node_id uuid, p_media_id uuid, p_filename text, p_size bigint,
  p_content_type text, p_original_sha256 text, p_thumbnail_sha256 text,
  p_thumbnail_size bigint
) returns uuid language plpgsql security invoker set search_path = '' as $$
declare
  v_device text;
  v_existing public.media_metadata;
begin
  select device_id into v_device from public.storage_nodes
    where id=p_node_id and user_id=p_user_id and disabled_at is null for share;
  if v_device is null then
    raise exception 'active owned node required' using errcode='42501';
  end if;
  if p_size not between 1 and 20971520 or p_thumbnail_size not between 1 and 2097152
    or p_content_type not in ('image/jpeg','image/png','image/webp') then
    raise exception 'invalid photo metadata' using errcode='22023';
  end if;
  -- Serialize retries for the same upload ID without overwriting existing media.
  perform pg_advisory_xact_lock(hashtextextended(p_media_id::text, 0));
  select * into v_existing from public.media_metadata where id=p_media_id;
  if found then
    if v_existing.user_id <> p_user_id or v_existing.device_id <> v_device
      or v_existing.original_filename is distinct from p_filename
      or not exists(select 1 from public.media_objects where media_id=p_media_id
        and user_id=p_user_id and storage_node_id=p_node_id and kind='original'
        and sha256=p_original_sha256 and byte_size=p_size and content_type=p_content_type)
      or not exists(select 1 from public.media_objects where media_id=p_media_id
        and user_id=p_user_id and storage_node_id=p_node_id and kind='thumbnail'
        and sha256=p_thumbnail_sha256 and byte_size=p_thumbnail_size) then
      raise exception 'upload ID already used' using errcode='23505';
    end if;
    return p_media_id;
  end if;
  insert into public.media_metadata(id,user_id,device_id,local_file_id,file_type,original_filename)
    values(p_media_id,p_user_id,v_device,p_media_id::text,'image',p_filename);
  insert into public.media_objects(user_id,media_id,storage_node_id,kind,object_key,
    byte_size,content_type,sha256) values
    (p_user_id,p_media_id,p_node_id,'original',p_media_id,p_size,p_content_type,p_original_sha256),
    (p_user_id,p_media_id,p_node_id,'thumbnail',gen_random_uuid(),p_thumbnail_size,
      'image/jpeg',p_thumbnail_sha256);
  return p_media_id;
end;
$$;
revoke all on function public.complete_photo_upload(uuid,uuid,uuid,text,bigint,text,text,text,bigint)
  from public,anon,authenticated;
grant execute on function public.complete_photo_upload(uuid,uuid,uuid,text,bigint,text,text,text,bigint)
  to service_role;
notify pgrst, 'reload schema';
commit;

-- Migration: 006_search.sql
begin;
-- AI suggestions never overwrite the owner's hand-edited tags.
alter table public.media_metadata
  add column ai_tags text[] not null default '{}',
  add column media_info jsonb not null default '{}',
  add column ai_status text not null default 'not_requested'
    check (ai_status in ('not_requested','queued','ready','failed')),
  add column ai_models jsonb not null default '{}';
create function public.search_archive(
  p_owner uuid, p_query text, p_type text default null, p_tag text default null,
  p_oldest boolean default false, p_offset integer default 0, p_limit integer default 25
) returns setof public.media_metadata
language plpgsql stable security invoker set search_path='' as $$
begin
  if length(p_query)>200 or p_limit not between 1 and 101 or p_offset<0 then
    raise exception 'invalid search parameters' using errcode='22023';
  end if;
  return query select m.* from public.media_metadata m
    where m.user_id=p_owner
      and (p_type is null or m.file_type=p_type)
      and (p_tag is null or p_tag=any(m.tags) or p_tag=any(m.ai_tags))
      and (
        strpos(lower(coalesce(m.original_filename,m.local_file_id)),lower(p_query))>0
        or exists(select 1 from unnest(m.tags || m.ai_tags) t
                  where strpos(lower(t),lower(p_query))>0)
        or to_tsvector('simple',coalesce(m.transcription,'')) @@
           websearch_to_tsquery('simple',p_query))
    order by
      case when p_oldest then m.created_at end asc,
      case when not p_oldest then m.created_at end desc, m.id
    offset p_offset limit p_limit;
end $$;
revoke all on function public.search_archive(uuid,text,text,text,boolean,integer,integer)
  from public,anon,authenticated;
grant execute on function public.search_archive(uuid,text,text,text,boolean,integer,integer)
  to service_role;
notify pgrst,'reload schema';
commit;

-- Migration: 007_media_upload.sql
begin;
create function public.complete_media_upload(
  p_user_id uuid,p_node_id uuid,p_media_id uuid,p_filename text,p_size bigint,
  p_content_type text,p_original_sha256 text,p_thumbnail_sha256 text,p_thumbnail_size bigint,
  p_playback_sha256 text,p_playback_size bigint,p_playback_type text,p_info jsonb
) returns uuid language plpgsql security invoker set search_path='' as $$
declare v_device text; v_existing public.media_metadata; v_type text;
begin
  select device_id into v_device from public.storage_nodes where id=p_node_id
    and user_id=p_user_id and disabled_at is null for share;
  if v_device is null then raise exception 'active owned node required' using errcode='42501'; end if;
  v_type := split_part(p_content_type,'/',1);
  if v_type not in ('video','audio') or p_size not between 1 and 268435456
    or p_thumbnail_size not between 1 and 2097152
    or p_playback_size not between 1 and 1073741824
    or p_playback_type <> (case when v_type='video' then 'video/mp4' else 'audio/mp4' end)
    or jsonb_typeof(p_info)<>'object' or octet_length(p_info::text)>8192 then
    raise exception 'invalid media metadata' using errcode='22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_media_id::text,0));
  select * into v_existing from public.media_metadata where id=p_media_id;
  if found then
    if v_existing.user_id<>p_user_id or v_existing.device_id<>v_device
      or v_existing.original_filename is distinct from p_filename
      or not exists(select 1 from public.media_objects where media_id=p_media_id
        and user_id=p_user_id and storage_node_id=p_node_id and kind='original'
        and sha256=p_original_sha256 and byte_size=p_size and content_type=p_content_type)
      or not exists(select 1 from public.media_objects where media_id=p_media_id
        and kind='playback' and sha256=p_playback_sha256 and byte_size=p_playback_size)
      or not exists(select 1 from public.media_objects where media_id=p_media_id
        and kind='thumbnail' and sha256=p_thumbnail_sha256 and byte_size=p_thumbnail_size) then
      raise exception 'upload ID already used' using errcode='23505';
    end if;
    return p_media_id;
  end if;
  insert into public.media_metadata(id,user_id,device_id,local_file_id,file_type,original_filename,media_info)
    values(p_media_id,p_user_id,v_device,p_media_id::text,v_type,p_filename,p_info);
  insert into public.media_objects(user_id,media_id,storage_node_id,kind,object_key,byte_size,content_type,sha256)
  values
    (p_user_id,p_media_id,p_node_id,'original',p_media_id,p_size,p_content_type,p_original_sha256),
    (p_user_id,p_media_id,p_node_id,'thumbnail',gen_random_uuid(),p_thumbnail_size,'image/jpeg',p_thumbnail_sha256),
    (p_user_id,p_media_id,p_node_id,'playback',gen_random_uuid(),p_playback_size,p_playback_type,p_playback_sha256);
  return p_media_id;
end $$;
revoke all on function public.complete_media_upload(uuid,uuid,uuid,text,bigint,text,text,text,bigint,text,bigint,text,jsonb)
  from public,anon,authenticated;
grant execute on function public.complete_media_upload(uuid,uuid,uuid,text,bigint,text,text,text,bigint,text,bigint,text,jsonb)
  to service_role;
notify pgrst,'reload schema';
commit;

-- Migration: 008_local_indexing.sql
begin;
alter table public.media_metadata
  add column ai_request_id uuid,
  add column ai_options jsonb not null default '{}',
  add column ai_message text check(length(ai_message)<=200);
create function public.apply_index_result(p_owner uuid,p_node uuid,p_media uuid,p_request uuid,p_result jsonb)
returns boolean language plpgsql security invoker set search_path='' as $$
declare m public.media_metadata; f jsonb;
begin
  perform 1 from public.storage_nodes where id=p_node and user_id=p_owner and disabled_at is null for share;
  if not found then raise exception 'active node required' using errcode='42501'; end if;
  select * into m from public.media_metadata where id=p_media and user_id=p_owner for update;
  if not found or m.ai_request_id is distinct from p_request then return false; end if;
  if not exists(select 1 from public.media_objects where media_id=p_media
    and user_id=p_owner and storage_node_id=p_node and kind='original') then
    raise exception 'owned original required' using errcode='42501';
  end if;
  if p_result->>'error' is not null then
    update public.media_metadata set ai_status='failed',ai_message=p_result->>'error' where id=p_media;
    return true;
  end if;
  update public.media_metadata set ai_status='ready',ai_message=null,
    ai_models=ai_models || coalesce(p_result->'models','{}'),
    ai_tags=case when jsonb_typeof(p_result->'tags')='array'
      then array(select jsonb_array_elements_text(p_result->'tags')) else ai_tags end,
    transcription=coalesce(p_result->>'transcription',transcription)
    where id=p_media;
  if jsonb_typeof(p_result->'faces')='array' then
    if not coalesce((m.ai_options->>'faces')::boolean,false)
      or jsonb_array_length(p_result->'faces')>100 then
      raise exception 'face consent required' using errcode='42501';
    end if;
    -- Deterministic IDs preserve owner-confirmed names on identical re-indexing.
    delete from public.face_embeddings where media_id=p_media and user_id=p_owner
      and id not in(select (value->>'id')::uuid from jsonb_array_elements(p_result->'faces'));
    for f in select value from jsonb_array_elements(p_result->'faces') loop
      insert into public.face_embeddings(id,media_id,user_id,embedding,model_id,vector_version)
        values((f->>'id')::uuid,p_media,p_owner,(f->'embedding')::text::extensions.vector(512),
               f->>'model_id',(f->>'vector_version')::integer)
        on conflict(id) do update set embedding=excluded.embedding
          where face_embeddings.user_id=p_owner and face_embeddings.media_id=p_media;
    end loop;
  end if;
  return true;
end $$;
create function public.forget_media_faces(p_owner uuid,p_media uuid)
returns void language plpgsql security invoker set search_path='' as $$
begin
  update public.media_metadata set ai_request_id=null,ai_options=ai_options || '{"faces":false}',
    ai_status='not_requested' where id=p_media and user_id=p_owner;
  delete from public.face_embeddings where media_id=p_media and user_id=p_owner;
end $$;
revoke all on function public.apply_index_result(uuid,uuid,uuid,uuid,jsonb),
  public.forget_media_faces(uuid,uuid) from public,anon,authenticated;
grant execute on function public.apply_index_result(uuid,uuid,uuid,uuid,jsonb),
  public.forget_media_faces(uuid,uuid) to service_role;
create function public.named_face_groups(p_owner uuid)
returns table(person_name text,face_count bigint)
language sql stable security invoker set search_path='' as $$
  select f.person_name,count(*) from public.face_embeddings f
    where f.user_id=p_owner and f.person_name is not null
    group by f.person_name order by f.person_name limit 200;
$$;
revoke all on function public.named_face_groups(uuid) from public,anon,authenticated;
grant execute on function public.named_face_groups(uuid) to service_role;
notify pgrst,'reload schema';
commit;

