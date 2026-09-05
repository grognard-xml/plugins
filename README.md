# Grognard plugins

Optional plugins for [Grognard](https://github.com/grognard/grognard): specialized tools that not every user needs, installed from **Tools → Plugins**.

## Layout

```
plugins/
  docs/manifest.md          # manifest spec
  schema/                   # JSON Schema
  packages/
    plugin-sdk/             # validate manifests
    plugin-cjk-dates/       # East Asian dates (Sanmiao)
    plugin-norbert/         # Chinese prosopography
    plugin-kanripo-import/  # Kanripo clone → TEI, gaiji, parallel punctuation
    plugin-daozang-import/  # Fang Tongzi Daozang corpus import
```

Each plugin folder contains **`plugin.manifest.json`** — the contract the Grognard host reads at install time.

## Quick start

```bash
npm run validate          # check all plugin.manifest.json files
npm run release:prepare   # build dist + refresh metadata, verify bundled data
npm run release           # prepare + smoke tests + archives + plugins-index.json
```

Maintainers refreshing large bundled assets (first time or after upstream changes):

```bash
npm run build:daozang-corpus -w @grognard/plugin-daozang-import   # if corpus not in tree
npm run download:gaiji -w @grognard/plugin-kanripo-import         # if gaiji not in tree
npm run release
```

## Plugins

| Plugin | Id | For |
|--------|-----|-----|
| East Asian dates | `cjk-dates` | Premodern China, Japan, Korea — date tagging & disambiguation |
| Norbert | `norbert` | Chinese entity tagging, contextual disambiguation, noble titles, Norbert authority pack |
| Kanripo import | `kanripo-import` | Clone Kanseki Repository works, gaiji, parallel punctuation, SKQS metadata |
| Daozang import | `daozang-import` | Bundled 方瞳子 Daozang corpus (~1,500 texts), search and TEI import |

**Wikisource import** is built into the Grognard desktop app (not this repo). Kanripo can use Wikisource as a parallel punctuation source when Grognard is installed.

## Related repos

- **grognard** — editor + plugin *host* (Tools panel, import dialogs, suggestion pipeline)
- **authoritypacks** — compile Norbert/CBDB/Wikidata NDJSON packs; Norbert plugin references those releases

## Documentation

See [`docs/manifest.md`](docs/manifest.md) for the full manifest format.

## Releases

`npm run release` builds each plugin's runtime entry and emits a versioned
`grognard-plugin-<id>-<version>.tar.gz` archive plus `plugins-index.json`. The
`build-plugins` GitHub Actions workflow publishes those files as release
assets when a `v*` tag is pushed. Grognard fetches that index from the latest
release, verifies the archive SHA-256, checks archive paths, and installs the
package under its per-user plugin directory. Platform-specific Python
runtimes are downloaded after installation, so archives remain portable.
