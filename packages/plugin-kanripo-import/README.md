# Kanripo import plugin

Self-contained hybrid plugin: Mandoku → TEI conversion, bundled gaiji tables/PNGs, parallel punctuation, work metadata (SKQS + Daozang + Wikidata), and a KRP–Wikisource–Daozang crosswalk for one-click punctuation sources.

**Runtime:** everything reads from bundled files under this package’s `data/` folder (via `LJB_PLUGIN_INSTALL_PATH`). No checkout of `chinese_corpus_metadata`, `normalization_zh`, or other sibling projects is required to import or punctuate.

**Maintainers** may refresh bundled tables from upstream with `--sync-from` (see [Refreshing bundled data](#refreshing-bundled-data-maintainers-only)).

## What ships in the plugin

| Piece | Location |
| --- | --- |
| Mandoku → TEI body | `python/kanripo_import/kanripo_tei.py` |
| Gaiji (`&KRnnnn;`) resolution | `python/kanripo_import/kanripo_gaiji.py` |
| KR-Gaiji charlist + PNGs | `data/gaiji/` |
| DPM + hard-replacement CSVs | `data/normalize/` |
| Parallel punctuation | `python/kanripo_import/parallel_punct.py` |
| Work search index (id, section, title, dynasty, authors, dzid) | `data/krp_works.json` |
| Work metadata (authors, dynasty, dates, vols, edition, Wikidata) | `data/metadata/krp_works_by_id.json` |
| Edition profile table (SKQS WYG, 正統道藏, …) | `data/metadata/edition_profiles.json` |
| KR ↔ DZ / Daozang concordance | `data/concordance/` |
| KRP parallel-source crosswalk (WS + Daozang buttons) | `data/concordance/krp_parallel_sources.json` |
| Wizard UI | LJB host module (`kanripoImportUi`) |

## Self-containment

| When | External folders? |
| --- | --- |
| **Import / punctuate / search** | **No.** Python resolves paths under `data/` inside the installed plugin only (`python/kanripo_import/_paths.py`). |
| **Rebuild metadata or concordance** | Optional. `--sync-from /path/to/chinese_corpus_metadata` copies fresh CSVs/JSON into `data/`; not needed for end users. |
| **Daozang parallel text** | Separate **Daozang import** plugin (bundled 方瞳子 corpus). Kanripo import only stores the *path* (`rel_path`) in its crosswalk; reading text uses `daozang-import`. |
| **Wikisource / ctext URL fetch** | Network at click time only; no local mirror required. |

Provenance fields inside some JSON files (e.g. `"source": "/home/…/matches.csv"`) record where data was built; they are **not** read at runtime.

---

## Work metadata (import entities)

Bundled under `data/metadata/` for offline KR_ID lookup at import time.

### Source tables (`data/metadata/sources/`)

| File | Role |
| --- | --- |
| `krp_works.csv` | Titles, juan file counts (Kanripo catalog) |
| `skqs_org_authorship.csv` | SKQS authors, dynasty, `DATES`, `EXTENT`, edition `SOURCE` |
| `dz_metadata_works.csv` | Daozang titles, volumes (KR ↔ DZ enrichment) |
| `dz_metadata_authors.csv` | All Daozang authors with Norbert `person_id` |
| `DZ_metadata_normalized.csv` | Dynasty and date hints for Daozang works |
| `krp_wikidata_qids.json` | SKQS ↔ Wikisource match export (Q-ids, `ws_page`, `match_tier`) |
| `kr_classification.json` | KR 部/類 labels, fetched from the upstream KR-Catalog |

KR_ID → DZID crosswalk: bundled `data/concordance/krp_dz_collation.csv` and `kanripo_org_concordance.csv`.

### Built output

| File | Role |
| --- | --- |
| `krp_works_by_id.json` | Runtime lookup (~9k works): SKQS/DZ bibliographic metadata |
| `krp_wikidata_by_kr_id.json` | Runtime lookup (~2.6k works): Q-ids, Wikisource URLs, pack enrichment |
| `../krp_works.json` | Slim, pre-joined index the import window searches |
| `manifest.json` | Build stats (counts, timestamp) |

Wikidata is kept in a **separate sidecar file** so the main metadata blob stays smaller and Q-id pairs are not duplicated inside every work record. At import time Python joins the two lookups by `kr_id`.

Build-only inputs under `data/metadata/sources/` (including `krp_wikidata_qids.json`) are **not** bundled in the installed plugin — only the built JSON files above ship.

Rebuild:

```bash
npm run build:metadata -w @ljb/plugin-kanripo-import
```

The full build needs the optional Wikidata authority pack (`--wikidata-pack`); without it the
pack enrichment in `krp_works_by_id.json` is lost. To refresh only the search index from the
metadata already built:

```bash
python3 scripts/build-kanripo-metadata.py --index-only
```

### Section labels

`data/metadata/sources/kr_classification.json` holds the 部/類 labels shown as the first line of each
search result (經部・易類, 道部・洞真部, 佛部・禪宗部類). It is fetched from the upstream
[KR-Catalog](https://github.com/kanripo/KR-Catalog) — never hand-edited:

```bash
python3 scripts/fetch-kr-classification.py
```

`KR2p` has works here but no heading upstream, so those three rows show 史部 alone.

### Fields per work (`krp_works_by_id.json`)

**Always (from Kanripo catalog):**

| Field | Meaning |
| --- | --- |
| `kr_id` | Kanripo work id (e.g. `KR1a0030`) |
| `title` | Work title (SKQS or Daozang overrides Kanripo when present) |
| `juan_count` | Number of juan files in Kanripo |
| `vols` | Extent in 卷: SKQS `EXTENT`, else Daozang vols, else juan count |
| `source` | Raw edition string (SKQS `SOURCE`, or 正統道藏 for DZ-only) |
| `edition_profile` | Profile id from `edition_profiles.json` (e.g. `skqs_wyg`) |
| `edition_label` | Structured edition name for TEI (e.g. 文淵閣四庫全書) |
| `edition_date` | Year of edition (e.g. `1782` for SKQS WYG) |
| `source_locator` | SKQS volume/page locator (e.g. `V143.1, p1 - V144.1`) |
| `cbeta_id` | CBETA id from org concordance |
| `dzid` | Normalized Daozang id when mapped |
| `time_dynasty` | Dynasty (SKQS → author → DZ normalized hints) |
| `author_dates` | Life dates string when known |
| `date_not_before`, `date_not_after` | Parsed ISO-style bounds when `DATES` is `start-end` |
| `authorship[]` | Author rows (see below) |
| `metadata_sources.skqs`, `.daozang` | Which catalogues contributed |

**Per author (`authorship[]`):**

| Field | Meaning |
| --- | --- |
| `author_index` | Order (1, 2, …) |
| `person_name` | Author name |
| `function` | Role (撰, 編, …) |
| `time_dynasty` | Author dynasty |
| `author_dates`, `date_not_before`, `date_not_after` | Life dates |
| `person_id` | Norbert person id (from Daozang when KR ↔ DZ) |

**Merge rule:** SKQS authorship wins; Daozang adds `person_id` and extra authors. Daozang fills title/vols/source only when SKQS is absent.

**Wikidata block (`wikidata`, when SKQS matched to Wikisource):**

| Field | Meaning |
| --- | --- |
| `work_qid` | Wikidata work entity (P629 parent) |
| `edition_qid` | Wikidata edition (四庫全書本) |
| `wikidata_work_qid` | Primary Q-id used for linking |
| `ws_page` | Wikisource page title |
| `ws_url` | Full Wikisource URL |
| `match_tier` | Match confidence (e.g. `confirmed_tiyao`, `confirmed_unique_title`) |
| `corpus_title` | Title used during matching |
| `primary_name`, `aliases[]` | From Wikidata authority pack (**gap-fill only**, if `--wikidata-pack` used) |
| `start_year`, `end_year`, `description` | Same (gap-fill only) |

**Priority:** SKQS/Daozang catalog data always wins; Wikidata crossref adds identifiers and links; authority pack fills empty fields only.

### What lands in imported TEI

**`<teiHeader>` biblStruct (LJB file metadata panel):**

- `monogr/edition` ← `edition_label`
- `monogr/imprint/date@when` ← `edition_date`
- `biblStruct/note` ← Kanripo id, juan, file witness, SKQS locator

**`<teiHeader>` idnos:**

- `Kanripo`, `CBETA`, `DZID`
- Wikidata work URI (`<idno type="URI">`)
- Edition URI when distinct (`subtype="edition"`)
- Wikisource URL (`subtype="wikisource"`)

**`<metadata>` block (DPM convention):**

- `<citation>` attrs: kr_id, title, source, edition_profile, edition_label, edition_date, source_locator, cbeta_id, dz_id, juan, Q-ids, ws_page
- `<work>`: title, vols, `<authorship>` / `<persName>`
- `<date>`: dynasty, notBefore/notAfter
- `<wikidata>`: workQid, editionQid, wsPage, wsUrl, primaryName, aliases (up to 12)

Per-juan fields from the Kanripo file header (juan number, source line) are unchanged.

---

## Parallel-source crosswalk (punctuation UI)

`data/concordance/krp_parallel_sources.json` lists **Daozang-only** bundled paths (~1.5k works). **Wikisource** parallel buttons are derived at runtime from `krp_wikidata_by_kr_id.json` (~2.6k works). Python merges both in `kanripo_import.crosswalk.lookup_parallel_crosswalk()`.

| Source at runtime | From |
| --- | --- |
| Wikisource URL + label | `krp_wikidata_by_kr_id.json` (`ws_url`, `ws_page`) |
| Daozang `rel_path` | `krp_parallel_sources.json` |
| Title, dz_id, cbeta_id | `krp_works_by_id.json` (joined by `kr_id`) |

**UI behaviour:**

- When a work (or open file’s Kanripo idno) has crosswalk entries, **one-click** Wikisource / Daozang buttons appear.
- Manual URL, file, paste, and ctext wiki remain under **Other sources**.
- Daozang load requires the **Daozang import** plugin enabled and corpus ready.

Python API: `kanripo_import.crosswalk.lookup_parallel_crosswalk("KR1a0030")`. Bridge op `concordance_lookup` returns `parallel_crosswalk` for the desktop UI.

---

## Concordance data (Kanripo ↔ 方瞳子 Daozang)

Bundled under `data/concordance/` for offline KR_ID ↔ DZID ↔ bundled Daozang filename lookup:

| File | Role |
| --- | --- |
| `krp_dz_collation.csv` | Work-level KR_ID ↔ DZID (~1500 Daoist texts) |
| `kanripo_org_concordance.csv` | Kanripo.org catalogue ↔ CBETA / DZID |
| `dz_corpus_works.csv` | DZID ↔ Fang Tongzi corpus filename |
| `duren_jing_index.csv` | Curated Duren jing KR ↔ DZ paths |
| `kanripo_daozang_map.json` | Runtime map: KR_ID → bundled Daozang `rel_path` |
| `kanripo_daozang_overrides.csv` | Manual overrides (maintainer-edited) |
| `krp_parallel_sources.json` | KRP → bundled Daozang `rel_path` (Wikisource derived at runtime from wikidata sidecar) |

Refresh concordance tables:

```bash
npm run build:concordance -w @ljb/plugin-kanripo-import
```

Python API: `kanripo_import.concordance.lookup_daozang_rel_path("KR5a0087")`.

---

## Refreshing bundled data (maintainers only)

After updating tables or SKQS–Wikisource matches in `chinese_corpus_metadata`:

```bash
# From chinese_corpus_metadata (when matches change):
python scripts_wikidata/export_krp_wikidata_qids.py
python scripts_wikidata/apply_skqs_resolved_matches.py --fetch-qids

# Into the plugin:
cd packages/plugin-kanripo-import
python3 scripts/build-kanripo-metadata.py --sync-from /path/to/chinese_corpus_metadata
npm run build:concordance   # if DZ paths changed
```

Optional Wikidata authority-pack enrichment (aliases, description, years — gap-fill only).
When building inside the LJB monorepo, the pack is **auto-discovered** at
`authoritypacks/packs/wikidata/work-zh-hant/works.ndjson`. Override with
`--wikidata-pack` or `LJB_WIKIDATA_WORK_PACK`:

```bash
python3 scripts/build-kanripo-metadata.py --sync-from /path/to/chinese_corpus_metadata
# or explicitly:
python3 scripts/build-kanripo-metadata.py \
  --wikidata-pack /path/to/authoritypacks/packs/wikidata/work-zh-hant/works.ndjson
```

End users who install the built plugin **never** need these steps.

---

## Authorship notes (summary)

- Most SKQS works: author + dynasty + dates from `skqs_org_authorship.csv`.
- **`person_id`**: from `dz_metadata_authors.csv` when KR maps to DZID (~800+ rows).
- Multi-author Daozang works: all DZ authors merged when SKQS has fewer.
- **`vols`**: SKQS `EXTENT` when present; else DZ vols; else Kanripo juan file count.

See also `data/metadata/sources/README.md`.

---

- Unicode or IDS entries from [kanripo/KR-Gaiji](https://github.com/kanripo/KR-Gaiji) resolve to characters or bracket notation.
- Image-only entries emit inline TEI:

  `<g type="kanripo" n="KR0954"><graphic url="_gaiji/KR0954.png" height="1em"/></g>`

  PNGs are copied into `<project>/imported/kanripo/<KR_ID>/_gaiji/` during import. The visual editor resolves `_gaiji/…` relative to the open XML file and renders these at **1em height** (inline, baseline-aligned). Paste/crop tooling is a follow-up.

## Refresh gaiji data

```bash
npm run download:gaiji -w @ljb/plugin-kanripo-import
```

## Dev smoke test

```bash
npm run build:kanripo-import
npm run smoke:kanripo-import
```

## Batch parallel test (no GUI)

Check every juan in a Kanripo work against one parallel source — well-formed XML and coverage per file:

```bash
npm run test:parallel-batch -w @ljb/plugin-kanripo-import -- \
  --kanripo /path/to/KR4h0002 \
  --ctext-url 'https://ctext.org/wiki.pl?if=gb&chapter=793335'
```

Or with a saved parallel file:

```bash
npm run fetch:ctext -w @ljb/plugin-kanripo-import -- \
  --url 'https://ctext.org/wiki.pl?if=gb&chapter=793335' > /tmp/ctext.txt

npm run test:parallel-batch -w @ljb/plugin-kanripo-import -- \
  --kanripo /path/to/KR4h0002 --parallel /tmp/ctext.txt
```

**ctext URL:** use a **wiki commentary page** (`…/wiki.pl?…&chapter=…`), not a library/reading root URL. One wiki chapter often matches only part of a multi-juan Kanripo work (other juans correctly show ~0% overlap).

Requires sibling `leaf-writer` (or `LJB_HOST_ROOT`) for host UI wiring check. Python tests run against bundled data with `LJB_PLUGIN_INSTALL_PATH` set automatically in smoke.

## CLI: convert + segmented parallel punctuation

From the plugin package root, with sibling `leaf-writer` for bundled Python:

```bash
PLUGIN="/path/to/plugins/packages/plugin-kanripo-import"
PY="/path/to/leaf-writer/apps/desktop/resources/python/bin/python3"
export LJB_PLUGIN_INSTALL_PATH="$PLUGIN" PYTHONPATH="$PLUGIN/python"

# 1. Convert Kanripo txt → TEI body
echo '{"path":"/path/to/KR4h0002_001.txt","normalize":"off","gaiji_dest_dir":"/tmp/_gaiji"}' \
  | "$PY" -c "from kanripo_import.ljb_bridge import cli_main; cli_main()" \
  > /tmp/kanripo-body.json

# 2. Fetch whole ctext wiki chapter (default: all rows on the page)
npm run fetch:ctext -w @ljb/plugin-kanripo-import -- \
  --url 'https://ctext.org/wiki.pl?if=gb&chapter=793335' \
  > /tmp/ctext-whole.txt

# Optional: one section only
npm run fetch:ctext -w @ljb/plugin-kanripo-import -- \
  --url 'https://ctext.org/wiki.pl?if=gb&chapter=793335' --section 兩都賦序 \
  > /tmp/ctext-section.txt

# 3. Apply segmented punctuation (basetext + commentary matched separately)
python3 - <<'PY'
import json, os, subprocess
from pathlib import Path
plugin = Path(os.environ["LJB_PLUGIN_INSTALL_PATH"])
body = json.loads(Path("/tmp/kanripo-body.json").read_text())["body_xml"]
parallel = Path("/tmp/ctext-whole.txt").read_text()
payload = {"op": "parallel_punct", "mode": "segmented", "body_xml": body, "parallel_text": parallel}
proc = subprocess.run(
    ["python3", "-c", "from kanripo_import.ljb_bridge import cli_main; cli_main()"],
    input=json.dumps(payload),
    text=True,
    capture_output=True,
    cwd=plugin / "python",
    env={**os.environ, "PYTHONPATH": str(plugin / "python")},
    check=True,
)
print(json.loads(proc.stdout)["coverage"])
PY
```

`mode: "segmented"` merges split commentary notes (`</note></p><p><note type="comm">`), then matches basetext and `<note type="comm">` segments separately against ctext-style inline commentary. Use `mode: "tape"` (default) for a single contiguous Han sticker.

## Install in LJB

1. `npm run build:kanripo-import` in `plugins`
2. `npm run dev:desktop` in `leaf-writer`
3. Tools → Plugins → install `packages/plugin-kanripo-import`, enable per project

### Single-juan import (Kanripo API)

The import dialog can fetch **one 卷** via the [kanripo](https://pypi.org/project/kanripo/) API client (`pip` name: `kanripo`, import: `import kanripo`) instead of cloning the whole GitHub repo. It is bundled in the desktop Python runtime alongside sanmiao (`npm run python:download` in `apps/desktop`).

Enter juan as `001` or full loc `KR1a0030_001`. Bridge op: `fetch_juan` with `kr_id`, `juan`, `cache_root`.
