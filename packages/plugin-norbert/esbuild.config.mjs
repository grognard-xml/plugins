#!/usr/bin/env node
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = __dirname;
const require = createRequire(import.meta.url);

const esbuildRootCandidates = [
  path.join(packageRoot, 'node_modules/esbuild'),
  path.join(packageRoot, '../../node_modules/esbuild'),
  path.join(packageRoot, '../../../grognard/node_modules/esbuild'),
];
let esbuild;
for (const candidate of esbuildRootCandidates) {
  try {
    esbuild = require(candidate);
    break;
  } catch {
    // try next
  }
}
if (!esbuild) {
  console.error('[plugin-norbert] esbuild not found. Run: npm install (in plugins/)');
  process.exit(1);
}

await esbuild.build({
  absWorkingDir: packageRoot,
  entryPoints: [path.join(packageRoot, 'src/register.mjs')],
  outfile: path.join(packageRoot, 'dist/register.mjs'),
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  sourcemap: true,
  logLevel: 'info',
  loader: { '.json': 'json' },
});

console.log('[plugin-norbert] Built dist/register.mjs');
