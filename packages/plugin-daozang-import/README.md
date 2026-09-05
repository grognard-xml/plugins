# Daozang import

Import 方瞳子源 (Fang Tongzi) transcriptions of the Zhengtong and Wanli Supplement Daozang into project TEI.

The plugin ships with a **bundled UTF-8 corpus** (`data/corpus/`, 1,504 texts, ~77 MB) whose `index.json` already carries each work's DZ section, number, title, dynasty, and authorship. Users can search and import immediately after install — no download from third-party sites.

## Bundled corpus (maintainers)

Build or refresh bundled data before `npm run release`:

```bash
cd plugins/packages/plugin-daozang-import

# From the Fang Tongzi RAR (slow: extract + convert)
node scripts/build-corpus-data.mjs --from-rar ~/Downloads/DaoCanon_txt_chm.rar

# Or from an already-extracted 道藏_txt folder (fast)
node scripts/build-corpus-data.mjs --from-utf8 ~/Downloads/DaoCanon_txt_chm/道藏_txt
```

This writes:

```
data/corpus/
  utf8/           # UTF-8 .txt files
  index.json      # search index
  manifest.json   # provenance
```

These paths are listed in `plugin.manifest.json` → `bundled`, so they are included in the plugin release archive.

### Work metadata (maintainers)

Rich entity metadata (DZID, Kanripo KR_ID, volumes, Norbert `person_id`, dynasty/date) ships **inside the plugin** under `data/metadata/`. Source CSVs live in `data/metadata/sources/`; the build script reads only those bundled files.

Rebuild the lookup JSON after editing sources:

```bash
cd plugins/packages/plugin-daozang-import
npm run build:metadata
```

Bundled sources (committed with the plugin):

- `data/metadata/sources/dz_metadata_works.csv`
- `data/metadata/sources/dz_metadata_authors.csv` (Norbert `person_id`)
- `data/metadata/sources/krp_dz_collation.csv` (KR_ID)
- `data/metadata/sources/DZ_metadata_normalized.csv` (dynasty/date hints; optional but included)
- `data/metadata/sources/dz_wikidata_qids.json` (Wikisource page + Q-ids from the 正統道藏 TOC matcher)

Output: `data/metadata/dz_works_by_rel_path.json`. On import, Python attaches a DPM-style `<metadata>` block plus TEI header fields (idno, authors, creation).

**Wikisource / Wikidata:** confirmed TOC matches add `ws_page`, `ws_url` (only if the page exists), and the sitelink Q-id. Unmatched works (including 續道藏) have no Q-id. Rebuild the export first:

```bash
cd ~/Python/chinese_corpus_metadata
python scripts_wikidata/export_dz_wikidata_qids.py
```

**Authorship:** every row in `dz_metadata_authors.csv` is included per work (113 multi-author works in the corpus, up to 11 authors on 孫子批注). The build does not collapse to a lead author only.

To refresh sources from your upstream tables (maintainers only, not required for normal use):

```bash
python3 scripts/build-daozang-metadata.py \
  --sync-from ~/Python/chinese_corpus_metadata \
  --normalized-csv ~/Corpora/DaoCanon_txt_chm/DZ_metadata_normalized.csv
```

When the normalized CSV is absent, dynasty is inferred from the Fang Tongzi filename (e.g. `-元-陳致虛.txt` → 元).

**Kanripo crosswalk:** KR_ID → bundled Daozang filename lives in the sibling **kanripo-import** plugin (`data/concordance/kanripo_daozang_map.json`). Rebuild with `npm run build:concordance -w @grognard/plugin-kanripo-import`.

`data/corpus/utf8/` is gitignored locally because of size; CI/release machines run the build script before packaging.

Optional separate redistributable pack (same bytes, different layout):

```bash
node scripts/build-corpus-pack.mjs --from-utf8 data/corpus/utf8
```

## User workflow

1. Install and enable the plugin (**Tools → Plugins**).
2. **File → Import from Daozang…** — bundled corpus is ready immediately. Search by title, 道藏 number, section, dynasty, or author.

The corpus is part of the plugin, so there is nothing to install or refresh from the dialog. Maintainers rebuild `data/corpus/` with the scripts above; the Python `install_from_source` / `sync` operations exist for those scripts only.

## Requirements

- Python 3 on `PATH` (for TEI conversion and for rebuilding the bundled corpus)
- A RAR extractor only when rebuilding from `.rar`: `unar`, `7z`, `unrar`, or `bsdtar`

## Development

```bash
cd plugins
npm run smoke:daozang-import
```

Install in Grognard via **Tools → Plugins → Install from folder…** pointing at `packages/plugin-daozang-import` (after `build-corpus-data` has been run once).
