# @grognard/plugin-bdrc-import

Import one **BDRC** ([Buddhist Digital Resource Center](https://library.bdrc.io))
etext volume into the open project as TEI.

Unlike the Kanripo / Daozang plugins, this one **fetches live** from the BDRC
Public Data Interface (`purl.bdrc.io`) at import time — there is no bundleable
corpus tree. A local on-disk cache (keyed by `UT` id + data revision) makes a
re-import offline.

- **Delivery:** browser extension on the BUDA reader → native messaging → Grognard
  **File → Import from BDRC…**. Same path as the Wikisource / Kanripo adapters.
- **Unit:** one `UT` etext volume per import, `<pb/>` markers throughout.
- **Language:** Tibetan (`bo`).
- **Edition metadata:** the scanned instance's edition statement, publisher /
  place, and publication year (ISO `<date>` only when BDRC carries a clean
  4-digit year) are pulled from its `/resource/<MW>` describe graph into
  `<sourceDesc><bibl>`, alongside a `<note type="source">` naming BDRC and the
  URL the volume was imported from.
- **Authority:** persons (`bdr:P…`) / places (`bdr:G…`) emitted as `@ref`
  URIs; names resolved later via the Wikidata P2477 crosswalk. No bundled pack.

Full design and open questions: **[bdrc-import-planning.md](https://github.com/grognard/grognard/blob/main/docs/bdrc-import-planning.md)**
in the host repo.

## Layout

```
plugin.manifest.json   # contract the Grognard host reads at install time
src/register.ts        # stub — loads `bdrc-import-ui` from the host bundle
esbuild.config.mjs     # bundles src/register.ts → dist/register.mjs
```

The fetch + TEI-emit pipeline (`apps/desktop/src/bdrc/`) and the import dialog
live in the host repo, not here.

## Build

```bash
npm run build -w @grognard/plugin-bdrc-import
```
