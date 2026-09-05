/**
 * Grognard plugin manifest types (manifestVersion 1.0.0).
 * Consumed by the plugin host in grognard and by packages in this repo.
 */

/** @typedef {'1.0.0'} PluginManifestVersion */

/** @typedef {'javascript' | 'python' | 'hybrid'} PluginEntryKind */

/** @typedef {'bundled' | 'system' | 'conda-env'} PythonRuntimeKind */

/** @typedef {'east-asia' | 'china' | 'japan' | 'korea'} PluginRegion */

/**
 * @typedef {Object} PluginManifestPythonBackend
 * @property {string} module
 * @property {PythonRuntimeKind} [runtime]
 * @property {string} [runtimePath]
 */

/**
 * @typedef {Object} PluginManifestEntry
 * @property {PluginEntryKind} kind
 * @property {string} [module]
 * @property {PluginManifestPythonBackend} [python]
 */

/**
 * @typedef {Object} PluginToolsMenuItem
 * @property {string} id
 * @property {string} label
 * @property {string} [action]
 * @property {boolean} [separatorBefore]
 */

/**
 * @typedef {Object} PluginAutoTaggingProducer
 * @property {string} id
 * @property {string} label
 * @property {string} [description]
 * @property {'dates' | 'authority-tag-bomb' | 'contextual-disambiguation' | 'pattern-tag' | 'custom'} kind
 * @property {boolean} [defaultEnabled]
 * @property {string[]} [tags]
 */

/**
 * @typedef {Object} PluginAuthorityPackInstall
 * @property {'bundled' | 'authoritypacks-release' | 'url'} source
 * @property {string} [path]
 * @property {string} [releaseId]
 * @property {string} [url]
 * @property {string} [manifestPath]
 */

/**
 * @typedef {Object} PluginAuthorityPackContribution
 * @property {string} id
 * @property {string} label
 * @property {string} [defaultTag]
 * @property {PluginAuthorityPackInstall} install
 */

/**
 * @typedef {Object} PluginSettingsSection
 * @property {string} id
 * @property {string} label
 * @property {string} [description]
 */

/**
 * @typedef {Object} PluginDisambiguationStrategy
 * @property {string} id
 * @property {string} label
 * @property {'person' | 'place' | 'office' | 'date' | 'org' | 'work'} entityKind
 * @property {string} [description]
 * @property {('dynasty' | 'office' | 'place' | 'nationality' | 'compound-string')[]} [usesContextKeys]
 */

/**
 * @typedef {Object} PluginContributions
 * @property {PluginToolsMenuItem[]} [toolsMenu]
 * @property {PluginToolsMenuItem[]} [fileMenu]
 * @property {PluginAutoTaggingProducer[]} [autoTagging]
 * @property {PluginAuthorityPackContribution[]} [authorityPacks]
 * @property {PluginSettingsSection[]} [settingsSections]
 * @property {PluginDisambiguationStrategy[]} [disambiguation]
 */

/**
 * @typedef {Object} PluginManifest
 * @property {PluginManifestVersion} manifestVersion
 * @property {string} id
 * @property {string} name
 * @property {string} version
 * @property {string} description
 * @property {string} [author]
 * @property {string} [homepage]
 * @property {string} license
 * @property {{ minVersion: string, maxVersion?: string }} grognard
 * @property {string[]} [languages]
 * @property {PluginRegion[]} [regions]
 * @property {{ message: string, documentLanguages?: string[] }} [languagePrompt]
 * @property {PluginManifestEntry} entry
 * @property {PluginContributions} [contributions]
 * @property {{ plugins?: string[] }} [dependencies]
 * @property {string[]} [bundled]
 */

export const PLUGIN_MANIFEST_VERSION = '1.0.0';

export const PLUGIN_MANIFEST_FILENAME = 'plugin.manifest.json';
