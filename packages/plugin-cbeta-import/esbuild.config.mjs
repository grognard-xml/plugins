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
  path.join(packageRoot, '../../../leaf-writer/node_modules/esbuild'),
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
  console.error('[plugin-cbeta-import] esbuild not found. Run: npm install (in plugins/)');
  process.exit(1);
}

await esbuild.build({
  absWorkingDir: packageRoot,
  entryPoints: [path.join(packageRoot, 'src/register.ts')],
  outfile: path.join(packageRoot, 'dist/register.mjs'),
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  sourcemap: true,
  logLevel: 'info',
});

console.log('[plugin-cbeta-import] Built dist/register.mjs');
