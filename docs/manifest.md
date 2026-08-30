# LJB plugin manifest (v1.0.0)

Each plugin is a folder under `packages/` containing a **`plugin.manifest.json`**. The LJB desktop app reads this file when a plugin is installed under the user’s plugins directory.

## File location

```
packages/<plugin-name>/
  plugin.manifest.json    # required
  package.json            # npm workspace metadata
  dist/register.mjs       # JS entry (future)
  python/                 # optional bundled Python backend
```

Validate all manifests:

```bash
npm run validate
```

## Top-level fields

| Field | Required | Purpose |
|-------|----------|---------|
| `manifestVersion` | yes | Schema version. Currently `"1.0.0"`. |
| `id` | yes | Stable kebab-case id (`norbert`, `cjk-dates`). |
| `name` | yes | Display name in Tools → Plugins. |
| `version` | yes | Plugin package semver. |
| `description` | yes | Short summary. |
| `license` | yes | SPDX license id. |
| `ljb.minVersion` | yes | Minimum LJB version. |
| `entry` | yes | How the host loads the plugin (see below). |
| `languages` | no | BCP 47 tags for language-based discovery prompts. |
| `regions` | no | `east-asia`, `china`, `japan`, `korea`. |
| `languagePrompt` | no | Message when a matching document language is opened. |
| `contributions` | no | What the plugin registers with LJB. |
| `dependencies.plugins` | no | Other plugin ids required first. |
| `bundled` | no | Paths included in the install archive. |

## Entry kinds

| `entry.kind` | Meaning |
|--------------|---------|
| `javascript` | Bundled `register.mjs` hooks into LJB (auto-tagging, menus). |
| `python` | IPC backend only (like Sanmiao today). |
| `hybrid` | Both JS registration and a Python backend. |

Example (hybrid):

```json
"entry": {
  "kind": "hybrid",
  "module": "dist/register.mjs",
  "python": {
    "module": "sanmiao.ljb_bridge",
    "runtime": "bundled",
    "runtimePath": "python"
  }
}
```

## Contributions

Plugins declare **what they offer**; the LJB host decides **how to wire it**.

### `toolsMenu`

Items merged under **Tools** when the plugin is enabled.

```json
{
  "id": "norbert-settings",
  "label": "Norbert settings…",
  "action": "norbert.open-settings",
  "separatorBefore": true
}
```

The host dispatches `action` to the plugin’s JS entry.

### `autoTagging`

Producers shown in the auto-tagging dialog. Each becomes a `Suggestion` source in the unified pipeline (see LJB `docs/Auto-tagging.md`).

Kinds:

- `dates` — calendar/date element tagging
- `authority-tag-bomb` — NDJSON authority matching
- `contextual-disambiguation` — Norbert-style compound context
- `pattern-tag` — structured regex/pattern passes (noble titles)
- `custom` — anything else

### `authorityPacks`

Registers pack ids with the entity-database folder. Install sources:

| `install.source` | Use |
|------------------|-----|
| `bundled` | Ship `persons.ndjson` inside the plugin archive. |
| `authoritypacks-release` | Download from the authoritypacks release tarball. |
| `url` | Direct URL to a pack archive. |

Bundled packs are for plugin-local runtime assets, not for the public
authority-packs CI tarball. Norbert uses this for the shipped
`data/wiki-nt-links.ndjson` noble-title crosswalk: it lives with the plugin so
the tagger can use it for person-wrapper / noble-title disambiguation without
writing hypothetical rows into `entities.xml`.

Norbert example (pulls from authoritypacks release):

```json
{
  "id": "norbert-persons",
  "label": "Norbert persons",
  "defaultTag": "persName",
  "install": {
    "source": "authoritypacks-release",
    "releaseId": "authority-packs-chinese",
    "manifestPath": "norbert/manifest.json"
  }
}
```

### `disambiguation`

Strategies shown in the disambiguation panel. Norbert uses `usesContextKeys` to document dynasty/office/place context — the LJB equivalent of your `<person>` wrapper logic without requiring that custom XML in the final corpus.

### `settingsSections`

Optional sections added to the Settings dialog when the plugin is enabled.

## Host behaviour

1. User opens **Tools → Plugins…**
2. Host lists installed plugins by reading each folder’s `plugin.manifest.json`
   and checks the plugins repository's release index for new versions.
3. A new installation or update downloads the versioned archive, verifies its
   SHA-256, validates its manifest, and installs it under the per-user plugin
   directory.
4. Enabling a plugin:
   - loads `entry.module` (JS)
   - starts Python IPC if `entry.python` is set
   - installs declared authority packs
   - merges menu items and auto-tagging producers
5. On document open, if `languagePrompt` matches and the plugin is not installed, show a one-time nudge

## Schema

Machine-readable schema: [`schema/plugin-manifest.schema.json`](../schema/plugin-manifest.schema.json)

Validation: `@ljb/plugin-sdk` (`packages/plugin-sdk/validate.mjs`).

## Current plugins

| Id | Package | Scope |
|----|---------|-------|
| `cjk-dates` | `plugin-cjk-dates` | Premodern China, Japan, Korea dates (Sanmiao) |
| `norbert` | `plugin-norbert` | Chinese prosopography, noble titles, Norbert pack |
| `kanripo-import` | `plugin-kanripo-import` | Kanripo Mandoku → TEI, gaiji, parallel punctuation, metadata |
| `daozang-import` | `plugin-daozang-import` | Bundled Fang Tongzi Daozang corpus, local search + TEI import |

Hybrid import plugins (`kanripo-import`, `daozang-import`) ship a thin `dist/register.mjs` that loads dialog UI from the LJB host (`kanripo-import-ui` / `daozang-import-ui` modules in the editor package). The host must be **LJB 0.1.0-beta.4** or newer for those imports.

## Release checklist

```bash
npm run release:prepare   # validate, build all dist/, refresh metadata JSON, verify bundled paths
npm run release:smoke     # optional alone; included in release
npm run release           # full pipeline → release/archives/*.tar.gz + plugins-index.json
git tag v0.1.0 && git push origin v0.1.0
```

Large assets (`data/corpus/`, `data/gaiji/`) are committed in this repo so CI can build archives without re-downloading. Rebuild them only when upstream sources change (see each package README).
