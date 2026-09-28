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
