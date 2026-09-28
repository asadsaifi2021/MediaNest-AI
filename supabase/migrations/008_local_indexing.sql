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
