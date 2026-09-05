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
const registerSourcePath = path.join(packageRoot, 'src/register.ts');
const hostUiRel = 'packages/cwrc-leafwriter/src/plugins/hostModules/kanripoImportUi.ts';
const hostUiPath = [
  process.env.GROGNARD_HOST_ROOT,
  path.resolve(packageRoot, '../../../grognard'),
  path.resolve(packageRoot, '../../../leaf-writer'),
]
  .filter(Boolean)
  .map((root) => path.join(root, hostUiRel))
  .find((candidate) => fs.existsSync(candidate));
const worksPath = path.join(packageRoot, 'data/krp_works.json');
const bridgePath = path.join(packageRoot, 'python/kanripo_import/grognard_bridge.py');

const log = (message) => console.log(`[smoke:kanripo-import] ${message}`);
const fail = (message) => {
  console.error(`[smoke:kanripo-import] FAIL: ${message}`);
  process.exit(1);
};

log('checking manifest…');
assert.ok(fs.existsSync(manifestPath), 'plugin.manifest.json missing');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
assert.equal(manifest.id, 'kanripo-import');
assert.equal(manifest.entry.python.module, 'kanripo_import.grognard_bridge');
assert.ok(manifest.contributions?.fileMenu?.length >= 1, 'expected fileMenu item');
log('manifest OK');

log('validating manifest via plugin-sdk…');
execFileSync('node', ['../../packages/plugin-sdk/validate.mjs', manifestPath], {
  cwd: packageRoot,
  stdio: 'inherit',
});

if (!fs.existsSync(registerPath)) {
  fail('dist/register.mjs missing — run: npm run build -w @grognard/plugin-kanripo-import');
}

log('checking host UI module wiring…');
assert.ok(
  hostUiPath,
  'host UI module missing (looked for sibling grognard/ or leaf-writer/, or GROGNARD_HOST_ROOT)',
);
const hostUiSource = fs.readFileSync(hostUiPath, 'utf8');
assert.match(hostUiSource, /registerKanripoImportUi/, 'host module must export registerKanripoImportUi');
log('host UI module OK');

log('importing dist/register.mjs…');
const mod = await import(pathToFileURL(registerPath).href);
assert.equal(typeof mod.register, 'function', 'register export must be a function');

const registrations = { toolActions: [], dialogs: [], hostModuleRequested: null };
const fakeContext = {
  pluginId: 'kanripo-import',
  log: (msg) => log(`register: ${msg}`),
  registerToolAction: (action) => registrations.toolActions.push(action),
  registerDialog: (type) => registrations.dialogs.push(type),
  registerReviewPanel: () => undefined,
  registerToolbarItem: () => undefined,
  loadHostModule: async (moduleId) => {
    registrations.hostModuleRequested = moduleId;
    return {
      registerKanripoImportUi: (ctx) => {
        ctx.registerDialog('kanripoImport');
        ctx.registerToolAction('kanripo-import.open');
      },
    };
  },
};

await mod.register(fakeContext);
assert.equal(registrations.hostModuleRequested, 'kanripo-import-ui');
assert.ok(registrations.dialogs.includes('kanripoImport'));
assert.ok(registrations.toolActions.includes('kanripo-import.open'));
log('register() wiring OK');

log('checking register source…');
assert.match(fs.readFileSync(registerSourcePath, 'utf8'), /kanripo-import-ui/);
assert.ok(fs.existsSync(worksPath), 'data/krp_works.json missing');
log('checking python convert + gaiji + parallel punct…');
execFileSync('python', ['-m', 'pytest', 'python/tests', '-q'], {
  cwd: packageRoot,
  env: {
    ...process.env,
    PYTHONPATH: path.join(packageRoot, 'python'),
    GROGNARD_PLUGIN_INSTALL_PATH: packageRoot,
  },
  stdio: 'inherit',
});
const { size } = fs.statSync(registerPath);
assert.ok(size > 200 && size < 20_000, `unexpected register size ${size}`);
log('ALL PASS');
