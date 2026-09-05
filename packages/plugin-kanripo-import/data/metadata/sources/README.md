# Bundled metadata sources

CSV/JSON inputs for `npm run build:metadata`. **At import time, only the built files under `data/metadata/` and `data/concordance/` are read** — nothing in this folder is loaded directly by the plugin at runtime except during rebuilds.

## Source files

| File | Role |
|------|------|
| `krp_works.csv` | Kanripo catalog: titles, juan file counts |
| `skqs_org_authorship.csv` | SKQS: authors, dynasty, dates, extent, edition source |
| `dz_metadata_works.csv` | Daozang work titles, volumes |
| `dz_metadata_authors.csv` | All Daozang authors with Norbert `person_id` |
| `DZ_metadata_normalized.csv` | Dynasty and date hints for Daozang works |
| `krp_wikidata_qids.json` | SKQS ↔ Wikisource matches: Q-ids, `ws_page`, `match_tier` |

Concordance inputs live in `data/concordance/` (`krp_dz_collation.csv`, `kanripo_org_concordance.csv`, `kanripo_daozang_map.json`).

| Built output | Location |
|--------|----------|
| Edition profile table | `../edition_profiles.json` |
| Work metadata lookup (SKQS/DZ only) | `../krp_works_by_id.json` |
| Wikidata crossref lookup (KR → Q-id, WS) | `../krp_wikidata_by_kr_id.json` |
| Parallel punctuation crosswalk (Daozang paths only) | `../../concordance/krp_parallel_sources.json` |
| Build stats | `../manifest.json` |

`krp_wikidata_qids.json` in this folder is a **build input only** — it is not shipped in the installed plugin.

## Field priority (merge rules)

1. **SKQS** wins for title, authors, dynasty, dates, extent, edition source when the KR id is in SKQS.
2. **Daozang** fills gaps and adds full multi-author lists + `person_id` when KR ↔ DZID is known.
3. **Wikidata crossref** (`krp_wikidata_qids.json`) adds Q-ids and Wikisource URLs; does not overwrite catalog fields.
4. **Wikidata authority pack** (`--wikidata-pack`, optional) fills aliases, description, years only where catalog fields are empty.

## Maintainer refresh

```bash
# Upstream (chinese_corpus_metadata), when tables or matches change:
python scripts_wikidata/export_krp_wikidata_qids.py

# Plugin:
python3 scripts/build-kanripo-metadata.py --sync-from /path/to/chinese_corpus_metadata
npm run build:metadata
```

Optional authority pack (auto-discovered in the Grognard monorepo, or `--wikidata-pack` / `GROGNARD_WIKIDATA_WORK_PACK`):

```bash
python3 scripts/build-kanripo-metadata.py --sync-from /path/to/chinese_corpus_metadata
```

See the package [README.md](../../../README.md) for the full field catalogue and TEI mapping.
