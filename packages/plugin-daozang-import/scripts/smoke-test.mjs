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
const hostUiRel = 'packages/cwrc-leafwriter/src/plugins/hostModules/daozangImportUi.ts';
const hostUiPath = [
  process.env.GROGNARD_HOST_ROOT,
  path.resolve(packageRoot, '../../../leaf-writer'),
]
  .filter(Boolean)
  .map((root) => path.join(root, hostUiRel))
  .find((candidate) => fs.existsSync(candidate));

const log = (message) => console.log(`[smoke:daozang-import] ${message}`);
const fail = (message) => {
  console.error(`[smoke:daozang-import] FAIL: ${message}`);
  process.exit(1);
};

log('checking manifest…');
assert.ok(fs.existsSync(manifestPath), 'plugin.manifest.json missing');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
assert.equal(manifest.id, 'daozang-import');
assert.equal(manifest.entry.python.module, 'daozang_import.grognard_bridge');
assert.ok(manifest.contributions?.fileMenu?.length >= 1, 'expected fileMenu item');
log('manifest OK');

log('validating manifest via plugin-sdk…');
execFileSync('node', ['../../packages/plugin-sdk/validate.mjs', manifestPath], {
  cwd: packageRoot,
  stdio: 'inherit',
});

if (!fs.existsSync(registerPath)) {
  fail('dist/register.mjs missing — run: npm run build -w @grognard/plugin-daozang-import');
}

log('checking host UI module wiring…');
assert.ok(hostUiPath, 'host UI module missing (leaf-writer sibling or GROGNARD_HOST_ROOT)');
const hostUiSource = fs.readFileSync(hostUiPath, 'utf8');
assert.match(hostUiSource, /registerDaozangImportUi/, 'host module must export registerDaozangImportUi');
log('host UI module OK');

log('importing dist/register.mjs…');
const mod = await import(pathToFileURL(registerPath).href);
assert.equal(typeof mod.register, 'function', 'register export must be a function');

const registrations = { toolActions: [], dialogs: [], hostModuleRequested: null };
const fakeContext = {
  pluginId: 'daozang-import',
  log: (msg) => log(`register: ${msg}`),
  registerToolAction: (action) => registrations.toolActions.push(action),
  registerDialog: (type) => registrations.dialogs.push(type),
  registerReviewPanel: () => undefined,
  registerToolbarItem: () => undefined,
  loadHostModule: async (moduleId) => {
    registrations.hostModuleRequested = moduleId;
    return {
      registerDaozangImportUi: (ctx) => {
        ctx.registerDialog('daozangImport');
        ctx.registerToolAction('daozang-import.open');
      },
    };
  },
};

await mod.register(fakeContext);
assert.equal(registrations.hostModuleRequested, 'daozang-import-ui');
assert.ok(registrations.dialogs.includes('daozangImport'));
assert.ok(registrations.toolActions.includes('daozang-import.open'));
log('register() wiring OK');

log('checking python tests…');
execFileSync('python3', ['-m', 'unittest', 'discover', '-s', 'python/tests', '-p', 'test_*.py', '-q'], {
  cwd: packageRoot,
  env: {
    ...process.env,
    PYTHONPATH: path.join(packageRoot, 'python'),
  },
  stdio: 'inherit',
});
log('ALL PASS');
