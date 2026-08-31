#!/usr/bin/env node
/**
 * Build bundled plugin corpus data under data/corpus/xml-p5 (git clone at DATA_VERSION_TAG).
 *
 * Usage:
 *   node scripts/build-corpus-data.mjs
 *   node scripts/build-corpus-data.mjs --from-dir ~/checkouts/cbeta-xml-p5
 */
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.join(__dirname, '..');
const corpusRoot = path.join(packageRoot, 'data', 'corpus', 'xml-p5');
const dataRoot = path.join(packageRoot, 'data');

const args = process.argv.slice(2);
const fromDir = args.includes('--from-dir') ? args[args.indexOf('--from-dir') + 1] : null;

const runPython = (payload) => {
  const result = spawnSync(
    'python3',
    ['-c', 'from cbeta_import.ljb_bridge import cli_main; cli_main()'],
    {
      cwd: packageRoot,
      input: JSON.stringify(payload),
      encoding: 'utf8',
      env: {
        ...process.env,
        PYTHONPATH: path.join(packageRoot, 'python'),
        LJB_PLUGIN_INSTALL_PATH: packageRoot,
      },
    },
  );
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || 'Python corpus setup failed');
  }
  return JSON.parse(result.stdout.trim());
};

await fsp.rm(corpusRoot, { recursive: true, force: true });
await fsp.mkdir(path.dirname(corpusRoot), { recursive: true });

let installResult;
if (fromDir) {
  const source = path.resolve(fromDir);
  if (!fs.existsSync(source)) throw new Error(`Source not found: ${source}`);
  console.log(`[build-corpus-data] installing from ${source}…`);
  installResult = runPython({ op: 'install_from_source', source_path: source });
} else {
  console.log('[build-corpus-data] cloning cbeta-org/xml-p5 from GitHub…');
  installResult = runPython({ op: 'sync' });
}

const manifestPath = path.join(dataRoot, 'corpus.json');
if (fs.existsSync(manifestPath)) {
  const manifest = JSON.parse(await fsp.readFile(manifestPath, 'utf8'));
  manifest.packKind = 'ljb-cbeta-bundled';
  manifest.bundled = true;
  await fsp.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
}

console.log(`[build-corpus-data] wrote ${corpusRoot}`);
console.log(`[build-corpus-data] action=${installResult.action ?? installResult.kind ?? 'ok'}`);
