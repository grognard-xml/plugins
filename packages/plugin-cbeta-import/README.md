# CBETA import plugin

Hybrid plugin: clone CBETA (漢文電子佛典) works from GitHub, **split each work by
juan**, and translate CBETA P5 markup to project TEI. Design and every
keep/cut/standoff ruling: **[leaf-writer/docs/cbeta-import-planning.md](../../../leaf-writer/docs/cbeta-import-planning.md)**.

**Runtime:** `import` touches no network. The `cbeta-xml-p5` checkout is fetched
once by an explicit **Sync corpus** action (`git clone --depth 1 --branch
<DATA_VERSION_TAG>`) into `LJB_PLUGIN_CACHE_PATH`
(`<userData>/plugin-cache/cbeta-import/`), injected by the desktop bridge;
dev falls back to `data/`. Bundled in the installed plugin: `data/metadata/`
(work-info, gaiji table, prebuilt catalog index) and `data/schema/` (CBETA
`_p5.rng` / `_p5.sch` with the LJB loosenings). Without a prebuilt index the
plugin scans the synced checkout and caches `catalog_index.json` next to it.

## Layout

| Piece | Location | Status |
| --- | --- | --- |
| Renderer entry (loads host UI) | `src/register.ts` | done |
| JSON bridge (`status`/`sync`/`install_from_source`/`search`/`resolve`/`convert`) | `python/cbeta_import/ljb_bridge.py` | done |
| **Juan splitter** | `python/cbeta_import/juan_split.py` | **done** (top-level `<milestone unit="juan">` / `<cb:juan fun="open">`); straddling-div split is TODO — planning §5.4 |
| **Per-juan apparatus** (§5.5) — carry `<back>` pruned to each juan's anchors (`<app from/to>` whose ids occur in that juan); `<lb>`/`<pb>`/`<anchor>` milestones kept | `juan_split.attach_apparatus` + `serialize_juan_body` | **done** — juan files now emit `<text><body>…</body><back>…</back></text>`; host splices `<back>` into the skeleton |
| **Multi-file id safety** — file 2..N's `xml:id`s (`beg_1`, `fx…` streamed ids) + their `@from`/`@to`/`@target` pointers namespaced with the file stem before concat | `juan_split.prefix_ids` | **done** — no duplicate `xml:id` in a multi-file work's output (§5.5 / §10.1) |
| In-place reductions (gaiji resolve, drop `@style`, drop `R135`/`R138` `lb`, drop `note[@type=orig]`, `cb:yin`/`cb:fan`/`cb:sg`→`<note type="gloss">`) | `python/cbeta_import/cbeta_tei.py` + `gaiji.py` + `downgrade.py` | done — the phonetic-gloss downgrade is **unconditional** (§5.2) |
| **Cross-family downgrades** — `cb:tt`/`cb:t`→`<seg subtype>` (§5.1), `cb:juan`→drop-open / `<trailer>` (§5.4), `cb:div`→`div` + `cb:mulu`→`<div>` nesting or `<milestone unit="mulu">` breadcrumb (§5.3), `cb:*` attrs→plain TEI attrs / drop + `cb:docNumber`→`<label>` + `cb:dialog`→`<div>` (§5.6) | `python/cbeta_import/downgrade.py` | **done** — runs only when the target project is not CBETA-family; leaves zero `cb:` in the output |
| **Corpus sync** — `git clone`/`fetch` at the pinned tag, `install_from_source` (local clone / dir / `.zip` / `.tar[.gz]`), `status` | `python/cbeta_import/corpus_sync.py` | **done** (live clone covered by an env-gated integration test) |
| **Catalog index** — scan checkout → work id / title / dynasty / juan count, multi-file grouping, `search`, `resolve_work_files`; prefers a prebuilt `catalog_index.json` | `python/cbeta_import/catalog_index.py` | **done** |
| **Multi-file works** (`T0220`, `L1557`, …) — planning §5.7 | `cbeta_tei.convert_cbeta_work` + `juan_split.stitch_cross_file_juan` | **done** — concatenate `<body>` + `<back>` in volume order (ids namespaced, above), split, then **stitch**: adjacent juan slices with the same `@n` (a juan re-anchored by a repeated `<milestone>`/`<cb:juan>` in the next file) are merged, dropping the duplicate markers; unmarked continuation content is already folded in by the split. Each stitch is recorded in `warnings` + the juan's `straddles` |
| **Work metadata + authority** — CBETA-header extraction (title, byline→dynasty/names/role, Taishō vol·no, 卷數), best-effort byline parser, `work_info.json` enrichment (dynasty, 部類, contributors resolved to DILA / Norbert / Wikidata), `build_tei_header` | `python/cbeta_import/metadata_xml.py` | **done** — `convert` returns `title` / `dynasty` / `category` / `taisho_vol·no` / `authorship[]` / `work_qid`; the host wrapper turns `authorship` into `<author ref=…>` |
| **Bundled metadata + schema build** — `work_info.json` + rich `catalog_index.json` from `Authority-Databases/authority_catalog` (title, dynasty, 部類, juans, contributors→DILA ids); file grouping from `--corpus` **or** `--file-list` (a GitHub tree listing — no checkout); optional `--crosswalk` (DILA→Norbert/Wikidata) and `--authority-person` (dates, QIDs) enrichment; `cb_gaiji.json` | `scripts/build-cbeta-metadata.py` | **done + run** — `data/metadata/{work_info,catalog_index}.json` bundled: **5,631 works**, 4,265 with a DILA id, 756 with a Norbert id, 2,847 with person dates; **5,623/5,631 with a resolved file list** (incl. multi-vol: `T0220`→15 files, `L1557`→4). 8 obscure works (`JB271`…) absent from the xml-p5 tree; `cb_gaiji.json` empty (per-file `<charDecl>` is the source) |
| **schema loosenings (`ljb-cbeta-loosen v2`)** — CBETA's flat `cbeta-p5.rng` (`tei_`-prefixed, ~570 defines) widened. v1 (tagging apparatus): `@ref`/`@key` on `title`/`author`/`byline`/NE (per-define, guarded against existing decls), the NE inventory added to `tei_model.phrase`, `<date>` extended with Sanmiao parse children + resolution attrs (in sync with `sanmiaoSchemaMerge.ts`). v2 (shared import target for Daozang / Kanripo / Wikisource / BDRC, which emit plain TEI markup): `tei_div` matches **both** `<cb:div>` and TEI-namespace `<div>` (reaches every division context), `<creation>` content `macro.phraseSeq.limited`→`macro.phraseSeq` (admits `<date>`), `@scheme` on `<keywords>` optional, optional `@role` on `<author>`/`<editor>`. Schematron passes through. Every step idempotent; output compiles as RelaxNG and lxml-validates both `<div>` and `<cb:div>` bodies | `scripts/loosen_schema.py` (called by `build:metadata --schema`) | **done + run** — `data/schema/cbeta_p5.rng` bundled |
| Host UI module | `leaf-writer/…/hostModules/cbetaImportUi.ts`, `dialogs/cbetaImport/`, `apps/commons/…/cbetaImportXml.ts`, `DialogType`/`useDialog`/`index.ts` wiring, File-menu item in `apps/desktop/src/main.ts`, `LJB_PLUGIN_CACHE_PATH` + long-op timeout in `pluginPythonBridge.ts` | **done** — talks to the generic `pluginsInvokePython('cbeta-import', {op})` bridge. Dialog has **Sync from GitHub** / **Install from folder…** (reuses `pluginsPickInstallFolder`) / **Re-sync** buttons wired to `{op:'sync'\|'install_from_source'}` |

## Build & check

```bash
npm install                                    # in plugins/
npm run build   -w @ljb/plugin-cbeta-import     # dist/register.mjs
npm run test    -w @ljb/plugin-cbeta-import     # python/tests
npm run smoke   -w @ljb/plugin-cbeta-import     # manifest + register() wiring + python tests

# real metadata build (all flags optional; no-arg = placeholders):
python3 scripts/build-cbeta-metadata.py \
  --authority-catalog /path/to/Authority-Databases/authority_catalog/json \
  --authority-person  /path/to/Authority-Databases/authority_person/Buddhist_Studies_Person_Authority.xml \
  --crosswalk         /path/to/dila-norbert.csv \
  --corpus            "$LJB_PLUGIN_CACHE_PATH/corpus/xml-p5" \
  --schema            /path/to/cbeta-schema
```

## Open items (planning §10)

1. ~~`xml:id` collision~~ — resolved. CBETA-internal (multi-file) handled by
   `prefix_ids`. LJB-vs-CBETA: LJB's editor ids are `dom_N`
   (`tinymce.DOM.uniqueId`), stripped on save by `cwrc2xml`; CBETA `xml:id`
   round-trips verbatim via the `_attributes` blob. No prefix reservation
   needed.
2. ~~Does CBETA's `.sch` fire on inserted markup?~~ — resolved: its only 3
   rules require `@spanTo` on `addSpan`/`damageSpan`/`delSpan`; `.sch` passes
   through untouched (`loosen_schema.loosen_sch`).
3. ~~`cb:type` leave or rename~~ — resolved: kept in CBETA-family mode,
   renamed to `@ana` cross-family (`downgrade.structural`).
4. Sanity-check `downgrade.phonetic_glosses` against a real 音義 juan (the
   fixture is synthetic; Huilin's 一切經音義 may not use `cb:yin` at all).
