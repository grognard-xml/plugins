# CHHIV composer: closing the gap with zi.tools (字统网)

## 0. Status and relationship to glyph_maker.md

This is a **new phase**, not a correction of `glyph_maker.md`. Phases 1 (project
glyph registry + basic KAGE composition) and 2 (GlyphWiki direct-containment
search) from that document are shipped and working. This document plans the
next increment: making the composer's *interaction design* — not just its
underlying data/rendering — genuinely competitive with a real, well-built tool
in this exact space.

Per the user's explicit instruction: **plan first, in writing, before any UI
code.** This document is that plan. Phases A, D, and B are implemented
(A and D committed; B is local, uncommitted). Phase C, below, is scoped
and not yet implemented.

## 1. What was actually observed (live, 2026-09-25)

zi.tools' compose page (`https://zi.tools/?secondary=ids`) was driven directly
rather than judged from the one screenshot the user shared. Findings:

- **Live IDS string, no lookup cost.** Typing into either component slot
  updates a visible IDS string (`⿰言?` → `⿰言某`) on every keystroke, before
  any "look this up" action. This is free — it's just concatenating the
  operator and the two components, exactly what our `composeIds` already
  does. zi.tools' UI treats it as a first-class, always-visible piece of
  feedback, not something tucked into a tooltip or a save-time computation.

- **A three-tier resolution model, checked in this order, on an explicit
  "組字/檢字 Form/Lookup" click** (this part *does* look like it costs a
  round-trip, unlike the free IDS string):
  1. **"認同已編碼字 / Unified encoded Unicode"** — the exact IDS
     composition already corresponds to a real, assigned Unicode codepoint.
     Tested live: `⿰言某` → 謀, `⿰言齒` → a real assigned character (confirmed
     against `cjkvi-ids` in §3: U+8B00 and U+2A619 respectively). Shown as a plain large
     character, not a drawn glyph. **This is a tier CHHIV does not have at
     all today.** Our own "Route A" check (`canonicalUnicodeChar`) only
     catches the narrower case where a *specific GlyphWiki entry* happens to
     be named after a bare Unicode codepoint — it says nothing about whether
     the IDS *structure itself* already has a standard decomposition
     matching a real character, independent of GlyphWiki.
  2. **"字統网收錄字 / Encoded in zi.tools"** — not a standard Unicode
     character, but present in zi.tools' own aggregated glyph database
     (presumably GlyphWiki plus other sources they ingest). Tested live:
     `⿰牙齒` → a real drawn compound glyph, shown in red, with this label.
     This is the tier our Phase 2 GlyphWiki search already covers, roughly.
  3. (Not directly observed — CJK combinatorics are dense enough that most
     plausible two-radical pairs land in tier 1 or 2 on the first few tries
     — but presumably a genuine "not found anywhere" state exists, matching
     our own "compose it fresh" fallback.)

- **A visual, shape-accurate layout diagram**, not a dropdown: the operator
  picker is a grid of small diagrams (the ⿰ icon actually *looks like* a
  vertical split, ⿱ looks like a horizontal split, etc.), and selecting one
  redraws the two/three edit slots in that exact shape — the edit surface
  *is* the diagram, not a separate preview next to an abstract control.

- **"直接輸入 Input"** — a toggle to switch from the visual slot editor to
  typing a raw IDS string directly. A power-user escape hatch, not a
  replacement for the visual mode.

- **"難輸入部件 Difficult Components"** — a helper for entering a component
  that has no ordinary keyboard input method (i.e. exactly CHHIV's whole
  reason for existing, one level down: composing a *component* you can't
  type is the same problem as composing a *character* you can't type).

- Operator grid has more icons than our 7 - the full 12 standard IDCs
  (⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻), not just the binary ones we shipped.

## 2. Gap analysis against the current CHHIV composer

| Capability | zi.tools | CHHIV today |
| --- | --- | --- |
| Live IDS string as you type | Yes | Yes (in `ComposePreview.ids`, shown as text) |
| Visual, shape-accurate operator picker | Yes (redraws edit slots; palette applies to the selected region, so the same click nests) | Yes (Phase C: palette plus a square; slots sit in the operator's shape) |
| All 12 IDS operators | Yes | 7 (binary only; ⿲⿳⿵⿶⿷ missing) |
| **IDS → already-assigned-Unicode check** | **Yes, tier 1** | **No** |
| "Found in our own gaiji database" check | Yes, tier 2 | Yes (Phase 2, direct-containment GlyphWiki search) |
| Recursive/nested composition in one view | Yes (implied by their editor being a general IDS-tree tool) | No — only via save-then-reuse-as-a-component-id across two separate composer sessions |
| Manual/raw IDS text entry | Yes ("直接輸入") | No |
| "Can't type this component" helper | Yes ("難輸入部件") | No (must already have a character to type, or a saved project glyph id memorized) |

The single most consequential gap is the missing tier-1 check. It is also,
per the general density of the CJK repertoire and what was just observed
firsthand (two out of two arbitrary test pairs landed in tier 1), likely to
fire *often* — probably more often than our own GlyphWiki search does. Not
having it means CHHIV will regularly generate a KAGE-rendered SVG gaiji for
something that is, in fact, an ordinary encoded character with full font/IME
support — the exact failure mode "Route A" was supposed to prevent, just
reached from a different angle (structure-first, not name-first).

## 3. IDS → Unicode decomposition table — investigated, real numbers (2026-09-25)

Unicode's own Unihan database does **not** normatively define IDS
decomposition as a character property. The de facto standard, open dataset
for this is the **CHISE IDS project**, distributed via `github.com/cjkvi/cjkvi-ids`
(`ids.txt`). Cloned and tested directly, not assumed from a README:

- **Format**, confirmed by reading the real file: tab-separated
  `U+XXXX<TAB>字<TAB>IDS[<TAB>altIDS...]`, e.g. `U+8B00	謀	⿰言某`. Some
  entries carry more than one alternate IDS (regional-standard variants,
  tagged `[GTKV]`/`[J]`/etc.) — 3,623 of 88,937 lines have 2+ variants; every
  variant is a separate valid lookup key mapping to the same character.
- **Size**: 88,937 raw entries, 91,708 unique IDS keys after expanding
  variants. Raw file 2.1 MB. Built as the same compact tuple-JSON format as
  the other two bundles: **91,708 entries, 1.15 MB uncompressed, 0.59 MB
  compressed** — by far the smallest and cheapest of the three bundled
  datasets (`kageCore.json` 17.8 MB, `glyphwikiCompoundIndex.json` 30.5 MB).
- **Coverage**: 68.4% of entries are supplementary-plane (CJK Ext B+) —
  consistent with the same encouraging skew found in `kageCore.json`'s seed
  distribution.
- **License, resolved favorably**: the `cjkvi-ids` README says `ids.txt`
  "follows CHISE's terms." Traced to the actual source: CHISE-IDS's own
  `.el` files carry the standard FSF header *"either version 2, or (at your
  option) any later version"* — GPL-2.0-**or-later**, not GPL-2.0-only. That
  matters: it means the "any later version" option can be exercised, making
  this combinable with Grognard's AGPL-3.0-only license under the same
  GPLv3/AGPLv3 §13 compatibility-clause reasoning already used for
  `@kurgm/kage-engine`. Worth an explicit citation in
  `THIRD_PARTY_NOTICES.md` (same treatment as kage-engine), but not a
  blocker.
- **Validated against what was just observed live on zi.tools**, not just
  self-consistency: looking up the exact IDS strings from section 1 against
  this table reproduces zi.tools' results exactly —
  `⿰言某` → 謀 (tier 1 hit, matches), `⿰牙齒` → not found (matches zi.tools'
  tier-2-only result). This is real confirmation the mechanism works, not
  just that the data parses.
- **Empirical hit-rate check against our own GlyphWiki compound index** (to
  calibrate the "likely fires often" claim from section 2, rather than
  generalizing from two anecdotal live tests): of 13,645 existing
  `glyphwikiCompoundIndex.json` entries whose two components are both
  ordinary Unicode characters, **5.2% (704)** already have an assigned
  Unicode codepoint under some ⿰/⿱ ordering. More modest than "often"
  suggested from the live spot-check, but still a real, non-trivial fraction
  of cases where CHHIV would otherwise manufacture an unnecessary gaiji for
  an ordinary encoded character — worth having regardless of the exact rate.
- Recursive-decomposition angle (does the same dataset give nested structure
  for free, useful for Phase D): not yet checked; defer until Phase D is
  actually scoped, no need to resolve it now.

**Decision: proceed.** Numbers are small, license is workable, and the
mechanism is validated against live zi.tools behavior. Phase A is unblocked.

## 4. Proposed phases

Small, validated slices again, matching how Phases 1-2 actually went (each
gated on real numbers before UI work, not before but not overbuilt either).

**Priority order (2026-09-25): A, then D, then B, then C.** Originally
written as A-B-C-D; D was reprioritized ahead of B/C after the very first
real manuscript character tried against the composer needed it (see Phase
D's own notes below) - direct evidence beats the original guess at ordering.

### Phase A — the missing tier-1 check (highest value, do first)

**Status (2026-09-25): done.**

- ~~Investigate `cjkvi-ids`~~ **done, see §3** — real size, license, format,
  and coverage numbers, validated against zi.tools' own live behavior and
  against our existing GlyphWiki compound index. Decision: proceed.
- `scripts/build-ids-unicode-index.mjs` builds
  `resources/ids/idsUnicodeIndex.json` (91,708 entries, 1.92 MB uncompressed
  / 0.59 MB compressed - the precise on-disk figure; §3's 1.15 MB was a
  JS-string-length approximation, corrected here) from `cjkvi-ids/ids.txt`.
  Reproducibility checked: re-running the committed script against the same
  source file byte-for-byte reproduces the committed artifact.
- `utilities/idsUnicodeIndex.ts`: exact-match lookup,
  `findEncodedCharacterForIds(idsString): string | null`. Tested both with a
  mock and against the real bundled data, locking in the exact zi.tools-
  validated examples from §1/§3 as a permanent regression test.
- Wired into `previewComposition` (`projectGlyphStore.ts`), checked before
  the GlyphWiki candidate search, as a new `existingUnicodeChar` field on
  `ComposePreview`.
- UI: when set, foregrounded above the plain SVG preview and the GlyphWiki
  candidates list - a large character, its codepoint, and an "Insert as
  plain text" button - not folded in as one candidate tile among several,
  since it's a qualitatively stronger result (the *structure itself* is
  already standard, not merely that some non-standard glyph happens to
  combine the same parts).
- Licensed and cited in `THIRD_PARTY_NOTICES.md` (GPL-2.0-or-later, same
  AGPL-combination reasoning as `@kurgm/kage-engine`).

### Phase B — all 12 IDS operators

- Add ⿲⿳⿵⿶⿷ to `kageCompose.ts`'s `boxesFor`/`IDS_OPERATORS`, same pattern
  as the existing 7, with default boxes reasoned the same evidence-based way
  the ⿰/⿱ overlap fix was (sample real GlyphWiki data for each new operator
  before picking numbers, not guess).
- ⿲/⿳ need a **third component slot** - the first structural change to the
  UI's data shape (`composeKageData`/`ComposePreview` currently hardcode
  "two components"). Worth doing as part of this phase rather than Phase C,
  since Phase C's visual redesign should be built against the final
  (2-or-3-slot) data shape, not redone afterward.

**Status (2026-09-25): done.**

- All 12 standard IDCs now in `IDS_OPERATORS`, each tagged with a
  `partCount: 2 | 3`. The five added (⿲⿳⿵⿶⿷) got simple, reasonable
  geometric defaults - the same rigor level ⿴/⿸/⿹/⿺ shipped with in Phase 1,
  not the real-data-mined overlap tuning ⿰/⿱ got later; worth the same
  treatment if visual feedback calls for it.
- Generalized the fixed two-component model to a variable-length one
  throughout the stack, not just at the edges: `composeKageData`/`composeIds`
  now take `names: string[]`; `ComposerSlot`'s `nested` case holds
  `parts: ComposerSlot[]` instead of fixed `first`/`second` fields;
  `ProjectGlyph.componentIds` is `string[]`, not a `[string, string]` tuple.
  `resizePartsForOperator` (composerTree.ts) is the one place that keeps
  `parts.length` in sync with the current operator's `partCount` - used both
  by the root composer state and by `SlotEditor`'s own nested case when its
  operator changes.
- All existing tests for the flat/binary case were updated to the new array
  calling convention rather than kept on a separate code path - confirmed
  the generalization didn't change binary-operator behavior (all previously
  passing tests pass again with the same assertions, just an array literal
  instead of two positional arguments).
- Real-data spot-check (not just unit tests against real `kageCore.json`,
  though those already exercise it): composing three real components (木木木,
  a "森"-shaped ⿲) renders correctly - 21 real polygons, no unresolved
  components.
- UI: the root operator picker and `SlotEditor`'s own nested picker both
  resize their `parts` array on operator change, padding with fresh empty
  leaves or truncating as needed - confirmed via a render test that selecting
  ⿲ mounts a third field.

### Phase C — visual layout editor (zi.tools WYSIWYG)

**Status (2026-09-25): implemented.** The stub that used to
live here only said "replace the dropdown with diagrams." The interaction
below was checked live on [zi.tools' compose page](https://zi.tools/?secondary=ids)
(`?secondary=ids`, WYSIWYG mode) on 2026-09-25, including nesting into an
empty slot and switching that nested slot from ⿱ to ⿴.

#### What the site actually does

Three regions, left to right:

1. **A palette of layout icons**, drawn as tiny pictures of the split
   (two columns, three rows, a box inside a box, and so on), sitting on
   top of the editing square. Not a dropdown of names.
2. **The editing square is the layout.** Choosing ⿰ draws a vertical
   dashed split and puts one text field in each half. Choosing ⿱ draws a
   horizontal split. Choosing ⿲ draws three columns. Choosing ⿴ draws an
   outer field with a smaller dashed field inside it. The placeholder in
   an empty field is 字.
3. **A result area beside the square.** As you type, an IDS string updates
   immediately (`⿲木??`, then `⿲木⿱??` once the middle column is itself
   split). A separate "組字/檢字 Form/Lookup" button resolves that string
   to a character. We already resolve continuously, so we do not copy
   that button.

The rule that decides *which* layout a palette click changes is
**selection**, shown as an orange border:

- With no field focused, the border is around the whole square, and a
  palette click changes the **outer** layout. Characters already typed
  stay, in order: switching from ⿱ (top = 木) to ⿲ moved 木 into the left
  column and added a third empty field. That is the same keep-or-pad
  behaviour `resizePartsForOperator` already has.
- Clicking a field focuses it (orange border on that field). The next
  palette click does **not** change the outer layout. It replaces **that
  field** with a nested layout. Confirmed on an empty middle column: it
  became a top/bottom pair, with an × in the corner of the new region.
  The outer character (木) and the untouched third column stayed put.
- The orange border then sits on the nested region. Another palette click
  changes **that region's** operator, not the outer one and not a brand-new
  level. Confirmed: the nested ⿱ became a ⿴ (outer field, inner dashed
  field) without touching 木 or the right-hand column. Blurring the field
  did not clear the selection.
- The × removes that nested region and restores a single field. We already
  have this as "flatten back to a single field."

So an empty field can become a layout. You do not have to type first.
The earlier idea — "once you start typing in a field, then you may nest"
— would block the ordinary case, which is composing the right-hand side
before you know which character goes there. The screenshots match the
selection rule, not the typing rule. **Follow the selection rule.**

One field holds one component (a character you can type, or a project
glyph id, as today). Do not split a field automatically because someone
typed several characters into it. 木木木 can be ⿲木木木, or ⿰木⿰木木, or
⿱木⿰木木, and the editor cannot know which. Nesting is how you say which.

#### What we copy, and what we leave

Copy:

- The palette, limited to the 12 operators we already implement
  (`IDS_OPERATORS` in `kageCompose.ts`).
- The square whose slots sit in that operator's shape, recursively, so a
  nested slot is the same square drawn inside its cell.
- The orange selection border, and the × that flattens a nested region.
- A live IDS string in the result area. `preview.ids` is already computed
  in `projectGlyphStore.ts` and is not shown.

Leave, on purpose:

- **⿼ ⿽ ⿾ ⿿ and ㇯.** They are on the zi.tools palette and are not in our
  12. ⿾ and ⿿ are a reflection and a rotation of a *single* component,
  which our tree cannot represent (every operator has 2 or 3 parts).
  Adding them is a geometry change, not a view change.
- **"難輸入部件 / Difficult Components."** A shape-picker for parts you
  cannot type. Still out of scope, as in the last section of this file.
- **"直接輸入 / Input."** Typing a raw IDS string (`LR日月` and similar
  abbreviations). Useful later, not required to fix the dropdown.
- **A lookup button.** Our preview already runs on every change: encoded
  Unicode character, drawn SVG, GlyphWiki candidates, then Save and insert.

#### How it sits on the code we have

Phase C does not change `kageCompose.ts`, `kageRenderer.ts`, or the save
path. The tree is already the data model (`ComposerSlot` in
`composerTree.ts`). `SlotEditor` and the root `<Select>` in
`ComposeCharacterDialog.tsx` are the pieces that still draw that tree as
a dropdown plus a vertical list of fields.

New UI state, alongside the tree: **which node is selected.**

- Default: the root. A palette click calls the existing
  `handleOperatorChange` / `resizePartsForOperator`.
- A focused leaf: the next palette click replaces that leaf with
  `{ kind: 'nested', operator, parts: empty leaves }`, which is what the
  "Compose this part" button does today, except the operator comes from
  the palette instead of always starting as ⿰.
- A selected nested node: a palette click changes that node's operator
  and resizes its `parts`, same as the nested `<Select>` does today.
- × on a nested node: replace it with `emptyLeafSlot()`, unless it had a
  single filled child worth keeping — see the open question below.

The square is CSS, not KAGE coordinates. `boxesFor` in `kageCompose.ts`
places ink in the 0–200 drawing space. The editor only has to *look*
like the operator:

| Operator | Editor shape |
| --- | --- |
| ⿰ | two equal columns |
| ⿱ | two equal rows |
| ⿲ | three equal columns |
| ⿳ | three equal rows |
| ⿴ | outer field as a frame, inner field centered |
| ⿵ ⿶ ⿷ | frame open on one side (bottom, top, or right), inner field in the opening |
| ⿸ ⿹ ⿺ | frame covering the named corner, inner field in the opposite corner |
| ⿻ | two fields stacked in the same box (overlap has no split line) |

A nested node fills its cell with the same table, one level down, and
draws the orange border and the ×. Dashed lines between siblings, as on
the site.

The dialog is opened with `maxWidth: 'xs'` in `chhivSymbolPaletteUi.tsx`,
which is why everything is currently one narrow column. The square and
the result need to sit side by side, so this phase widens that dialog
(MUI `sm` or `md`). Result column, top to bottom, reusing what the dialog
already renders: the IDS string, the encoded-character box, the SVG
preview, GlyphWiki candidates, warnings, Save and insert.

#### Open questions (resolve while building, not before)

- **Flattening a region that already has text.** The site's × was only
  tried on empty nested fields. If the scholar has typed into a nested
  region and clicks ×, dropping every child is harsh. Prefer: if exactly
  one child is filled, keep that child's text in the restored field;
  if several are filled, ask before discarding, or refuse until they
  clear the extras. Decide from the real control once it exists.
- **How you select the outer square again** after a field has been
  focused. On the site, clicking a field selects it, and blurring did
  not return selection to the root. We need an explicit click on the
  square's padding (not on a field) to select the root, otherwise there
  is no way back to "change the larger layout."
- **Enclosure fields are cramped.** A frame-shaped slot has little room
  for a text caret. A small centered field, as on the site, is enough
  for one character or a short id (`chhiv-0003` will wrap or scroll;
  `size="small"` and horizontal scroll is acceptable). Do not invent a
  second editing mode for ids.

### Phase D — recursive nesting in one view

**Reprioritized (2026-09-25): moved ahead of B and C.** Triggered by the
first real manuscript example tried against the composer — a character
whose right-hand side was itself an unresolved two-part compound, not a
single existing character or id. The save-then-reopen workaround
(`plugins/glyph_maker.md`'s own recursion mechanism, already shipped and
tested) is functionally correct but was immediately felt as friction on
the very first non-trivial real case, not a hypothetical.

**Design** (deferred in the original write-up pending a real case to design
against - this is that case):

- The composer's state changes from a flat pair of strings to a tree:
  ```ts
  type ComposerSlot =
    | { kind: 'leaf'; input: string }   // typed char or existing project-glyph id, same as today
    | { kind: 'nested'; operator: IdsOperator; first: ComposerSlot; second: ComposerSlot };
  ```
  A slot starts as an empty leaf; clicking "Compose this part" on a slot
  turns it into a `nested` slot with its own operator picker and its own two
  (recursive) sub-slots, rendered indented/inline in the same dialog.
- **No changes needed to `kageCompose.ts` or `kageRenderer.ts`.** A new pure
  function (`composerTree.ts`, or added to `kageCompose.ts`) recursively
  resolves a slot to `{ name, components }`: a leaf resolves via the
  existing `resolveComponentInput`, no extra components; a nested slot
  recursively resolves its two children, synthesizes a fresh temporary name
  for itself, builds its own KAGE data via the existing `composeKageData`,
  and returns that name plus its own data merged with both children's
  component maps. The live preview becomes: resolve both top-level slots,
  `composeKageData` the root, `renderKageToSvg(rootData, mergedComponents)`
  - the exact same two calls the flat version already makes, just fed a
  richer `extraComponents` map. This is why no rendering-layer changes are
  needed - the recursion was already there, waiting to be given a tree
  instead of two strings.
- **On save**, walk the tree bottom-up and persist every `nested` node as
  its own real `ProjectGlyph` (allocating a real id, rendering and caching
  its own SVG, adding it to the registry) - not just the root. This matches
  glyph_maker.md's own principle directly: "never throw away structure once
  the scholar supplies it." Only the root gets `<g ref>`-inserted into the
  document; the intermediate node(s) are saved and immediately available
  for reuse in a future composition, exactly as if the scholar had composed
  and saved them one at a time - just without leaving the dialog to do it.
- New orchestration function needed in `projectGlyphStore.ts`
  (`composeTreeAndInsertProjectGlyph`), reusing the existing
  `persistAndInsertProjectGlyph` tail for the root and a similar
  persist-without-insert step for each intermediate node.
- UI: `ComposeCharacterDialog.tsx`'s two flat `<TextField>`s become a
  recursive `<SlotEditor>` component (leaf mode = today's text field plus a
  "Compose this part" button; nested mode = an inline operator picker and
  two child `<SlotEditor>`s, plus a "flatten back to a single field"
  escape hatch).
- A saved intermediate node still needs a human-legible way to be
  recognized/reused later (today's flat composer already surfaces this
  reasonably: type its id, see the live preview render it). No new UI
  mechanism required beyond what already exists for reusing a project
  glyph id - confirmed true once nesting shipped (an intermediate node is a
  perfectly ordinary `ProjectGlyph`, findable/reusable exactly like any
  other saved composition).

**Status (2026-09-25): done.** Landed almost exactly as designed above, plus
one real bug the design didn't anticipate:

- `utilities/composerTree.ts` - the `ComposerSlot` type + `isSlotFilled`,
  unit tested including arbitrary-depth nesting.
- `utilities/projectGlyphStore.ts` - `previewComposerTree` and
  `composeTreeAndInsertProjectGlyph`, with the existing flat
  `previewComposition`/`composeAndInsertProjectGlyph` now thin wrappers over
  them (two leaf slots). Confirmed byte-for-byte behavior-compatible: all 15
  pre-existing tests for the flat functions still pass unchanged against the
  new tree-based implementation underneath.
- **Found and fixed a real bug while testing the nesting case**:
  `kageRenderer.ts`'s `findUnresolved` only ever checked the top-level
  `kageData`'s own two references - it never looked inside what
  `extraComponents` values themselves referenced. That assumption was safe
  as long as every `extraComponents` entry was a previously-*saved* (already
  validated) project glyph; Phase D's live tree preview breaks it, since a
  `nested` slot's synthetic component is deliberately *not yet* validated.
  A broken leaf three levels deep produced an empty `unresolvedComponents`
  at the root - caught by a real test, not inspection - fixed by also
  scanning every `extraComponents` value's own references (one flat pass
  covers arbitrary depth, since the tree resolver already flattens the
  whole tree into that one map).
- `dialogs/composeCharacter/SlotEditor.tsx` - the recursive editor: a leaf
  is a text field plus a "Compose this part" button; a nested slot is an
  operator picker, a "flatten back to a single field" escape hatch, and two
  recursive `<SlotEditor>` children, indented.
- Added `ComposeCharacterDialog.render.test.tsx`, matching this codebase's
  existing "render smoke test" convention (see
  `apps/commons/src/desktop/sidebar/SidebarDatabaseTab.render.test.tsx` for
  why these exist) - mounts the dialog and confirms clicking "Compose this
  part" successfully mounts the nested sub-editor, exercising the
  self-referential render path directly.

### Not planned here (still out of scope, unchanged from glyph_maker.md)

Stroke-level editing, geometric similarity search, manual drag/scale
geometry, live GlyphWiki network access, "difficult components" search-by-shape
(worth revisiting once Phase A-B land, since our own bundled `kageCore.json`
already has geometry for ~140k characters that a simple component-search UI
could reuse - but not part of this plan's scope).

## 5. Decision needed before Phase A starts

Same shape of gate as every prior phase: **investigate `cjkvi-ids` (or
whatever the real best-available IDS decomposition dataset turns out to be),
report actual size/license/format/coverage numbers, then decide** whether to
bundle it, and in what form - before writing `idsUnicodeIndex.ts` or touching
the UI.
