#!/usr/bin/env node
/**
 * Ensure every plugin.manifest.json bundled path exists before release archives are built.
 */
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const packagesRoot = path.join(root, 'packages');

let failed = false;

for (const entry of await fsp.readdir(packagesRoot, { withFileTypes: true })) {
  if (!entry.isDirectory() || entry.name === 'plugin-sdk') continue;
  const packageRoot = path.join(packagesRoot, entry.name);
  const manifestPath = path.join(packageRoot, 'plugin.manifest.json');
  if (!fs.existsSync(manifestPath)) continue;

  const manifest = JSON.parse(await fsp.readFile(manifestPath, 'utf8'));
  const bundled = [...new Set(['plugin.manifest.json', 'README.md', ...(manifest.bundled ?? [])])];
  for (const relative of bundled) {
    if (relative === 'python' && !fs.existsSync(path.join(packageRoot, relative))) {
      console.log(`[verify-bundled] ${manifest.id}: skip optional missing ${relative}`);
      continue;
    }
    const absolute = path.join(packageRoot, relative);
    if (!fs.existsSync(absolute)) {
      console.error(`[verify-bundled] ${manifest.id}: missing bundled path: ${relative}`);
      failed = true;
    }
  }
}

if (failed) {
  console.error('[verify-bundled] Fix missing paths (see READMEs for build:corpus-data, download:gaiji, build:metadata, etc.)');
  process.exit(1);
}

console.log('[verify-bundled] all bundled paths present');
