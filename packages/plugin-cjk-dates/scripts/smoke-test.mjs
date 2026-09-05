#!/usr/bin/env node
/**
 * Smoke test for plugin-cjk-dates (no Electron required).
 *
 * Run from plugins repo root:
 *   npm run build:cjk-dates && npm run smoke:cjk-dates
 */
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
const hostUiRel = 'packages/cwrc-leafwriter/src/plugins/hostModules/cjkDatesUi.ts';
const hostUiPath = [
  process.env.GROGNARD_HOST_ROOT,
  path.resolve(packageRoot, '../../../leaf-writer'),
  path.resolve(packageRoot, '../../../grognard'),
]
  .filter(Boolean)
  .map((root) => path.join(root, hostUiRel))
  .find((candidate) => fs.existsSync(candidate));
const pythonScript = path.join(packageRoot, 'scripts/download-python-runtime.mjs');

const log = (message) => console.log(`[smoke:cjk-dates] ${message}`);
const fail = (message) => {
  console.error(`[smoke:cjk-dates] FAIL: ${message}`);
  process.exit(1);
};

log('checking manifest…');
assert.ok(fs.existsSync(manifestPath), 'plugin.manifest.json missing');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
assert.equal(manifest.id, 'cjk-dates');
assert.equal(manifest.entry.python.module, 'sanmiao.tei_bridge');
assert.ok(manifest.contributions?.autoTagging?.length >= 2, 'expected autoTagging producers');
assert.ok(manifest.contributions?.toolsMenu?.length >= 1, 'expected toolsMenu item');
log('manifest OK');

log('validating manifest via plugin-sdk…');
execFileSync('node', ['../../packages/plugin-sdk/validate.mjs', manifestPath], {
  cwd: packageRoot,
  stdio: 'inherit',
});

if (!fs.existsSync(registerPath)) {
  fail('dist/register.mjs missing — run: npm run build -w @grognard/plugin-cjk-dates');
}

log('checking host UI module wiring…');
assert.ok(
  hostUiPath,
  'host UI module missing (leaf-writer sibling, grognard sibling, or GROGNARD_HOST_ROOT)',
);
const hostUiSource = fs.readFileSync(hostUiPath, 'utf8');
assert.match(hostUiSource, /registerCjkDatesUi/, 'host module must export registerCjkDatesUi');
assert.match(hostUiSource, /registerDialog\('calendar'/, 'host module must register calendar dialog');
assert.match(hostUiSource, /registerToolbarItem/, 'host module must register toolbar item');
log('host UI module OK');

log('importing dist/register.mjs…');
const mod = await import(pathToFileURL(registerPath).href);
assert.equal(typeof mod.register, 'function', 'register export must be a function');

const registrations = {
  dialogs: [],
  reviewPanels: [],
  toolbarItems: [],
  toolActions: [],
  hostModuleRequested: null,
};

const fakeContext = {
  pluginId: 'cjk-dates',
  log: (msg) => log(`register: ${msg}`),
  registerToolAction: (action) => registrations.toolActions.push(action),
  registerDialog: (type) => registrations.dialogs.push(type),
  registerReviewPanel: (matcher) => registrations.reviewPanels.push(typeof matcher),
  registerToolbarItem: (item) => registrations.toolbarItems.push(item.id),
  loadHostModule: async (moduleId) => {
    registrations.hostModuleRequested = moduleId;
    return {
      registerCjkDatesUi: (ctx) => {
        ctx.registerDialog('calendar');
        ctx.registerReviewPanel(() => true);
        ctx.registerReviewPanel(() => false);
        ctx.registerToolbarItem({ id: 'calendar' });
        ctx.registerToolAction('cjk-dates.open-curator');
        ctx.onEnable = () => {};
        ctx.onDisable = () => {};
      },
    };
  },
};

await mod.register(fakeContext);
assert.equal(registrations.hostModuleRequested, 'cjk-dates-ui', 'must request cjk-dates-ui host module');
assert.ok(registrations.dialogs.includes('calendar'), 'must register calendar dialog');
assert.equal(registrations.toolActions.includes('cjk-dates.open-curator'), true, 'must register tool action');
assert.ok(registrations.reviewPanels.length >= 2, 'must register date review panels');
assert.ok(registrations.toolbarItems.includes('calendar'), 'must register calendar toolbar item');
log('register() wiring OK');

log('checking plugin register source…');
const registerSource = fs.readFileSync(registerSourcePath, 'utf8');
assert.match(registerSource, /cjk-dates-ui/, 'register.ts must delegate to host UI');
log('register source OK');

log('checking python download script…');
assert.ok(fs.existsSync(pythonScript), 'scripts/download-python-runtime.mjs missing');
const pythonScriptSource = fs.readFileSync(pythonScript, 'utf8');
assert.match(pythonScriptSource, /sanmiao\[fuzzy\]/, 'python script must install sanmiao');
log('python script OK');

log('checking bundled register size…');
const { size } = fs.statSync(registerPath);
assert.ok(size > 200, `dist/register.mjs looks too small (${size} bytes)`);
assert.ok(size < 20_000, `dist/register.mjs looks unexpectedly large (${size} bytes)`);
log(`dist/register.mjs ${(size / 1024).toFixed(1)} KB`);

log('ALL PASS');
