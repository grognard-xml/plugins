#!/usr/bin/env node
/**
 * Downloads relocatable CPython + sanmiao into this plugin's python/ folder.
 */
import { existsSync, mkdirSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'fs';
import { createWriteStream } from 'fs';
import { pipeline } from 'stream/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { execFileSync } from 'child_process';
import { fetchWithRetry } from './retryable-fetch.mjs';

const PBS_TAG = '20260623';
const PYTHON_VERSION = '3.12.13';
const SANMIAO_SPEC = 'sanmiao[fuzzy]==0.2.10';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RESOURCES_DIR = path.join(__dirname, '../python');

const TARGETS = {
  'darwin-arm64': 'aarch64-apple-darwin',
  'darwin-x64': 'x86_64-apple-darwin',
  'linux-arm64': 'aarch64-unknown-linux-gnu',
  'linux-x64': 'x86_64-unknown-linux-gnu',
  'win32-arm64': 'aarch64-pc-windows-msvc',
  'win32-x64': 'x86_64-pc-windows-msvc',
};

const platform = process.env.GROGNARD_PYTHON_PLATFORM || process.platform;
const arch = process.env.GROGNARD_PYTHON_ARCH || process.arch;

const target = TARGETS[`${platform}-${arch}`];
if (!target) {
  console.error(`[cjk-dates python] Unsupported platform: ${platform}-${arch}`);
  process.exit(1);
}

const asset = `cpython-${PYTHON_VERSION}+${PBS_TAG}-${target}-install_only.tar.gz`;
const url = `https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${asset}`;

const pythonBin =
  process.platform === 'win32'
    ? path.join(RESOURCES_DIR, 'python.exe')
    : path.join(RESOURCES_DIR, 'bin', 'python3');
const stampPath = path.join(RESOURCES_DIR, '.deps-installed');
const stamp = `${asset} ${SANMIAO_SPEC}`;

if (
  existsSync(pythonBin) &&
  existsSync(stampPath) &&
  readFileSync(stampPath, 'utf-8').trim() === stamp
) {
  console.log(`[cjk-dates python] Already present: ${pythonBin}`);
  process.exit(0);
}

rmSync(RESOURCES_DIR, { recursive: true, force: true });
mkdirSync(RESOURCES_DIR, { recursive: true });

const tarPath = path.join(RESOURCES_DIR, asset);
console.log(`[cjk-dates python] Downloading ${url}`);
const response = await fetchWithRetry(url, undefined, { label: '[cjk-dates python] download' });
await pipeline(response.body, createWriteStream(tarPath));

console.log(`[cjk-dates python] Extracting ${asset}`);
execFileSync('tar', ['-xzf', tarPath, '-C', RESOURCES_DIR, '--strip-components=1'], {
  stdio: 'inherit',
});
unlinkSync(tarPath);

console.log(`[cjk-dates python] Installing ${SANMIAO_SPEC}`);
execFileSync(
  pythonBin,
  [
    '-m',
    'pip',
    'install',
    '--no-warn-script-location',
    '--disable-pip-version-check',
    '--retries',
    '5',
    '--timeout',
    '60',
    SANMIAO_SPEC,
  ],
  { stdio: 'inherit' },
);

writeFileSync(stampPath, `${stamp}\n`);
console.log(`[cjk-dates python] Ready: ${pythonBin}`);
