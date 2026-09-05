#!/usr/bin/env node
/**
 * Build a distributable Daozang corpus pack (.tar.gz) from a local Fang Tongzi RAR
 * or from an already-converted utf8/ tree.
 *
 * Usage:
 *   node scripts/build-corpus-pack.mjs --from-rar ~/Downloads/DaoCanon_txt_chm.rar
 *   node scripts/build-corpus-pack.mjs --from-utf8 ./staging/utf8
 *
 * Output: release/archives/grognard-plugin-daozang-import-corpus-<version>.tar.gz
 */
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.join(__dirname, '..');
const manifest = JSON.parse(await fsp.readFile(path.join(packageRoot, 'plugin.manifest.json'), 'utf8'));
const version = manifest.version;
const releaseRoot = path.join(packageRoot, '../../release');
const archiveRoot = path.join(releaseRoot, 'archives');
const workRoot = path.join(releaseRoot, '.staging-corpus');

const args = process.argv.slice(2);
const fromRar = args.includes('--from-rar') ? args[args.indexOf('--from-rar') + 1] : null;
const fromUtf8 = args.includes('--from-utf8') ? args[args.indexOf('--from-utf8') + 1] : null;

if (!fromRar && !fromUtf8) {
  console.error('Provide --from-rar <path> or --from-utf8 <path>');
  process.exit(1);
}

await fsp.rm(workRoot, { recursive: true, force: true });
await fsp.mkdir(workRoot, { recursive: true });
await fsp.mkdir(archiveRoot, { recursive: true });

const cacheRoot = path.join(workRoot, 'cache');
await fsp.mkdir(cacheRoot, { recursive: true });

const runPythonInstall = (sourcePath) => {
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

let installResult;
if (fromRar) {
  const rarPath = path.resolve(fromRar);
  if (!fs.existsSync(rarPath)) throw new Error(`RAR not found: ${rarPath}`);
  console.log(`[build-corpus-pack] processing ${rarPath}…`);
  installResult = runPythonInstall(rarPath);
} else {
  const utf8Path = path.resolve(fromUtf8);
  if (!fs.existsSync(utf8Path)) throw new Error(`utf8 folder not found: ${utf8Path}`);
  const wrapper = path.join(workRoot, 'utf8-wrapper');
  await fsp.mkdir(wrapper, { recursive: true });
  await fsp.cp(utf8Path, path.join(wrapper, 'utf8'), { recursive: true });
  console.log(`[build-corpus-pack] indexing ${utf8Path}…`);
  installResult = runPythonInstall(wrapper);
}

const packRoot = path.join(workRoot, 'daozang-corpus');
await fsp.mkdir(packRoot, { recursive: true });
for (const name of ['utf8', 'index.json', 'manifest.json']) {
  await fsp.cp(path.join(cacheRoot, name), path.join(packRoot, name), { recursive: true });
}
const manifestData = JSON.parse(await fsp.readFile(path.join(packRoot, 'manifest.json'), 'utf8'));
manifestData.packVersion = version;
manifestData.packKind = 'grognard-daozang-corpus';
await fsp.writeFile(path.join(packRoot, 'manifest.json'), `${JSON.stringify(manifestData, null, 2)}\n`);

const archiveName = `grognard-plugin-daozang-import-corpus-${version}.tar.gz`;
const archivePath = path.join(archiveRoot, archiveName);
const tar = spawnSync('tar', ['-czf', archivePath, 'daozang-corpus'], {
  cwd: workRoot,
  encoding: 'utf8',
});
if (tar.status !== 0) throw new Error(tar.stderr || 'tar failed');

const stat = await fsp.stat(archivePath);
const hash = createHash('sha256');
hash.update(await fsp.readFile(archivePath));
console.log(`[build-corpus-pack] wrote ${archivePath}`);
console.log(`[build-corpus-pack] texts=${installResult.textCount} bytes=${stat.size} sha256=${hash.digest('hex')}`);
