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
