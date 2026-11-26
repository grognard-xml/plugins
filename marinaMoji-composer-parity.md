# CHHIV composer: marinaMoji layout parity

## Decisions (2026-11-25)

1. **Keep three CHHIV menu items** — Symbols…, Insert existing glyph…, Compose
   character…. Do **not** merge into one entry. Only the Compose dialog is
   rebuilt to match marinaMoji’s three-column character composer.
2. **Rich character info** — ship marinaMoji-style `char_info` (Unihan +
   cjkvi / tghb / 入管 / GlyphWiki itaiji variants, old/new forms, etc.), not a
   thin Unihan-only extract.

## Target layout (Compose character…)

| Region | Content |
|--------|---------|
| **Left — Construct** | 12 IDS operators, nested layout square, editable IDS (`LR日月` / `⿰日月`), Next form |
| **Middle — Examine** | Tabs: Character (specimen + char_info + variants) \| Components (catalogue; Phase 2) |
| **Right — Discover** | Break apart, Find by components + strokes (Phase 1), results grid |
| **Footer** | Clear · Adjust layout… (Phase 3) · Copy · Insert · (dialog Close) |

TEI insert path unchanged: encoded Unicode → plain text; otherwise project
glyph + `<g ref>` via existing `projectGlyphStore` / `insertGlyph`.

## Phases

| Phase | Scope | Status |
|-------|--------|--------|
| **0** | Three-column shell; wire existing compose / break-apart / save; editable IDS + abbreviations; Character tab specimen; char_info load + display when a character is in focus; footer Clear / Copy / Insert; Adjust + Find + Components stubbed | **done** |
| **1** | Find by components + stroke filter + results → examine | **done** |
| **2** | Components catalogue + difficult components; variant chips fully interactive | **done** |
| **3** | Adjust layout…; project-glyph browse in Discover (optional) | **done** |

## Data

- Copy / rebuild `char_info.tsv` from marinaMoji’s `build_char_info.py` pipeline
  into `packages/cwrc-leafwriter/resources/charInfo/` with Unicode notice.
- Runtime loader: `utilities/charInfo.ts` (lazy Map by character).

## Phase 3 notes

- **Adjust layout…** opens a modal over the composer. Only the **root**
  operator’s component boxes are edited (KAGE 0–200). Drag / resize handles,
  numeric Left/Top/Width/Height, snap, centre, reset. Applied boxes feed
  `composeKageData` / preview / Save; if they differ from defaults, Unicode
  Insert and GlyphWiki candidates are suppressed (hand-tuned geometry).
- **Project glyphs** appear at the bottom of Discover. Click inserts via
  `insertProjectGlyphAtCursor` (`reuseExistingDeclaration`); composition
  slots are left alone.

## Out of scope for this track

- Merging Symbols / Existing glyph into Compose
- IME / system-wide insert
- Online GlyphWiki fetch (stay offline-first)
- OpenCC inside the composer
- Nested-slot layout adjust (marinaMoji can adjust deep boxes; Grognard
  Phase 3 is top-level only)
