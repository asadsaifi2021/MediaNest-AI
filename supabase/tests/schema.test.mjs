import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';
import { vector } from '@electric-sql/pglite-pgvector';

const alice = '11111111-1111-4111-8111-111111111111';
const bob = '22222222-2222-4222-8222-222222222222';
const embedding = [1, ...Array(511).fill(0)];
const migrations = new URL('../migrations/', import.meta.url);

test('archive search, AV completion, AI consent and stale-result isolation', async () => {
  const db = await database();
  try {
    await migrate(db);
    await db.exec('set role service_role');
    const node = (await db.query(
      "insert into public.storage_nodes(user_id,device_id,display_name,base_url) values ($1,'pc','PC','https://pc.example.test') returning id", [alice],
    )).rows[0].id;
    const media = '44444444-4444-4444-8444-444444444444';
    const sql = 'select public.complete_media_upload($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)';
    const args = [alice,node,media,'Holiday.MP4',123,'video/mp4','a'.repeat(64),'b'.repeat(64),50,
      'c'.repeat(64),200,'video/mp4',JSON.stringify({duration:2})];
    await assert.rejects(db.query(sql,[bob,...args.slice(1)]));
    await db.query(sql,args); await db.query(sql,args);
    assert.equal((await db.query('select * from public.media_objects')).rows.length,3);
    await assert.rejects(db.query(sql,[...args.slice(0,9),'d'.repeat(64),...args.slice(10)]));
    const search = (owner, query) => db.query('select * from public.search_archive($1,$2)',[owner,query]);
    assert.equal((await search(alice,'holiday')).rows.length,1);
    assert.equal((await search(bob,'holiday')).rows.length,0);
    assert.equal((await search(alice,"%),user_id.eq.any")).rows.length,0);
    const request = '55555555-5555-4555-8555-555555555555';
    const face = '66666666-6666-4666-8666-666666666666';
    await db.query("update public.media_metadata set tags='{Family}',ai_status='queued',ai_request_id=$1,ai_options='{\"faces\":true}' where id=$2",[request,media]);
    const result = {tags:['car'],transcription:'A picnic beside the mountains',models:{objects:'test'},
      faces:[{id:face,embedding,model_id:'test-face',vector_version:1}]};
    const apply = (owner=alice,req=request) => db.query('select public.apply_index_result($1,$2,$3,$4,$5) as applied',
      [owner,node,media,req,JSON.stringify(result)]);
    await assert.rejects(apply(bob));
    assert.equal((await apply(alice,'77777777-7777-4777-8777-777777777777')).rows[0].applied,false);
    assert.equal((await apply()).rows[0].applied,true);
    let row = (await search(alice,'CAR')).rows[0];
    assert.deepEqual(row.tags,['Family']); assert.deepEqual(row.ai_tags,['car']);
    assert.equal((await search(alice,'mountains')).rows.length,1);
    await db.query("update public.face_embeddings set person_name='Dad' where id=$1",[face]);
    await apply();
    assert.equal((await db.query('select person_name from public.face_embeddings where id=$1',[face])).rows[0].person_name,'Dad');
    assert.equal((await db.query('select * from public.named_face_groups($1)',[alice])).rows[0].person_name,'Dad');
    assert.equal((await db.query('select * from public.named_face_groups($1)',[bob])).rows.length,0);
    await db.query('select public.forget_media_faces($1,$2)',[alice,media]);
    assert.equal((await apply()).rows[0].applied,false);
    assert.equal((await db.query('select id from public.face_embeddings')).rows.length,0);
    await db.exec('reset role; set role authenticated');
    await assert.rejects(search(alice,'holiday'));
    await assert.rejects(apply());
    await db.exec('reset role');
  } finally { await db.close(); }
});

test('photo completion is atomic, idempotent, and owner/node scoped', async () => {
  const db = await database();
  try {
    await migrate(db);
    await db.exec('set role service_role');
    const node = (await db.query(
      "insert into public.storage_nodes(user_id,device_id,display_name,base_url) values ($1,'pc','PC','http://127.0.0.1:8100') returning id", [alice],
    )).rows[0].id;
    const id = '44444444-4444-4444-8444-444444444444';
    const sql = 'select public.complete_photo_upload($1,$2,$3,$4,$5,$6,$7,$8,$9)';
    const args = [alice, node, id, 'photo.jpg', 100, 'image/jpeg', 'a'.repeat(64), 'b'.repeat(64), 50];
    await assert.rejects(db.query(sql, [bob, ...args.slice(1)]));
    await assert.rejects(db.query(sql, [...args.slice(0, 7), 'invalid-hash', 50]));
    assert.equal((await db.query('select id from public.media_metadata')).rows.length, 0);
    await db.query(sql, args);
    await db.query(sql, args);
    assert.equal((await db.query('select id from public.media_metadata')).rows.length, 1);
    assert.equal((await db.query('select id from public.media_objects')).rows.length, 2);
    await assert.rejects(db.query(sql, [...args.slice(0, 6), 'c'.repeat(64), ...args.slice(7)]));
    await db.query('update public.storage_nodes set disabled_at=now() where id=$1', [node]);
    await assert.rejects(db.query(sql, args));
    await db.exec('reset role; set role authenticated');
    await assert.rejects(db.query(sql, args));
    await db.exec('reset role');
  } finally { await db.close(); }
});

test('storage registry preserves owner boundaries and denies browser access', async () => {
  const db = await database();
  try {
    await migrate(db);
    await db.exec('set role service_role');
    const media = await sync(db, alice);
    async function node(owner) {
      return (await db.query(
        "insert into public.storage_nodes(user_id,device_id,display_name,base_url) values ($1,'pc','Windows PC','http://127.0.0.1:8100') returning id",
        [owner],
      )).rows[0].id;
    }
    const a = await node(alice);
    const b = await node(bob);
    await assert.rejects(node(alice), 'duplicate owner/device ID rejected');
    const insert = "insert into public.media_objects(user_id,media_id,storage_node_id,kind,byte_size,content_type) values ($1,$2,$3,'original',12,'image/jpeg')";
    await assert.rejects(db.query(insert, [alice, media, b]), 'cannot reference another owner node');
    await assert.rejects(db.query(insert, [bob, media, b]), 'cannot reference another owner media');
    await db.query(insert, [alice, media, a]);
    await assert.rejects(db.query(insert, [alice, media, a]), 'one original per media');
    await db.query('update public.storage_nodes set disabled_at=now() where id=$1', [a]);
    assert.equal((await db.query('select id from public.media_objects')).rows.length, 1);
    await db.exec('reset role');
    for (const role of ['anon', 'authenticated']) {
      await db.exec('set role ' + role);
      await assert.rejects(db.query('select * from public.storage_nodes'));
      await assert.rejects(db.query('select * from public.media_objects'));
      await db.exec('reset role');
    }
    await db.exec('grant select on public.storage_nodes, public.media_objects to authenticated; set role authenticated');
    assert.equal((await db.query('select * from public.storage_nodes')).rows.length, 0);
    assert.equal((await db.query('select * from public.media_objects')).rows.length, 0);
    await db.exec('reset role');
    await db.query('delete from auth.users where id=$1', [alice]);
    assert.equal((await db.query('select id from public.media_objects')).rows.length, 0);
    assert.equal((await db.query('select id from public.storage_nodes')).rows.length, 1);
  } finally { await db.close(); }
});
async function database() {
  const db = new PGlite({ extensions: { vector } });
  // Isolated test-only Auth/role stand-ins; never installed on Supabase.
  await db.exec(`
    create role anon; create role authenticated;
    create role service_role bypassrls;
    create schema auth; create table auth.users(id uuid primary key);
    grant usage on schema public to anon, authenticated, service_role;
    insert into auth.users values ('${alice}'), ('${bob}');
  `);
  return db;
}
async function migrate(db, names) {
  for (const name of names ?? (await readdir(migrations)).filter(n => n.endsWith('.sql')).sort()) {
    await db.exec(await readFile(new URL(name, migrations), 'utf8'));
  }
}
async function sync(db, owner, faces = [{ embedding }], tags = ['family']) {
  return (await db.query(
    'select public.sync_media_metadata($1,$2,$3,$4,$5,$6,$7,$8) as id',
    [owner, 'nas', 'opaque-object-1', 'image', null, tags,
      'A picnic in the mountains', JSON.stringify(faces)],
  )).rows[0].id;
}
async function matches(db, owner, model = 'legacy-512', version = 1) {
  return (await db.query(
    'select * from public.match_faces_v2($1::extensions.vector,$2,$3,$4,$5,$6)',
    [JSON.stringify(embedding), 0.8, 20, owner, model, version],
  )).rows;
}

test('fresh migrations: atomic sync, ownership, vector/model isolation, FTS, deletion', async () => {
  const db = await database();
  try {
    await migrate(db);
    await db.exec('set role service_role');
    const a = await sync(db, alice);
    const b = await sync(db, bob);
    assert.notEqual(a, b);
    assert.equal(await sync(db, alice), a, 'retry keeps media ID');
    assert.equal((await matches(db, alice)).length, 1, 'retry does not duplicate faces');
    assert.equal((await matches(db, alice))[0].media_id, a);
    assert.equal((await matches(db, bob))[0].media_id, b);
    await assert.rejects(sync(db, alice, [{ embedding: Array(512).fill(0) }]));
    assert.equal((await matches(db, alice)).length, 1, 'invalid replacement rolls back deletion');
    await assert.rejects(sync(db, alice, [{ embedding: [1, 2] }]));
    await assert.rejects(sync(db, alice, [], ['']));
    await assert.rejects(sync(db, '33333333-3333-4333-8333-333333333333'));
    await assert.rejects(db.query(
      'insert into public.face_embeddings(media_id,user_id,embedding) values ($1,$2,$3)',
      [a, bob, JSON.stringify(embedding)],
    ));
    await sync(db, alice, [{ embedding, model_id: 'model-b', vector_version: 2 }]);
    assert.equal((await matches(db, alice)).length, 0);
    assert.equal((await matches(db, alice, 'model-b', 1)).length, 0);
    assert.equal((await matches(db, alice, 'model-b', 2)).length, 1);
    assert.equal((await db.query(
      "select id from public.media_metadata where user_id=$1 and to_tsvector('simple', coalesce(transcription,'')) @@ plainto_tsquery('simple','mountains')",
      [alice],
    )).rows.length, 1);
    await db.exec('reset role');
    await db.query('delete from auth.users where id=$1', [alice]);
    assert.equal((await db.query('select id from public.media_metadata')).rows.length, 1);
    assert.equal((await db.query('select id from public.face_embeddings')).rows.length, 1);
  } finally { await db.close(); }
});

test('browser roles cannot read metadata or execute privileged RPCs; RLS is deny-by-default', async () => {
  const db = await database();
  try {
    await migrate(db);
    await sync(db, alice);
    for (const role of ['anon', 'authenticated']) {
      await db.exec('set role ' + role);
      for (const table of ['media_metadata', 'face_embeddings', 'archive_events']) {
        await assert.rejects(db.query('select * from public.' + table));
      }
      await assert.rejects(sync(db, alice));
      await assert.rejects(matches(db, alice));
      await db.exec('reset role');
    }
    await db.exec('grant select on public.media_metadata to authenticated; set role authenticated');
    assert.equal((await db.query('select * from public.media_metadata')).rows.length, 0);
    await db.exec('reset role');
  } finally { await db.close(); }
});

test('upgrade preserves valid existing data and old RPC contract', async () => {
  const db = await database();
  try {
    await migrate(db, ['001_media_search.sql', '002_archive_events.sql']);
    const id = await sync(db, alice);
    await migrate(db, ['003_database_integrity.sql']);
    assert.equal(await sync(db, alice), id);
    const rows = (await db.query(
      'select * from public.match_faces($1::extensions.vector,0.8,20,$2)',
      [JSON.stringify(embedding), alice],
    )).rows;
    assert.equal(rows[0].media_id, id);
  } finally { await db.close(); }
});

test('upgrade with invalid legacy ownership aborts without losing data', async () => {
  const db = await database();
  try {
    await migrate(db, ['001_media_search.sql', '002_archive_events.sql']);
    await sync(db, 'not-a-real-auth-user');
    await assert.rejects(migrate(db, ['003_database_integrity.sql']));
    await db.exec('rollback');
    assert.equal((await db.query('select user_id from public.media_metadata')).rows[0].user_id,
      'not-a-real-auth-user');
  } finally { await db.close(); }
});
