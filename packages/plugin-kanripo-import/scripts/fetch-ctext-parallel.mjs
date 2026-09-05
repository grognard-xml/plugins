#!/usr/bin/env node
/**
 * Fetch a punctuated row from ctext.org wiki and print it for parallel punctuation.
 */
import process from 'node:process';
import { parseArgs } from 'node:util';
import { fetchCtextWikiParallel } from './ctext-wiki-parallel.mjs';

const { values, positionals } = parseArgs({
  options: {
    url: { type: 'string', short: 'u' },
    row: { type: 'string', short: 'r' },
    id: { type: 'string' },
    contains: { type: 'string', short: 'c' },
    section: { type: 'string', short: 's' },
    'list-sections': { type: 'boolean' },
    'fetch-all': { type: 'boolean' },
    help: { type: 'boolean', short: 'h' },
  },
  allowPositionals: true,
});

if (values.help) {
  console.log(`Usage: fetch-ctext-parallel.mjs --url <wiki-url> [--section TITLE | --row N | --id pN | --contains TEXT]

Fetches a ctext wiki chapter page and prints punctuated text.
Inline commentary is kept as <span class="inlinecomment">…</span> for segmented mode.

Note: row numbers repeat within a chapter; prefer --section, --id, or --contains.
A res= index URL lists chapters; use --list-sections or add --fetch-all to pull every chapter (slow).

Examples:
  node scripts/fetch-ctext-parallel.mjs -u 'https://ctext.org/wiki.pl?if=gb&chapter=793335' -s 兩都賦序
  node scripts/fetch-ctext-parallel.mjs -u 'https://ctext.org/wiki.pl?if=gb&res=150222' --list-sections
  node scripts/fetch-ctext-parallel.mjs -u 'https://ctext.org/wiki.pl?if=gb&res=150222' --fetch-all
`);
  process.exit(0);
}

const url = values.url ?? positionals[0];
if (!url) {
  console.error('Missing --url (wiki chapter URL).');
  process.exit(1);
}

try {
  if (values['list-sections']) {
    const { listWikiCatalog } = await import('./ctext-wiki-parallel.mjs');
    const html = await fetch(url, {
      headers: { 'User-Agent': 'grognard-plugin-kanripo-import/0.1' },
    }).then((response) => response.text());
    for (const section of listWikiCatalog(html)) {
      process.stdout.write(`${section.title || section.slug}\t${section.rowCount} rows\t${section.id}\n`);
    }
    process.exit(0);
  }

  const result = await fetchCtextWikiParallel({
    url,
    row: values.row,
    id: values.id,
    contains: values.contains,
    section: values.section,
    fetchAll: values['fetch-all'] || undefined,
  });
  process.stdout.write(`${result.text}\n`);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
