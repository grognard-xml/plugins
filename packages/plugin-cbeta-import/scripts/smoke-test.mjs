#!/usr/bin/env node
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.join(__dirname, '..');
const manifestPath = path.join(packageRoot, 'plugin.manifest.json');
const registerPath = path.join(packageRoot, 'dist/register.mjs');
const hostUiRel = 'packages/cwrc-leafwriter/src/plugins/hostModules/cbetaImportUi.ts';
const hostUiPath = [process.env.GROGNARD_HOST_ROOT, path.resolve(packageRoot, '../../../leaf-writer')]
  .filter(Boolean)
  .map((root) => path.join(root, hostUiRel))
  .find((candidate) => fs.existsSync(candidate));

const log = (message) => console.log(`[smoke:cbeta-import] ${message}`);
const warn = (message) => console.warn(`[smoke:cbeta-import] WARN: ${message}`);
const fail = (message) => {
  console.error(`[smoke:cbeta-import] FAIL: ${message}`);
  process.exit(1);
};

log('checking manifest…');
assert.ok(fs.existsSync(manifestPath), 'plugin.manifest.json missing');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
assert.equal(manifest.id, 'cbeta-import');
assert.equal(manifest.entry.python.module, 'cbeta_import.grognard_bridge');
assert.ok(manifest.contributions?.fileMenu?.length >= 1, 'expected fileMenu item');
log('manifest OK');

log('validating manifest via plugin-sdk…');
execFileSync('node', ['../../packages/plugin-sdk/validate.mjs', manifestPath], {
  cwd: packageRoot,
  stdio: 'inherit',
});

if (!fs.existsSync(registerPath)) {
  fail('dist/register.mjs missing — run: npm run build -w @grognard/plugin-cbeta-import');
}

log('checking host UI module wiring…');
if (!hostUiPath) {
  // TODO: create packages/cwrc-leafwriter/src/plugins/hostModules/cbetaImportUi.ts
  // (mirror daozangImportUi.ts) + a CbetaImportDialog + an index.ts loader entry.
  warn('host UI module cbetaImportUi.ts not present yet — host-side follow-up');
} else {
  const hostUiSource = fs.readFileSync(hostUiPath, 'utf8');
  assert.match(hostUiSource, /registerCbetaImportUi/, 'host module must export registerCbetaImportUi');
  log('host UI module OK');
}

log('importing dist/register.mjs…');
const mod = await import(pathToFileURL(registerPath).href);
assert.equal(typeof mod.register, 'function', 'register export must be a function');

const registrations = { toolActions: [], dialogs: [], hostModuleRequested: null };
const fakeContext = {
  pluginId: 'cbeta-import',
  log: (msg) => log(`register: ${msg}`),
  registerToolAction: (action) => registrations.toolActions.push(action),
  registerDialog: (type) => registrations.dialogs.push(type),
  registerReviewPanel: () => undefined,
  registerToolbarItem: () => undefined,
  loadHostModule: async (moduleId) => {
    registrations.hostModuleRequested = moduleId;
    return {
      registerCbetaImportUi: (ctx) => {
        ctx.registerDialog('cbetaImport');
        ctx.registerToolAction('cbeta-import.open');
      },
    };
  },
};

await mod.register(fakeContext);
assert.equal(registrations.hostModuleRequested, 'cbeta-import-ui');
assert.ok(registrations.dialogs.includes('cbetaImport'));
assert.ok(registrations.toolActions.includes('cbeta-import.open'));
log('register() wiring OK');

log('checking python tests…');
execFileSync('python3', ['-m', 'unittest', 'discover', '-s', 'python/tests', '-p', 'test_*.py', '-q'], {
  cwd: packageRoot,
  env: { ...process.env, PYTHONPATH: path.join(packageRoot, 'python') },
  stdio: 'inherit',
});
log('ALL PASS');
