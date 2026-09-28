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
