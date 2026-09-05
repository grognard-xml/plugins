#!/usr/bin/env node
/**
 * Batch well-formedness + coverage check for Kanripo import + segmented parallel punct.
 *
 * Usage:
 *   node scripts/test-parallel-batch.mjs \
 *     --kanripo /path/to/KR4h0002 \
 *     --parallel /path/to/ctext-whole.txt
 *
 * Or fetch ctext inline:
 *   node scripts/test-parallel-batch.mjs \
 *     --kanripo /path/to/KR4h0002 \
 *     --ctext-url 'https://ctext.org/wiki.pl?if=gb&chapter=793335'
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.join(__dirname, '..');

const args = process.argv.slice(2);
const readFlag = (name) => {
  const index = args.indexOf(name);
  if (index === -1) return undefined;
  return args[index + 1];
};

const kanripoDir = readFlag('--kanripo');
const parallelPath = readFlag('--parallel');
const ctextUrl = readFlag('--ctext-url');
const wikisourceUrl = readFlag('--wikisource-url');
const alignMode = readFlag('--mode') || 'segmented';
const limit = Number.parseInt(readFlag('--limit') || '999', 10);

if (!kanripoDir) {
  console.error('Missing --kanripo /path/to/KR_ID directory');
  process.exit(1);
}
if (!parallelPath && !ctextUrl && !wikisourceUrl) {
  console.error('Provide --parallel, --ctext-url, or --wikisource-url');
  process.exit(1);
}

const hostPython = [
  process.env.GROGNARD_PYTHON,
  path.resolve(packageRoot, '../../../leaf-writer/apps/desktop/resources/python/bin/python3'),
  path.resolve(packageRoot, '../../../grognard/apps/desktop/resources/python/bin/python3'),
].find((candidate) => candidate && fs.existsSync(candidate));

if (!hostPython) {
  console.error('Bundled Grognard Python not found (set GROGNARD_PYTHON).');
  process.exit(1);
}

const env = {
  ...process.env,
  GROGNARD_PLUGIN_INSTALL_PATH: packageRoot,
  PYTHONPATH: path.join(packageRoot, 'python'),
};

let parallelFile = parallelPath;
if (!parallelFile && wikisourceUrl) {
  const { fetchWikisourceParallel } = await import('./wikisource-parallel.mjs');
  const result = await fetchWikisourceParallel(wikisourceUrl, { fetchAll: true });
  parallelFile = path.join(os.tmpdir(), `wikisource-parallel-${Date.now()}.txt`);
  fs.writeFileSync(parallelFile, result.text, 'utf8');
  console.error(`Fetched ${result.label} (${result.text.length} chars) → ${parallelFile}`);
}
if (!parallelFile && ctextUrl) {
  const fetchScript = path.join(packageRoot, 'scripts/fetch-ctext-parallel.mjs');
  const parallelText = execFileSync('node', [fetchScript, '--url', ctextUrl], {
    cwd: packageRoot,
    encoding: 'utf8',
    maxBuffer: 20_000_000,
  });
  parallelFile = path.join(os.tmpdir(), `ctext-parallel-${Date.now()}.txt`);
  fs.writeFileSync(parallelFile, parallelText, 'utf8');
}

const py = `
import json, sys
from pathlib import Path
from kanripo_import.kanripo_tei import convert_kanripo_txt
from kanripo_import.parallel_punct import (
    apply_parallel_punctuation,
    apply_parallel_segmented,
    assert_well_formed,
)

kanripo_dir = Path(sys.argv[1])
parallel = Path(sys.argv[2]).read_text()
mode = sys.argv[4]
apply = apply_parallel_segmented if mode == 'segmented' else apply_parallel_punctuation
rows = []
for txt in sorted(kanripo_dir.glob('*.txt'))[: int(sys.argv[3])]:
    body = convert_kanripo_txt(txt, normalize='off')['body_xml']
    result = apply(body, parallel)
    well_formed = True
    try:
        assert_well_formed(result['body_xml'])
    except Exception:
        well_formed = False
    rows.append({
        'stem': txt.stem,
        'ratio': round(result['coverage']['ratio'], 4),
        'applied': result['applied'],
        'well_formed': well_formed,
        'covered_chars': result['coverage']['covered_chars'],
        'total_chars': result['coverage']['total_chars'],
    })
print(json.dumps(rows))
`;

const stdout = execFileSync(
  hostPython,
  ['-c', py, kanripoDir, parallelFile, String(limit), alignMode],
  { env, encoding: 'utf8', maxBuffer: 50_000_000 },
);

const rows = JSON.parse(stdout);
let failed = 0;
for (const row of rows) {
  const pct = row.total_chars
    ? `${Math.round(row.ratio * 100)}% (${row.covered_chars}/${row.total_chars})`
    : '0%';
  const status = row.well_formed ? 'ok' : 'MALFORMED';
  if (!row.well_formed) failed += 1;
  console.log(`${row.stem}\t${pct}\tapplied=${row.applied}\t${status}`);
}

if (failed) {
  console.error(`\n${failed} juan produced malformed XML — import must fail closed on these.`);
  process.exit(1);
}

console.log(`\nAll ${rows.length} juan well-formed.`);
