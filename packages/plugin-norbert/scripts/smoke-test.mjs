#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.join(__dirname, '..');
const registerPath = path.join(packageRoot, 'dist/register.mjs');

if (!fs.existsSync(registerPath)) {
  console.error('dist/register.mjs missing — run: npm run build -w @ljb/plugin-norbert');
  process.exit(1);
}

const mod = await import(pathToFileURL(registerPath).href);
assert.equal(typeof mod.register, 'function');

let registered = false;
await mod.register({
  pluginId: 'norbert',
  log: (msg) => console.log(`[smoke] ${msg}`),
  registerPersonNameSegmenter: (fn) => {
    registered = true;
    const result = fn({
      name: '王安石',
      projectLang: 'zh-Hans',
      romanize: (part) => (part === '王' ? 'Wang' : part === '安石' ? 'Anshi' : null),
    });
    assert.deepEqual(result, {
      familyName: '王',
      givenName: '安石',
      romanizedName: 'Wang Anshi',
    });
  },
  loadHostModule: async () => ({
    registerNorbertNobleTitleUi: () => undefined,
  }),
  registerToolAction: () => undefined,
  registerDialog: () => undefined,
  registerReviewPanel: () => undefined,
  registerToolbarItem: () => undefined,
});

assert.equal(registered, true);
console.log('[smoke:norbert] ALL PASS');
