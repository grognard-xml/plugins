# CBETA import — bundled metadata refresh recipe

How to regenerate everything under `packages/plugin-cbeta-import/data/` when
CBETA ships a new `xml-p5` release (or the DILA authority data moves). Nothing
here runs in CI or at plugin install time — it is a **maintainer-only**,
network-touching batch. The output is committed to the repo.

Design rationale for every keep/cut lives in
`leaf-writer/docs/cbeta-import-planning.md` (§1, §10). This file is only the
mechanical "which repos, which flags, in what order".

---

## 0. What gets built

| Output | Built by | Source(s) |
| --- | --- | --- |
| `data/metadata/work_info.json` | `scripts/build-cbeta-metadata.py` | authority catalogue + person authority + crosswalk |
| `data/metadata/catalog_index.json` | same | authority catalogue + **file grouping** (`--corpus` *or* `--file-list`) |
| `data/metadata/gaiji/cb_gaiji.json` | same | `--gaiji` dir (best-effort; usually stays `{}` — see §5) |
| `data/schema/cbeta_p5.rng` / `.sch` | `scripts/loosen_schema.py` (via `--schema`) | CBETA published RNG/SCH + Grognard loosenings |

The pinned corpus release is `DATA_VERSION_TAG` in
`python/cbeta_import/constants.py` (currently **`2026R1`**). Bump it there first;
it is stamped into every imported file's `<revisionDesc>`.

---

## 1. Upstream repos

All from `python/cbeta_import/constants.py`:

| Const | Repo | Used for |
| --- | --- | --- |
| `XML_P5_REPO` | `https://github.com/cbeta-org/xml-p5` | the TEI corpus itself; `--corpus` grouping + header fallback scan. **Note:** `cbeta-org/xml-p5`, *not* `DILA-edu/cbeta-xml-p5`. |
| `METADATA_REPO` | `https://github.com/DILA-edu/cbeta-metadata` | `creators/creators-by-canon/` (contributor-id fallback), `gaiji/` |
| `CATALOG_REPO` | `https://github.com/DILA-edu/cbeta-catalog` | the authority catalogue JSON (`--authority-catalog`). The old `cbeta-metadata/catalog/` folder was deprecated 2026-05-21; confirm this repo name is still current (`constants.py` has a TODO on it). |
| gaiji repos | `cbeta-org/gaiji-CB`, `cbeta-org/sd-gif`, `cbeta-org/rj-gif` | only if you want to attempt a real `cb_gaiji.json` (§5) |

Person authority (`--authority-person`) is the DILA **Buddhist Studies Person
Authority** — `Buddhist_Studies_Person_Authority.xml`. Local copies seen at
`leaf-writer/databases/` and `data/authority_person.*/`; otherwise pull from the
DILA authority-databases distribution.

Schema (`--schema`) — a checkout of CBETA's published RelaxNG/Schematron
(`cbeta-p5.rng` / `.sch`). `loosen_schema.py` applies the `grognard-cbeta-loosen v2`
widenings; the `.sch` passes through unchanged.

```bash
mkdir -p ~/cbeta-refresh && cd ~/cbeta-refresh
git clone --depth 1 --branch 2026R1 https://github.com/cbeta-org/xml-p5.git
git clone --depth 1 https://github.com/DILA-edu/cbeta-catalog.git
git clone --depth 1 https://github.com/DILA-edu/cbeta-metadata.git
# schema: from wherever CBETA currently publishes the P5 grammar
```

---

## 2. DILA → Norbert / Wikidata crosswalk (`--crosswalk`)

The build wants a `dila_id → {norbert_id, wikidata_qid}` table. It accepts CSV
(any columns containing `dila` + `norbert`/`wikidata`) or JSON
(`{dila_id: norbert_id}` or `{dila_id: {...}}`).

Extract it from the **authority-extraction Norbert pack**:
`authority extraction/dist/authority-packs/norbert/concordance.ndjson`
(rebuild that pack from the `authority extraction/` repo if stale).

Each line is one concordance record; the ones we want have
`metadata.matched.source == "dila"`:

```jsonc
{"authorityId":"Norbert:1495:dila:A002484", ...,
 "metadata":{"norbert":{"authorityId":"1495"},
             "matched":{"source":"dila","authorityId":"A002484"}}}
```

Extraction (yields ~1,500 pairs as of the 2026-07-25 Norbert pack):

```bash
python3 - <<'PY'
import json
src = "authority extraction/dist/authority-packs/norbert/concordance.ndjson"
out = {}
for line in open(src):
    if not line.strip():
        continue
    md = json.loads(line).get("metadata", {})
    if md.get("matched", {}).get("source") == "dila":
        out[md["matched"]["authorityId"]] = {"norbert_id": md["norbert"]["authorityId"]}
json.dump(out, open("dila-norbert.json", "w"), ensure_ascii=False, indent=1)
print(len(out), "DILA ids -> dila-norbert.json")
PY
```

Wikidata QIDs mostly arrive via `--authority-person` (the person authority XML
carries a `Wikidata` ref per id), so the crosswalk can be Norbert-only. If you
want QIDs in the crosswalk too, add them from
`authority extraction/dist/authority-packs/wikidata/dila-wikidata-concordance.ndjson`.

---

## 3. File grouping — `--corpus` vs `--file-list`

`catalog_index.json` needs, per work, the list of `xml-p5` file stems
(multi-volume works span several: `T0220`→15, `L1557`→4).

- **`--corpus <checkout>`** — point it at the synced `xml-p5` checkout
  (`/Users/daniel/Corpora/cbeta-xml-p5`, or a fresh `git clone --branch 2026R1`).
  `build_index_from_corpus` scans it and keys works by canon + text number.
  **This is the base build.**
- **`--file-list <paths.txt>`** — newline-delimited `xml-p5` paths, no checkout.
  Only for when you cannot check out the corpus; resolves fewer works.

  ```bash
  gh api repos/cbeta-org/xml-p5/git/trees/2026R1?recursive=1 \
    --jq '.tree[].path | select(endswith(".xml"))' > xml-p5-files.txt
  ```

### Known grouping misses — the "repair" pass

A plain `--corpus` build of 2026R1 leaves **879** works with `files: []`. **865**
of those are a *genuine* gap — catalogue entries with no file anywhere in
`cbeta-org/xml-p5` @ 2026R1 (verified against GitHub's own tree): ~441 卍續藏
`X####`, ~373 嘉興藏 `JA###`/`JB###`, ~34 補編 `B####`, a few `G`/`YP`. Those
correctly stay empty — a fabricated stem 404s on import, and `resolve_work_files`
raises a clear `FileNotFoundError` for them.

The other **~14** are real files the grouper mis-keys and must be repaired:

| Pattern | Example | Real file(s) |
| --- | --- | --- |
| `G####` (canon `G`, zero-padded volume) | `G2202` | `G086n2202` |
| `G####` | `G2241` | `G103n2241` |
| `YP####` multi-volume | `YP0011` | `YP05n0011`, `YP06n0011` |

The committed `catalog_index.json` was hand-repaired for these (its `built_from`
reads `"… + files repaired from xml-p5 2026R1"`) — the repair was an ad-hoc
snippet, not a committed script. Until `build_index_from_corpus` /
`group_stems` learn these two shapes, after a fresh build **diff the new empties
against the old** and carry over any non-`X`/`J`/`B` id whose `vol`-based stem
(`<vol>n<textnum>`) actually exists in the checkout:

```bash
python3 - <<'PY'
import json, glob, os
C = "/Users/daniel/Corpora/cbeta-xml-p5"
stems = {os.path.basename(p)[:-4] for p in glob.glob(C + "/*/*/*.xml")}
idx = json.load(open("data/metadata/catalog_index.json"))
CAT = {}                     # merge Authority-Databases/authority_catalog/json/*.json
for jf in glob.glob("<authority_catalog>/json/*.json"):
    d = json.load(open(jf))
    if isinstance(d, dict): CAT.update(d)
fixed = 0
for w in idx["works"]:
    if w["files"]:
        continue
    vol = str(CAT.get(w["work_id"], {}).get("vol", ""))
    tn = w["work_id"][len(w["canon"]):]
    for cand in (f"{vol}n{tn}", f"{vol}n{tn.zfill(4)}"):
        if cand in stems:
            w["files"] = [cand]; fixed += 1; break
print("repaired", fixed, "works")
idx["built_from"] = idx["built_from"].split(" + files repaired")[0] + " + files repaired from xml-p5 2026R1"
json.dump(idx, open("data/metadata/catalog_index.json", "w"), ensure_ascii=False)
PY
```

(Multi-volume `YP` works need both stems — extend the candidate loop or fix them
by hand; there are <10.)

---

## 4. Full build command

```bash
cd plugins/packages/plugin-cbeta-import

python3 scripts/build-cbeta-metadata.py \
  --authority-catalog ~/cbeta-refresh/cbeta-catalog/json \
  --authority-person  ~/cbeta-refresh/Buddhist_Studies_Person_Authority.xml \
  --creators          ~/cbeta-refresh/cbeta-metadata/creators/creators-by-canon \
  --crosswalk         ~/cbeta-refresh/dila-norbert.json \
  --corpus            ~/cbeta-refresh/xml-p5 \
  --schema            ~/cbeta-refresh/cbeta-schema \
  --gaiji             ~/cbeta-refresh/cbeta-metadata/gaiji     # optional, see §5

# then, from plugins/:
npm run build:cbeta-import          # dist/register.mjs
npm run test  -w @grognard/plugin-cbeta-import
npm run smoke -w @grognard/plugin-cbeta-import
npm run verify:bundled              # checks data/ is present & well-formed
```

Every flag is optional; a missing source just drops its enrichment. Run with
**no** `--authority-catalog` and the script is a no-op that leaves the bundled
files untouched (the release pipeline calls it that way — it must never clobber
a real build with placeholders).

Sanity numbers for a good `--corpus` build of 2026R1 (compare to
`git diff --stat` on the JSON): ~5,600 works, ~4,300 with a DILA id, ~750 with
a Norbert id, ~2,850 with person dates, ~4,766 with a resolved file list
(5,631 − 865 genuine gap; see §3).

---

## 5. `cb_gaiji.json` — deliberately empty

`data/metadata/gaiji/cb_gaiji.json` is `{}` and that is the intended state.
CBETA gaiji (`<g ref="#CB…">`) are resolved **per file** from that file's own
`<charDecl>`/`<char>` block at import time (`gaiji.py`), which is authoritative
and always in sync with the text. A bundled global table would only be a
fallback for PUA residue, and PUA residue legitimately stays as `<g>` (valid
TEI). `build_gaiji` only picks up a table if `--gaiji` points at a dir with a
recognised `gaiji.json`/`cb-gaiji.json`/`gaiji_unicode.json`; the CBETA
`gaiji-CB` repo does not ship one in that shape, so the result is `{}`. Leave
it unless the import path ever needs a cross-file lookup.

---

## 6. Commit

```
data/metadata/work_info.json
data/metadata/catalog_index.json
data/metadata/gaiji/cb_gaiji.json      # if it changed
data/schema/cbeta_p5.rng
data/schema/cbeta_p5.sch
python/cbeta_import/constants.py        # DATA_VERSION_TAG bump
```

Update the counts line and the `catalog_index.json` `built_from` / gap
description in `packages/plugin-cbeta-import/README.md` (§ "Bundled metadata +
schema build") and the open-items list to match the new build.
