// Fresh-project convenience bundle; migration files remain the source of truth.
import { readFile, readdir, writeFile } from 'node:fs/promises';
const directory = new URL('./migrations/', import.meta.url);
const files = (await readdir(directory)).filter(name => name.endsWith('.sql')).sort();
let sql = '-- GENERATED: node supabase/build-setup.mjs\n'
  + '-- FRESH PROJECT ONLY. Run once in Supabase SQL Editor as postgres.\n'
  + '-- Existing projects: back up and apply only unapplied migrations.\n\n';
for (const name of files) {
  sql += '-- Migration: ' + name + '\n'
    + (await readFile(new URL(name, directory), 'utf8')).trim() + '\n\n';
}
const output = new URL('./setup.sql', import.meta.url);
if (process.argv.includes('--check')) {
  if (await readFile(output, 'utf8') !== sql) throw new Error('Regenerate supabase/setup.sql');
} else {
  await writeFile(output, sql);
}
