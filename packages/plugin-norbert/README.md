# Norbert (`norbert`)

Premodern Chinese prosopography for Grognard.

## Person-name split (pass 2)

When the plugin is enabled, creating a new **person** entity:

1. Splits the canonical name into **family** + **given** using the Norbert surname table (longest match first — same logic as `segment_full_name2` in Norbert pass 2).
2. Prefills **romanization** from those parts (e.g. 王安石 → Wang Anshi).

Wired through the entity lookup “Create new” flow (`EntityLookupField`).

## Build

```bash
cd plugins
npm run build:norbert
npm run smoke:norbert
```

Surnames and geo-admin suffix tables are synced from `authoritypacks/packs/norbert/` (regenerate with `npm run compile:norbert` in `authoritypacks/`).

## Wikipedia noble titles

zh.wikipedia disambiguation pages such as [東海王](https://zh.wikipedia.org/wiki/东海王) list successive holders of a fief + rank (封地 + 爵位), often with posthumous names (謚). The plugin includes a parser aligned with Norbert’s `person_nt` fields (`fief`, `pn`, `nt`, dynasty section, person, reign years).

Parse the bundled fixture (offline):

```bash
cd plugins/packages/plugin-norbert
npm test
node scripts/fetch-wiki-noble-titles.mjs \
  --fixture src/wikiNobleTitles/fixtures/donghai-wang.wikitext \
  --title 东海王
```

Fetch from Wikipedia (requires network; crawls `Category:三字封號消歧義` by default).
Requests are **slow by design** (~2 s between calls) to stay within Wikimedia limits.

```bash
cd plugins/packages/plugin-norbert
npm run fetch:wiki-noble-titles -- --limit 20

# full crawl (one page per request; may take an hour+):
npm run fetch:wiki-noble-titles

# if you hit 429 Too Many Requests, resume where you left off:
npm run fetch:wiki-noble-titles -- --resume --delay-ms 5000
```

**Via Tor** (with `tor` running locally on port 9050):

```bash
npm run fetch:wiki-noble-titles -- --proxy socks5://127.0.0.1:9050 --delay-ms 3000
# or set once in your shell:
export WIKI_PROXY=socks5://127.0.0.1:9050
export WIKI_DELAY_MS=3000
npm run fetch:wiki-noble-titles -- --resume
```

Useful flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `--delay-ms` | `2000` | Pause between API requests |
| `--batch-size` | `1` | Pages per request (keep at 1 for politeness) |
| `--proxy` | — | HTTP/HTTPS/SOCKS proxy (`socks5://127.0.0.1:9050` for Tor) |
| `--resume` | — | Continue from `data/.wiki-noble-titles.checkpoint.json` |
| `--limit N` | all | Fetch only the first N category members (testing) |

Output: `data/wiki-noble-titles.ndjson` — one JSON object per holder row, e.g.:

```json
{
  "source": "zh.wikipedia",
  "sourcePage": "东海王",
  "dynastySection": "汉朝",
  "fief": "东海",
  "pn": "恭",
  "nt": "王",
  "person": "刘彊",
  "startYear": 43,
  "endYear": 58,
  "confidence": "high",
  "needsReview": false
}
```

Rows with `needsReview: true` (different rank, missing dates, etc.) should be checked before importing into Norbert.

## Human review (Norbert ↔ Wikipedia)

After fetching and enriching wiki data, prepare a review spreadsheet:

```bash
cd plugins/packages/plugin-norbert
npm run prepare:wiki-review
# optional: only rows with some Norbert overlap
npm run prepare:wiki-review -- --only-matched
```

Output:

| File | Purpose |
|------|---------|
| `data/wiki-norbert-review.csv` | Open in LibreOffice/Excel — fill the **`action`** column |
| `data/wiki-norbert-review.ndjson` | Same rows, machine-readable |

The **`action`** column (your decision) accepts:

| action | Meaning |
|--------|---------|
| `link` | Same `person_nt` row — create wiki crosswalk only |
| `insert_nt` | Person exists in Norbert, add a new `person_nt` row |
| `update_nt` | Existing `person_nt` row — fill missing `pn` or dates from wiki |
| `skip` | Ignore |
| `review` | Needs manual research |

`suggested_action` is pre-filled; override it in `action` when you disagree.

## Compile plugin asset (after review)

The shippable output is a **static JSON asset** — Norbert person ids/names + wiki links.
It does **not** include your full SQL dump and is safe to commit.

```bash
cd plugins/packages/plugin-norbert
npm run compile:wiki-nt-asset
# merges manual corrections from:
#   data/wiki-norbert-review.csv  (fief_corrected, pn_corrected, etc.)
```

Output (bundled with the plugin):

| File | Purpose |
|------|---------|
| `data/wiki-nt-links.json` | Full asset + metadata |
| `data/wiki-nt-links.ndjson` | One record per line (for streaming) |

Each record includes:

- **`wiki`** — fief, pn, nt, person, dates, Wikidata Q-id, Wikipedia URLs  
- **`norbert`** — `personId`, `ntInd`, `canName`, existing NT fields (when matched)  
- **`proposedNt`** — wiki-sourced NT fields for `insert_nt` / `update_nt` rows  
- **`action`** — `link`, `insert_nt`, `update_nt`, or `title_only`  
- **`searchStrings`** — composed title variants for tagging/disambiguation  

Raw crawl/review intermediates stay gitignored under `data/.gitignore`.

Policy baked in from your review:

| Case | `action` |
|------|----------|
| Matched person + NT | `link` |
| Person exists, NT missing | `insert_nt` |
| NT exists, wiki fills gaps | `update_nt` |
| Wiki only / ambiguous / manual 諡號 fixes | `title_only` (Wikidata link; user resolves person) |

Optional local SQL generation (your machine only, not shipped):

```bash
npm run apply:wiki-review   # writes data/wiki-apply.sql (gitignored)
```

## Authority packs

When enabled, the auto-tagging dialog offers:

- **Norbert persons** → `persName` tag bomb
- **Norbert offices (官名)** → `roleName` tag bomb (period-tuned office strings from your Norbert SQL)
- **Norbert + Wikipedia noble titles** → bundled `persName` pack for fief + rank + person combinations, with the Wikipedia-reviewed rows merged into the Norbert title pattern set

Use alongside **CBDB offices** for broader coverage. Each Norbert row keeps its
own source id; conservatively matched rows also carry the canonical CBDB office
id.

The noble-title asset is shipped as `data/wiki-nt-links.ndjson` and is generated
from the review workflow in this plugin, not copied directly from the SQL dump.
That keeps the runtime pack portable while still preserving the Norbert + wiki
crosswalk needed for tagging and disambiguation.

At runtime these rows are wrapped in the Grognard `AuthorityCandidate` envelope but
remain structured and compact. Grognard expands their fief, rank, posthumous name,
and personal-name combinations when the `norbert-wiki-nt` pack is loaded. The
runtime keeps full person-wrapper strings separate from standalone noble-title
strings, so a title-only hit cannot create a person wrapper. Rows with no
recoverable title string are retained only in the review workflow and are not
shipped as taggable candidates. When the Norbert persons pack is loaded in the
same run, its current alternate names are merged by Norbert person ID before
the wiki-title combinations are generated.

The plugin owns Norbert's position-sensitive office rule. When a resolved
office marked `followsOffice` immediately follows another resolved office, Grognard
retains the first as the inferred parent of the second and writes a
provenance-bearing `parentOf` assertion to `entities.xml`. Place + office
constructions remain contextual tagging and do not become office hierarchy.

## Enable in Grognard

Tools → Plugins → enable **Norbert**, then use entity lookup to mint a new person.
