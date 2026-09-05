#!/usr/bin/env node
/**
 * Build bundled plugin corpus data under data/corpus/ (utf8, index.json, manifest.json).
 *
 * Usage:
 *   node scripts/build-corpus-data.mjs --from-rar ~/Downloads/DaoCanon_txt_chm.rar
 *   node scripts/build-corpus-data.mjs --from-utf8 ~/Downloads/DaoCanon_txt_chm/道藏_txt
 */
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.join(__dirname, '..');
const corpusRoot = path.join(packageRoot, 'data', 'corpus');

const args = process.argv.slice(2);
const fromRar = args.includes('--from-rar') ? args[args.indexOf('--from-rar') + 1] : null;
const fromUtf8 = args.includes('--from-utf8') ? args[args.indexOf('--from-utf8') + 1] : null;

if (!fromRar && !fromUtf8) {
  console.error('Provide --from-rar <path> or --from-utf8 <path>');
  process.exit(1);
}

const runPythonInstall = (sourcePath, cacheRoot) => {
  const payload = JSON.stringify({
    op: 'install_from_source',
    cache_root: cacheRoot,
    source_path: sourcePath,
  });
  const result = spawnSync(
    'python3',
    ['-c', 'from daozang_import.grognard_bridge import cli_main; cli_main()'],
    {
      cwd: packageRoot,
      input: payload,
      encoding: 'utf8',
      env: {
        ...process.env,
        PYTHONPATH: path.join(packageRoot, 'python'),
      },
    },
  );
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || 'Python install_from_source failed');
  }
  return JSON.parse(result.stdout.trim());
};

await fsp.rm(corpusRoot, { recursive: true, force: true });
await fsp.mkdir(corpusRoot, { recursive: true });

const stagingCache = path.join(corpusRoot, '.build-cache');
await fsp.mkdir(stagingCache, { recursive: true });

let installResult;
if (fromRar) {
  const rarPath = path.resolve(fromRar);
  if (!fs.existsSync(rarPath)) throw new Error(`RAR not found: ${rarPath}`);
  console.log(`[build-corpus-data] processing ${rarPath}…`);
  installResult = runPythonInstall(rarPath, stagingCache);
} else {
  const utf8Path = path.resolve(fromUtf8);
  if (!fs.existsSync(utf8Path)) throw new Error(`utf8 folder not found: ${utf8Path}`);
  const wrapper = path.join(stagingCache, 'wrapper');
  await fsp.mkdir(wrapper, { recursive: true });
  await fsp.cp(utf8Path, path.join(wrapper, 'utf8'), { recursive: true });
  console.log(`[build-corpus-data] indexing ${utf8Path}…`);
  installResult = runPythonInstall(wrapper, stagingCache);
}

for (const name of ['utf8', 'index.json', 'manifest.json']) {
  await fsp.cp(path.join(stagingCache, name), path.join(corpusRoot, name), { recursive: true });
}
await fsp.rm(stagingCache, { recursive: true, force: true });

const manifestPath = path.join(corpusRoot, 'manifest.json');
const manifest = JSON.parse(await fsp.readFile(manifestPath, 'utf8'));
manifest.packKind = 'grognard-daozang-bundled';
manifest.bundled = true;
await fsp.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

const utf8Stat = await fsp.stat(path.join(corpusRoot, 'utf8'));
console.log(`[build-corpus-data] wrote ${corpusRoot}`);
console.log(`[build-corpus-data] texts=${installResult.textCount}`);
