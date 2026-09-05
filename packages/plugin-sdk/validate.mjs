import { PLUGIN_MANIFEST_VERSION } from './types.mjs';

const ID_RE = /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/;
const SEMVER_RE = /^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/;

/**
 * @param {unknown} value
 * @param {string} path
 * @returns {string[]}
 */
function requireString(value, path) {
  if (typeof value !== 'string' || !value.trim()) return [`${path} must be a non-empty string`];
  return [];
}

/**
 * @param {unknown} value
 * @param {string} path
 * @returns {string[]}
 */
function requireStringArray(value, path) {
  if (!Array.isArray(value)) return [`${path} must be an array`];
  /** @type {string[]} */
  const errors = [];
  for (let i = 0; i < value.length; i += 1) {
    errors.push(...requireString(value[i], `${path}[${i}]`));
  }
  return errors;
}

/**
 * @param {Record<string, unknown>} obj
 * @param {string[]} allowed
 * @param {string} path
 */
function rejectUnknownKeys(obj, allowed, path) {
  return Object.keys(obj)
    .filter((k) => !allowed.includes(k))
    .map((k) => `${path}.${k} is not allowed`);
}

/**
 * @param {unknown} manifest
 * @returns {{ ok: true, manifest: import('./types.mjs').PluginManifest } | { ok: false, errors: string[] }}
 */
export function validatePluginManifest(manifest) {
  /** @type {string[]} */
  const errors = [];

  if (!manifest || typeof manifest !== 'object') {
    return { ok: false, errors: ['manifest must be an object'] };
  }

  /** @type {Record<string, unknown>} */
  const m = /** @type {Record<string, unknown>} */ (manifest);

  errors.push(...rejectUnknownKeys(m, [
    'manifestVersion', 'id', 'name', 'version', 'description', 'author', 'homepage',
    'license', 'grognard', 'languages', 'regions', 'languagePrompt', 'entry',
    'contributions', 'dependencies', 'bundled',
  ], 'manifest'));

  if (m.manifestVersion !== PLUGIN_MANIFEST_VERSION) {
    errors.push(`manifestVersion must be ${PLUGIN_MANIFEST_VERSION}`);
  }

  errors.push(...requireString(m.id, 'id'));
  if (typeof m.id === 'string' && !ID_RE.test(m.id)) {
    errors.push('id must be kebab-case');
  }

  errors.push(...requireString(m.name, 'name'));
  errors.push(...requireString(m.version, 'version'));
  if (typeof m.version === 'string' && !SEMVER_RE.test(m.version)) {
    errors.push('version must be semver');
  }
  errors.push(...requireString(m.description, 'description'));
  errors.push(...requireString(m.license, 'license'));

  if (m.author != null) errors.push(...requireString(m.author, 'author'));
  if (m.homepage != null) errors.push(...requireString(m.homepage, 'homepage'));

  if (!m.grognard || typeof m.grognard !== 'object') {
    errors.push('grognard must be an object');
  } else {
    errors.push(...rejectUnknownKeys(/** @type {Record<string, unknown>} */ (m.grognard), ['minVersion', 'maxVersion'], 'grognard'));
    errors.push(...requireString(/** @type {Record<string, unknown>} */ (m.grognard).minVersion, 'grognard.minVersion'));
    if (/** @type {Record<string, unknown>} */ (m.grognard).maxVersion != null) {
      errors.push(...requireString(/** @type {Record<string, unknown>} */ (m.grognard).maxVersion, 'grognard.maxVersion'));
    }
  }

  if (m.languages != null) errors.push(...requireStringArray(m.languages, 'languages'));
  if (m.regions != null) {
    if (!Array.isArray(m.regions)) errors.push('regions must be an array');
    else {
      const allowed = new Set(['east-asia', 'china', 'japan', 'korea']);
      for (const region of m.regions) {
        if (!allowed.has(region)) errors.push(`regions contains invalid value: ${region}`);
      }
    }
  }

  if (m.languagePrompt != null) {
    if (typeof m.languagePrompt !== 'object') errors.push('languagePrompt must be an object');
    else {
      const lp = /** @type {Record<string, unknown>} */ (m.languagePrompt);
      errors.push(...rejectUnknownKeys(lp, ['message', 'documentLanguages'], 'languagePrompt'));
      errors.push(...requireString(lp.message, 'languagePrompt.message'));
      if (lp.documentLanguages != null) {
        errors.push(...requireStringArray(lp.documentLanguages, 'languagePrompt.documentLanguages'));
      }
    }
  }

  if (!m.entry || typeof m.entry !== 'object') {
    errors.push('entry must be an object');
  } else {
    const entry = /** @type {Record<string, unknown>} */ (m.entry);
    errors.push(...rejectUnknownKeys(entry, ['kind', 'module', 'python'], 'entry'));
    const kind = entry.kind;
    if (!['javascript', 'python', 'hybrid'].includes(/** @type {string} */ (kind))) {
      errors.push('entry.kind must be javascript, python, or hybrid');
    }
    if ((kind === 'javascript' || kind === 'hybrid') && typeof entry.module !== 'string') {
      errors.push('entry.module is required for javascript/hybrid plugins');
    }
    if (kind === 'python' || kind === 'hybrid') {
      if (!entry.python || typeof entry.python !== 'object') {
        errors.push('entry.python is required for python/hybrid plugins');
      } else {
        const py = /** @type {Record<string, unknown>} */ (entry.python);
        errors.push(...rejectUnknownKeys(py, ['module', 'runtime', 'runtimePath'], 'entry.python'));
        errors.push(...requireString(py.module, 'entry.python.module'));
      }
    }
  }

  if (m.contributions != null) {
    if (typeof m.contributions !== 'object') errors.push('contributions must be an object');
    else validateContributions(/** @type {Record<string, unknown>} */ (m.contributions), errors);
  }

  if (m.dependencies != null) {
    if (typeof m.dependencies !== 'object') errors.push('dependencies must be an object');
    else {
      const deps = /** @type {Record<string, unknown>} */ (m.dependencies);
      errors.push(...rejectUnknownKeys(deps, ['plugins'], 'dependencies'));
      if (deps.plugins != null) {
        errors.push(...requireStringArray(deps.plugins, 'dependencies.plugins'));
        for (const pluginId of /** @type {string[]} */ (deps.plugins)) {
          if (!ID_RE.test(pluginId)) errors.push(`dependencies.plugins contains invalid id: ${pluginId}`);
        }
      }
    }
  }

  if (m.bundled != null) errors.push(...requireStringArray(m.bundled, 'bundled'));

  if (errors.length) return { ok: false, errors };
  return { ok: true, manifest: /** @type {import('./types.mjs').PluginManifest} */ (manifest) };
}

/**
 * @param {Record<string, unknown>} contributions
 * @param {string[]} errors
 */
function validateContributions(contributions, errors) {
  errors.push(...rejectUnknownKeys(contributions, [
    'toolsMenu', 'fileMenu', 'autoTagging', 'authorityPacks', 'settingsSections', 'disambiguation',
  ], 'contributions'));

  if (contributions.toolsMenu != null) {
    if (!Array.isArray(contributions.toolsMenu)) errors.push('contributions.toolsMenu must be an array');
    else {
      for (const [i, item] of contributions.toolsMenu.entries()) {
        validateToolsMenuItem(item, `contributions.toolsMenu[${i}]`, errors);
      }
    }
  }

  if (contributions.fileMenu != null) {
    if (!Array.isArray(contributions.fileMenu)) errors.push('contributions.fileMenu must be an array');
    else {
      for (const [i, item] of contributions.fileMenu.entries()) {
        validateToolsMenuItem(item, `contributions.fileMenu[${i}]`, errors);
      }
    }
  }

  if (contributions.autoTagging != null) {
    if (!Array.isArray(contributions.autoTagging)) errors.push('contributions.autoTagging must be an array');
    else {
      for (const [i, item] of contributions.autoTagging.entries()) {
        validateAutoTaggingProducer(item, `contributions.autoTagging[${i}]`, errors);
      }
    }
  }

  if (contributions.authorityPacks != null) {
    if (!Array.isArray(contributions.authorityPacks)) {
      errors.push('contributions.authorityPacks must be an array');
    } else {
      for (const [i, item] of contributions.authorityPacks.entries()) {
        validateAuthorityPack(item, `contributions.authorityPacks[${i}]`, errors);
      }
    }
  }

  if (contributions.settingsSections != null) {
    if (!Array.isArray(contributions.settingsSections)) {
      errors.push('contributions.settingsSections must be an array');
    } else {
      for (const [i, item] of contributions.settingsSections.entries()) {
        validateSettingsSection(item, `contributions.settingsSections[${i}]`, errors);
      }
    }
  }

  if (contributions.disambiguation != null) {
    if (!Array.isArray(contributions.disambiguation)) {
      errors.push('contributions.disambiguation must be an array');
    } else {
      for (const [i, item] of contributions.disambiguation.entries()) {
        validateDisambiguation(item, `contributions.disambiguation[${i}]`, errors);
      }
    }
  }
}

/**
 * @param {unknown} item
 * @param {string} path
 * @param {string[]} errors
 */
function validateToolsMenuItem(item, path, errors) {
  if (!item || typeof item !== 'object') {
    errors.push(`${path} must be an object`);
    return;
  }
  const obj = /** @type {Record<string, unknown>} */ (item);
  errors.push(...rejectUnknownKeys(obj, ['id', 'label', 'action', 'separatorBefore'], path));
  errors.push(...requireString(obj.id, `${path}.id`));
  errors.push(...requireString(obj.label, `${path}.label`));
  if (typeof obj.id === 'string' && !ID_RE.test(obj.id)) errors.push(`${path}.id must be kebab-case`);
}

/**
 * @param {unknown} item
 * @param {string} path
 * @param {string[]} errors
 */
function validateAutoTaggingProducer(item, path, errors) {
  if (!item || typeof item !== 'object') {
    errors.push(`${path} must be an object`);
    return;
  }
  const obj = /** @type {Record<string, unknown>} */ (item);
  errors.push(...rejectUnknownKeys(obj, ['id', 'label', 'description', 'kind', 'defaultEnabled', 'tags'], path));
  errors.push(...requireString(obj.id, `${path}.id`));
  errors.push(...requireString(obj.label, `${path}.label`));
  errors.push(...requireString(obj.kind, `${path}.kind`));
  const allowed = new Set(['dates', 'authority-tag-bomb', 'contextual-disambiguation', 'pattern-tag', 'custom']);
  if (typeof obj.kind === 'string' && !allowed.has(obj.kind)) errors.push(`${path}.kind is invalid`);
}

/**
 * @param {unknown} item
 * @param {string} path
 * @param {string[]} errors
 */
function validateAuthorityPack(item, path, errors) {
  if (!item || typeof item !== 'object') {
    errors.push(`${path} must be an object`);
    return;
  }
  const obj = /** @type {Record<string, unknown>} */ (item);
  errors.push(...rejectUnknownKeys(obj, ['id', 'label', 'defaultTag', 'install'], path));
  errors.push(...requireString(obj.id, `${path}.id`));
  errors.push(...requireString(obj.label, `${path}.label`));
  if (!obj.install || typeof obj.install !== 'object') {
    errors.push(`${path}.install is required`);
    return;
  }
  const install = /** @type {Record<string, unknown>} */ (obj.install);
  errors.push(...rejectUnknownKeys(install, ['source', 'path', 'releaseId', 'url', 'manifestPath'], `${path}.install`));
  errors.push(...requireString(install.source, `${path}.install.source`));
  const source = install.source;
  if (source === 'bundled' && typeof install.path !== 'string') {
    errors.push(`${path}.install.path is required when source=bundled`);
  }
  if (source === 'authoritypacks-release' && typeof install.releaseId !== 'string') {
    errors.push(`${path}.install.releaseId is required when source=authoritypacks-release`);
  }
  if (source === 'url' && typeof install.url !== 'string') {
    errors.push(`${path}.install.url is required when source=url`);
  }
}

/**
 * @param {unknown} item
 * @param {string} path
 * @param {string[]} errors
 */
function validateSettingsSection(item, path, errors) {
  if (!item || typeof item !== 'object') {
    errors.push(`${path} must be an object`);
    return;
  }
  const obj = /** @type {Record<string, unknown>} */ (item);
  errors.push(...rejectUnknownKeys(obj, ['id', 'label', 'description'], path));
  errors.push(...requireString(obj.id, `${path}.id`));
  errors.push(...requireString(obj.label, `${path}.label`));
}

/**
 * @param {unknown} item
 * @param {string} path
 * @param {string[]} errors
 */
function validateDisambiguation(item, path, errors) {
  if (!item || typeof item !== 'object') {
    errors.push(`${path} must be an object`);
    return;
  }
  const obj = /** @type {Record<string, unknown>} */ (item);
  errors.push(...rejectUnknownKeys(obj, ['id', 'label', 'entityKind', 'description', 'usesContextKeys'], path));
  errors.push(...requireString(obj.id, `${path}.id`));
  errors.push(...requireString(obj.label, `${path}.label`));
  errors.push(...requireString(obj.entityKind, `${path}.entityKind`));
}
