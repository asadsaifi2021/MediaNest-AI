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
