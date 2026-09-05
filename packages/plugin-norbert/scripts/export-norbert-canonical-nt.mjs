#!/usr/bin/env node
/**
 * Append canonical Norbert `person_nt` noble titles to the compiled asset.
 *
 * `wiki-nt-links.ndjson` previously only shipped titles matched against a
 * zh.wikipedia noble-title list-page crawl (`compile-wiki-nt-asset.mjs`).
 * That crawl only covers princely/ducal fief pages, so most emperor/founder
 * titles (nt=帝) — e.g. Liu Bei's 漢昭烈帝 — never made it into the asset even
 * though they are already on file in Norbert's own `person_nt` table.
 * Norbert's SQL is the canonical source; this script exports every
 * `person_nt` row not already covered by a wiki-matched record, independent
 * of whether a Wikipedia page exists for it.
 *
 * Re-running this script is safe: it first strips any previously exported
 * `source: "norbert-direct"` records back out, then regenerates them from
 * the current `person_nt` table and the current wiki-matched base, so it
 * never compounds duplicates across runs.
 *
 * Usage:
 *   node scripts/export-norbert-canonical-nt.mjs --sql /path/to/norbert.sql [--persons /path/to/persons.ndjson]
 *
 * The private Norbert SQL dump is a local build input only (never committed
 * to this or any repository, per docs/norbert-noble-title-autotagging-plan.md
 * in the leaf-writer repo) — there is no default path; it must be supplied.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTableRows } from '../src/wikiNobleTitles/parseSqlDump.mjs';
import { buildCanonicalNtRecords, coveredKeysFromExistingAsset } from '../src/wikiNobleTitles/exportNorbertCanonicalNt.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function arg(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const sqlPath = arg('--sql');
if (!sqlPath || !fs.existsSync(sqlPath)) {
  throw new Error(
    'Missing --sql <path-to-norbert-private-dump.sql>. The private Norbert SQL dump is not checked into any repository, so it must be supplied explicitly.',
  );
}

const defaultPersonsPath =
  '/Users/daniel/Library/Application Support/Grognard/authority-assets/authority-packs/norbert/persons.ndjson';
const personsPath = arg('--persons', defaultPersonsPath);
if (!fs.existsSync(personsPath)) {
  throw new Error(
    `Missing compiled Norbert persons pack at ${personsPath}. Pass --persons <path-to-persons.ndjson>.`,
  );
}

const outNdjson = path.resolve(__dirname, '../data/wiki-nt-links.ndjson');
const outJson = path.resolve(__dirname, '../data/wiki-nt-links.json');

// --- person_id -> asserted primary persName, from the compiled Norbert persons pack ---
/** @type {Map<string, string>} */
const personNameById = new Map();
/** @type {Map<string, string>} */
const personDisplayNameById = new Map();
for (const line of fs.readFileSync(personsPath, 'utf8').split('\n')) {
  if (!line.trim()) continue;
  const row = JSON.parse(line);
  const displayName = row.displayName ?? row.primaryName;
  if (row.authorityId && displayName) personDisplayNameById.set(String(row.authorityId), displayName);
  const primaryPersName = row.names?.find((name) => name.type === 'primary')?.text;
  if (row.authorityId && primaryPersName) personNameById.set(String(row.authorityId), primaryPersName);
}
console.log(`loaded ${personNameById.size} Norbert personal names and ${personDisplayNameById.size} display names`);

// --- person_nt, straight from the private SQL dump ---
const NT_COL = {
  ind: 0,
  person_id: 1,
  dyn: 2,
  fief: 3,
  pn: 4,
  pnAbr: 5,
  nt: 6,
  start_year: 10,
  end_year: 11,
  dyn_id: 12,
};
const rawNtRows = loadTableRows(sqlPath, 'person_nt');
const ntRows = rawNtRows.map((row) => ({
  ind: row[NT_COL.ind],
  personId: row[NT_COL.person_id],
  dyn: row[NT_COL.dyn],
  fief: row[NT_COL.fief],
  pn: row[NT_COL.pn],
  pnAbr: row[NT_COL.pnAbr],
  nt: row[NT_COL.nt],
  dynId: row[NT_COL.dyn_id],
  startYear: row[NT_COL.start_year],
  endYear: row[NT_COL.end_year],
}));
console.log(`loaded ${ntRows.length} person_nt rows`);

// --- existing asset: keep only the wiki-matched base, drop any prior canonical export ---
const existingNdjson = fs.existsSync(outNdjson)
  ? fs.readFileSync(outNdjson, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
  : [];
const base = existingNdjson.filter((r) => r.source !== 'norbert-direct');
console.log(`base wiki-matched records: ${base.length} (dropped ${existingNdjson.length - base.length} prior canonical rows)`);

const coveredKeys = coveredKeysFromExistingAsset(base);
const canonicalRecords = buildCanonicalNtRecords({
  ntRows,
  personNameById,
  personDisplayNameById,
  coveredKeys,
  startIndex: base.length,
});
console.log(`built ${canonicalRecords.length} canonical person_nt records (${ntRows.length - canonicalRecords.length - coveredKeys.size} skipped: no fief/nt or no search strings)`);

const records = [...base, ...canonicalRecords];
const actionCounts = {};
for (const r of records) actionCounts[r.action] = (actionCounts[r.action] ?? 0) + 1;

const asset = {
  id: 'norbert-wiki-nt',
  source: 'zh.wikipedia+norbert',
  assetVersion: '1',
  compiledAt: new Date().toISOString(),
  license: 'CC-BY-SA-4.0',
  attribution:
    'Noble title holders from zh.wikipedia and Norbert person_nt; Norbert person ids/names curated locally.',
  recordCount: records.length,
  actionCounts,
  records,
};

fs.writeFileSync(outNdjson, `${records.map((r) => JSON.stringify(r)).join('\n')}\n`);
fs.writeFileSync(outJson, `${JSON.stringify(asset, null, 2)}\n`);

console.log(`wrote ${outNdjson} (${asset.recordCount} records)`);
console.log(`wrote ${outJson}`);
console.log('actions:', asset.actionCounts);
