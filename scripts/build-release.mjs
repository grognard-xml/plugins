import { createHash } from 'node:crypto';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const packagesRoot = path.join(root, 'packages');
const releaseRoot = path.join(root, 'release');
const archiveRoot = path.join(releaseRoot, 'archives');

const sha256File = async (filePath) => {
  const hash = createHash('sha256');
  for await (const chunk of fs.createReadStream(filePath)) hash.update(chunk);
  return hash.digest('hex');
};

await fsp.rm(releaseRoot, { recursive: true, force: true });
await fsp.mkdir(archiveRoot, { recursive: true });

const plugins = [];
for (const entry of await fsp.readdir(packagesRoot, { withFileTypes: true })) {
  if (!entry.isDirectory() || entry.name === 'plugin-sdk') continue;
  const packageRoot = path.join(packagesRoot, entry.name);
  const manifestPath = path.join(packageRoot, 'plugin.manifest.json');
  if (!fs.existsSync(manifestPath)) continue;

  const manifest = JSON.parse(await fsp.readFile(manifestPath, 'utf8'));
  const archiveName = `grognard-plugin-${manifest.id}-${manifest.version}.tar.gz`;
  const archivePath = path.join(archiveRoot, archiveName);
  const stagingRoot = path.join(releaseRoot, '.staging', manifest.id);
  await fsp.rm(stagingRoot, { recursive: true, force: true });
  await fsp.mkdir(stagingRoot, { recursive: true });
  const bundled = [...new Set(['plugin.manifest.json', 'README.md', ...(manifest.bundled ?? [])])];
  const files = [];
  for (const relative of bundled) {
    const absolute = path.join(packageRoot, relative);
    // Python runtimes are downloaded for the user's platform after install;
    // never bake the builder's platform runtime into a universal archive.
    if (!fs.existsSync(absolute) && relative === 'python') continue;
    if (!fs.existsSync(absolute)) throw new Error(`${manifest.id}: bundled path is missing: ${relative}`);
    files.push(relative);
    const staged = path.join(stagingRoot, relative);
    await fsp.mkdir(path.dirname(staged), { recursive: true });
    await fsp.cp(absolute, staged, { recursive: true });
  }

  const result = spawnSync('tar', ['-czf', archivePath, manifest.id], {
    cwd: path.dirname(stagingRoot),
    encoding: 'utf8',
  });
  if (result.status !== 0) throw new Error(`Could not archive ${manifest.id}: ${result.stderr}`);

  const stat = await fsp.stat(archivePath);
  plugins.push({
    id: manifest.id,
    name: manifest.name,
    version: manifest.version,
    description: manifest.description,
    author: manifest.author,
    homepage: manifest.homepage,
    license: manifest.license,
    languages: manifest.languages ?? [],
    regions: manifest.regions ?? [],
    manifest,
    fileName: archiveName,
    bytes: stat.size,
    sha256: await sha256File(archivePath),
  });
}

await fsp.writeFile(
  path.join(releaseRoot, 'plugins-index.json'),
  `${JSON.stringify({ schemaVersion: 1, builtAt: new Date().toISOString(), plugins }, null, 2)}\n`,
);
console.log(`Built ${plugins.length} plugin archive(s) in ${releaseRoot}`);
