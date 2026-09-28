# CHHIV: Find-or-Compose System for Unencoded Chinese Characters

## 0. Scope: not Chinese-only

This document is titled around Chinese palaeography because that's the motivating case
(CHHIV, Laetitia Chhiv's transcriptions), but nothing in the design below is
Chinese-specific, and it shouldn't become so. GlyphWiki's own strongest coverage is
historical Japanese kanji variants (arguably stronger there than for Warring-States Chu
forms), so a composer built on it is at least as useful for Japanese-language projects
out of the box — no extra engineering, just don't hardcode Chinese-only framing into the
composer's UI copy. Grognard's toolbar registration (`chhivSymbolPaletteUi.tsx`,
`isAvailable: () => true`) already has no language gating, and the `<g>`/`<charDecl>`
infrastructure it builds on is already script-agnostic; the only genuinely
Chinese-palaeography-specific piece is the small plain-symbol palette (`chhivSymbols.ts`)
covered by the separate "Palaeography palette" work, which this document doesn't need to
touch.

# 1. Objective

Implement a system for Chinese palaeographers to insert, identify, construct, edit, reuse, and export characters that cannot conveniently be represented by a normal Unicode codepoint.

The central design principle is:

**Find before compose; compose before rasterize.**

When a scholar encounters an unencoded or unusual graph, the software should make it easy to:

1. search for an existing Unicode/GlyphWiki representation;
    
2. search GlyphWiki structurally from recognizable components;
    
3. adopt an existing GlyphWiki glyph when one exists;
    
4. construct a new glyph from existing components when necessary;
    
5. modify component geometry or individual strokes when necessary;
    
6. fall back to an image-derived SVG for genuinely idiosyncratic manuscript forms.
    

All of these routes should ultimately produce the same kind of reusable **project glyph / gaiji object**, which can be inserted into the XML text using `<g>`.

The scholar should not need to understand KAGE, IDS, SVG, Unicode internals, or GlyphWiki identifiers in order to use the ordinary interface.

---

# 2. Conceptual model

There are four routes into the same system.

### Route A — Existing Unicode character

If the required character exists in Unicode and the ordinary font representation is adequate, use the Unicode character normally.

No gaiji object is necessary.

### Route B — Existing GlyphWiki glyph

If the required form exists in GlyphWiki:

- retrieve/adopt its GlyphWiki identifier;
    
- retain its KAGE source where possible;
    
- obtain or locally render/cache an SVG;
    
- create a local project glyph referring to its external identity.
    

### Route C — Locally composed KAGE glyph

If no satisfactory GlyphWiki glyph exists:

- assemble the graph from existing components;
    
- preserve the component relationships and geometry as KAGE data;
    
- render it locally to SVG;
    
- create a project-local identifier.
    

The composition must remain editable.

### Route D — Image-derived glyph

For palaeographic forms that are too irregular, damaged, uncertain, or laborious to reconstruct:

- accept a cropped character image;
    
- process it through the existing image→SVG pipeline;
    
- create the same type of project glyph object;
    
- optionally add an IDS description, notes, correspondence, or other metadata later.
    

This route may have no KAGE representation.

---

# 3. Important distinction between representations

Do not collapse the following concepts.

## Unicode

Answers:

> What encoded character is this?

A Unicode codepoint may or may not exist.

## IDS

Answers approximately:

> What components/structure does this graph have?

Example:

```text
⿰言某
```

IDS is useful semantic/search metadata.

It is **not the rendering engine**.

## KAGE

Answers:

> How is this glyph geometrically constructed?

KAGE is the primary editable representation for composed glyphs.

It may contain individual strokes and/or references to other KAGE glyph components positioned and transformed within regions.

## SVG

Answers:

> What should Grognard display?

SVG is a rendered representation.

For KAGE glyphs, SVG should be considered a cache/output rather than the authoritative source.

## GlyphWiki ID

Answers:

> Does an externally maintained version of this glyph already exist, and what is it called there?

Preserve this identifier whenever an existing GlyphWiki glyph is adopted.

---

# 4. Unified project glyph model

**Decided:** this registry is project-level, not per-document. Grognard's existing
image→SVG pipeline (`glyphCharDecl.ts`) currently registers each glyph in *that
document's own* `<teiHeader><charDecl>` — fully portable per file, but with no way to
answer "all occurrences of project glyph #17" or "all glyphs containing component X"
across a project's many files (§24), and no way to propagate an edit to every occurrence
without walking every document (§22). Model `ProjectGlyph` storage on the precedent
Grognard already uses for exactly this local-vs-shared tension: the project's
`entities.sqlite` (see `docs/entity-sync-planning.md`, `docs/dual-entity-database-planning.md`).
A project-level glyph table is the source of truth; each document's `<g ref="#id">` plus
its own `<charDecl>` entry is kept in sync as a portable cached copy, so a single
exported/shared file still renders standalone even outside the project.

Create a project-level registry of nonstandard glyphs.

Conceptually:

```python
ProjectGlyph:
    id                  # stable local identifier
    unicode             # optional Unicode codepoint/string
    glyphwiki_id        # optional
    ids                 # optional IDS expression
    kage                # optional KAGE source
    svg                 # rendered/cached SVG
    source_type         # glyphwiki | composed | image | other
    source_image        # optional original/cropped manuscript image
    notes               # optional
```

Do not require every field.

Examples:

An adopted GlyphWiki character might have:

```text
id
glyphwiki_id
ids
kage
svg
source_type = glyphwiki
```

A locally composed character:

```text
id
ids
kage
svg
source_type = composed
```

An image-derived character:

```text
id
svg
source_image
source_type = image
```

Potentially later:

```text
unicode
```

if the character is encoded or identified.

---

# 5. XML representation

Insertion into the transcription should remain simple.

Prefer:

```xml
<g ref="#chhiv-0017"/>
```

The detailed representation belongs in a project glyph registry rather than being repeated at every occurrence.

A TEI-compatible representation could eventually resemble:

```xml
<charDecl>
    <glyph xml:id="chhiv-0017">
        <charName>Project glyph CHHIV-0017</charName>

        <mapping type="unicode">...</mapping>
        <mapping type="ids">⿰言某</mapping>
        <mapping type="glyphwiki">...</mapping>
        <mapping type="kage">...</mapping>

        <graphic url="glyphs/chhiv-0017.svg"/>
    </glyph>
</charDecl>
```

**Decided:** `<glyph>`, not `<char>` — TEI's `<char>` documents an already-encoded Unicode
character and its content model doesn't permit `<graphic>` children; `<glyph>` is the
element meant for exactly this (a non-standard graph, described, with `<graphic>`
children allowed). This also matches what Grognard's existing image→SVG pipeline
already writes (`glyphCharDecl.ts`'s `ensureGlyphCharDeclEntry`).

Do not hard-wire the implementation to this exact XML until compatibility with Grognard's existing document model has been examined.

The important architectural rule is:

**occurrence in text → stable local glyph ID → project glyph record → representations/provenance**

---

# 6. Primary UI: “Insert character”

The scholar should have one coherent entry point.

Something approximately like:

```text
Insert character

[ Search / identify ]
[ Compose from components ]
[ Import from image ]
```

These should not feel like unrelated tools.

They are three ways of answering:

> What graph belongs here?

---

# 7. Find-before-compose workflow

This is the core feature.

When the user begins composing a character from components, do not assume that a new glyph needs to be created.

Search for an existing one first.

Example:

The user specifies:

```text
left:  言
right: component X
```

The application should query its GlyphWiki data/index for glyphs containing those components.

Display plausible candidates visually:

```text
Possible existing glyphs

[ glyph ]  [ glyph ]  [ glyph ]  [ glyph ]

GlyphWiki: foo
GlyphWiki: bar
...
```

The user can:

- choose an existing glyph;
    
- inspect it more closely;
    
- continue composing if none is correct.
    

The human palaeographer makes the final identification.

Do not automatically equate component similarity with character identity.

---

# 8. Progressive search

Searching should ideally happen while the scholar composes.

For example:

```text
Component 1: 言

1432 matching GlyphWiki glyphs

Layout: left/right

318 matches

Component 2: X

7 matches
```

Show candidate thumbnails as soon as the search space becomes useful.

This means the composition UI doubles as a **structural GlyphWiki search interface**.

A scholar may begin intending to construct a graph and discover that the exact form already exists.

---

# 9. GlyphWiki data strategy

Do not make ordinary operation dependent upon the GlyphWiki website being reachable.

Prefer a local searchable dataset.

**Confirmed by direct testing (2026-09-24):**

- GlyphWiki publishes one archive at `https://glyphwiki.org/dump.tar.gz`, regenerated
  daily (`Last-Modified` was the previous day at test time). Compressed size: **~109 MB**
  (114,455,964 bytes). It contains two members: `dump_newest_only.txt` and
  `dump_all_versions.txt` (the latter, with full edit history, was not measured but is
  necessarily larger).
- `dump_newest_only.txt` alone is **~295 MB uncompressed** (309,304,832 bytes, read from
  its tar header), roughly **~2.5 million lines** by sampling (rough estimate from a
  partial download, not an exact count). A large fraction of those are per-user
  `username_label` sandbox/draft entries rather than distinct identified characters
  (e.g. `abyterus_g0000`, `a77uyh_sandbox` in the sample below) — the number of
  *palaeographically meaningful* glyphs is smaller than the raw row count suggests.
- Format is confirmed pipe-delimited `name|related-char|kage-data`, e.g.:
  ```
  abyterus_g0000|u3013|99:0:0:0:0:200:200:u56d7:0:0:0$99:0:0:36:30:167:180:u7389-01:0:0:0$...
  ```
  `kage-data` is `$`-joined stroke/component records; a component reference embeds the
  target as `u<hex>[-variant]` (e.g. `u5927-04`), which is straightforward to parse for
  building the component graph in §10.
- **No documented public JSON/REST search API was found.** GlyphWiki's own wiki pages
  are behind Cloudflare bot protection (scripted requests get HTTP 403) and there is no
  advertised `glyph2svg`/`glyph2ttf`-style endpoint beyond the dump itself. This matches
  what `gwsearch` (below) actually does: it works entirely from the daily dump, offline,
  not against a live service. Conclusion: there is no shortcut around downloading and
  parsing the dump — do the same thing `gwsearch` does rather than looking for an API
  that doesn't exist.
- **Licensing is more permissive than initially assumed.** This is not CC BY-SA: per the
  license text GlyphWiki itself ships (and that Mozilla redistributes verbatim alongside
  glyphs it bundles in Firefox), glyphs registered at GlyphWiki may be freely reused,
  reproduced, and modified, including as the basis for a new font, with **no attribution
  requirement**. The only carve-out is for third-party material quoted *within wiki
  articles* (not the glyph data itself), which keeps its own source license. This
  resolves item 4 from the earlier design discussion: bundling/caching GlyphWiki data
  locally carries materially less licensing overhead than a ShareAlike regime would —
  crediting GlyphWiki in `THIRD_PARTY_NOTICES.md`/About is still good practice, but not
  a legal precondition for redistribution.

**Decision-gate result (2026-09-24, `scripts/extract-glyphwiki-kage-core.mjs` in the
grognard repo, run against the real 2026-09-23 dump):**

The naive "bare `u<hex>`" filter needed one correction once tested against the real
file: the dump's fields are fixed-width and space-padded (` u0000  ...  | u3013   |
99:...`), so both `name` and `kage-data` must be trimmed after splitting on `|` — an
unanchored/untrimmed regex silently matches nothing. Fixed and reverified.

A second, more consequential bug surfaced only by actually attempting dependency
closure: a `99:` record's component-reference field can carry a trailing `@N`
render-parameter suffix glued onto the name with no delimiter (e.g. `u5927-04@2`).
Treating the whole token as the lookup key misses the real component (`u5927-04`,
which usually *is* present) and reports it as unresolved. Stripping `@.*` before
lookup (kage-engine evidently does the same internally at render time) cut unresolved
references by 99.7% (9,720 → 26) — worth calling out because "0 render failures"
alone would not have caught this: kage-engine renders a glyph with a genuinely
missing sub-component silently, by omitting it, not by throwing. Render success
count is not sufficient evidence of correctness on its own; the unresolved-reference
count is the real signal, and it should stay in the standing report the extraction
script emits.

Results:

| Metric | Value |
| --- | --- |
| Seed glyphs (canonical `u<hex>` found in dump) | 139,860 / 139,860 resolved |
| Additional dependency glyphs pulled in | 89,140 |
| Total records in bundle | 229,000 |
| Uncompressed bundle size | 16.13 MB |
| Compressed bundle size | 3.76 MB |
| Unresolved component references | 26 (real gaps in the dump itself — `-jv`/rare `-var` suffixed names with no entry under any name) |
| Rendering failures (all 139,860 seeds rendered via `@kurgm/kage-engine`) | 0 |

Spot-checked one rendered SVG (`u8a00`, 言) by hand — well-formed `<svg>` with real
`<polygon>` stroke geometry, not an empty/placeholder shape.

Seed distribution by block, for context on what's actually in this "canonical"
namespace before deciding whether to narrow it further:

| Range | Count |
| --- | --- |
| ASCII/Latin/control (< U+2E80) | 8,221 |
| CJK Radicals/Kangxi (U+2E80–U+2FDF) | 329 |
| CJK Symbols/Punctuation (U+3000–U+303F) | 80 |
| Hiragana/Katakana (U+3040–U+30FF) | 189 |
| CJK Unified Ideographs + Ext A (U+3400–U+9FFF) | 27,648 |
| CJK Compatibility (U+F900–U+FAFF) | 472 |
| Other BMP | 14,072 |
| Supplementary plane (≥ U+10000, i.e. CJK Ext B and beyond) | 88,849 (63.5%) |

That last row is the encouraging one: nearly two-thirds of the seed set is already in
supplementary-plane territory — exactly the rare/unencoded-adjacent range palaeography
work lives in — without any deliberate curation beyond "canonical bare name." The
~8,221 ASCII/Latin/control entries are very likely placeholder/reference glyphs rather
than useful components; harmless to keep (negligible size) but worth excluding in a
later pass if they turn out to be noise in the composer's component picker.

License confirmed directly from the dump's own bundled `LICENSE.txt` (stronger source
than the Mozilla-redistributed copy cited earlier): "These data files are free
software. Unlimited permission is hereby granted to use, copy, and distribute these
files, with or without modification, either commercially or non-commercially. THIS
DATA IS PROVIDED 'AS IS' WITHOUT ANY WARRANTY." (Copyright 2009 GlyphWiki Project.)
No ShareAlike, no attribution requirement.

Investigate GlyphWiki's available dumps and the existing `gwsearch` component-search project.

**Confirmed:** [`kurgm/gwsearch`](https://github.com/kurgm/gwsearch) is a real, current,
inspectable project (JavaScript, GPL-2.0), built exactly on this same daily dump, using
a directed-acyclic-graph structure over glyph citation/component/IDS relationships to
answer "which glyphs contain this component" queries offline. This is the reference
implementation for §10's component graph — read its source before designing a new one.

Build/update a local index from GlyphWiki data.

At minimum index:

```text
glyph
    glyphwiki_id
    kage_data

component_reference
    parent_glyph
    component_glyph
    geometry/placement where available
```

Also consider storing:

```text
unicode mapping
IDS
aliases
related glyphs
cached SVG
```

where available.

SQLite is probably sufficient unless the existing Grognard architecture suggests another storage layer.

---

# 10. Component graph

Component search must support nested components.

Suppose:

```text
Glyph A
  contains Component B
      contains Component C
```

A search for C should be capable of finding A.

Therefore model GlyphWiki component relationships as a graph rather than only flat direct references.

Study the approach used by `gwsearch`.

Avoid reinventing this algorithm unnecessarily.

---

# 11. Geometric information

KAGE component references contain useful placement information.

Preserve it.

However, do **not** initially attempt to implement arbitrary geometric similarity search such as:

> Find every GlyphWiki character whose 言 component occupies x=0–82 and whose second component occupies x=76–200.

For the first implementation:

1. identify component relationships;
    
2. optionally constrain by broad layout;
    
3. show candidate glyphs;
    
4. let the scholar visually identify the correct form.
    

Human verification is desirable here.

Later geometric ranking can be added if testing demonstrates that it is useful.

---

# 12. Composer UI

When no existing glyph is satisfactory, allow the scholar to construct one.

The simplest interface should begin with familiar ideographic layouts:

```text
⿰  left/right
⿱  above/below
⿲  three-part horizontal
⿳  three-part vertical
⿴  enclosure
⿵
⿶
⿷
⿸
⿹
⿺
⿻  overlap
```

The user chooses a structure and places components into its slots.

For example:

```text
┌────────────────────────┐
│            │           │
│     言     │     X     │
│            │           │
└────────────────────────┘
```

Initial placement can be automatic.

---

# 13. Component selection

A component slot should accept, where feasible:

- a Unicode character;
    
- a GlyphWiki glyph;
    
- another project glyph;
    
- a recognized component;
    
- eventually perhaps an IDS expression.
    

Searching for a component should show visual results rather than requiring knowledge of GlyphWiki naming conventions.

---

# 14. Geometry editing

Automatic component placement will often be insufficient for palaeographic material.

Provide direct manipulation.

At minimum:

- move;
    
- horizontal scale;
    
- vertical scale;
    
- resize;
    
- adjust boundary/divider between components.
    

For example:

```text
┌────────────────────────┐
│        │               │
│   言   │       X       │
│        │               │
└────────────────────────┘
         ↑
      draggable
```

The underlying KAGE component placement should update accordingly.

---

# 15. Advanced editing: explode component

Provide an advanced operation such as:

**Edit strokes**

or internally:

**Explode component**

A component reference can then become editable constituent strokes/components.

The advanced user should be able to:

- select strokes;
    
- move control points;
    
- alter stroke geometry;
    
- delete strokes;
    
- duplicate strokes;
    
- add strokes;
    
- alter relevant KAGE stroke/end parameters.
    

This does not need to be exposed in the first MVP if it substantially increases implementation complexity.

Architect the data model so it can be added without redesigning the entire composer.

---

# 16. KAGE rendering

**Decided:** use [`@kurgm/kage-engine`](https://www.npmjs.com/package/@kurgm/kage-engine)
(npm, JavaScript/TypeScript) — this is the actual engine GlyphWiki's own web editor
runs client-side, maintained by a current GlyphWiki contributor, so it's the same
rendering behaviour a scholar would see on the GlyphWiki site itself. All of the
Python framing below (and in §32) was aspirational pseudocode, not a real option:
Grognard is Electron/TypeScript end to end, and the KAGE ecosystem's canonical
implementation is JS anyway, so there's no cross-language boundary to design around.

License note: `kage-engine` is GPL-3.0. Combining GPL-3.0 code into an AGPL-3.0-only
program is permitted — both licenses carry the compatibility clause (§13 of each)
added specifically to allow this combination — but it should still be logged in
`THIRD_PARTY_NOTICES.md` like the project's other bundled components.

The application needs the ability to take KAGE data and produce SVG.

Desired conceptual API:

```ts
const svg = renderKage(kageData);
```

Rendering should be isolated behind an adapter so that the underlying KAGE library can later be replaced.

For example:

```ts
interface GlyphRenderer {
  renderKage(kageData: string): string;
}
```

Do not let the rest of CHHIV depend directly on the implementation details of one third-party library.

---

# 17. SVG caching

Rendered SVG should be cached.

Example:

```text
project/
    glyphs/
        chhiv-0017.svg
        chhiv-0018.svg
```

If KAGE source changes:

```text
KAGE modified
    ↓
invalidate SVG
    ↓
render new SVG
    ↓
refresh document display
```

The SVG should not be the authoritative editable representation when KAGE data exists.

---

# 18. Adopting a GlyphWiki glyph

When the scholar chooses an existing GlyphWiki candidate:

1. create a stable project-local glyph ID;
    
2. preserve the GlyphWiki ID;
    
3. preserve/import KAGE data if permitted and available;
    
4. preserve IDS/other structural metadata if available;
    
5. obtain or render SVG;
    
6. cache everything necessary for offline operation.
    

The document should reference the **local ID**, not depend directly on GlyphWiki.

Example:

```xml
<g ref="#chhiv-0042"/>
```

rather than embedding a remote GlyphWiki URL at every occurrence.

This protects the transcription against external changes and loss of connectivity.

---

# 19. Provenance

Do not silently erase where a glyph came from.

The system should distinguish:

```text
Unicode
GlyphWiki
locally composed
image-derived
```

For externally sourced glyphs, retain the external identifier and possibly retrieval/version information.

For locally modified GlyphWiki glyphs, distinguish:

```text
source = GlyphWiki foo
modified locally = true
```

The modified object should not falsely present itself as identical to the original GlyphWiki glyph.

---

# 20. Image-derived fallback

Integrate the existing CHHIV image→SVG mechanism into this architecture.

Current conceptual pipeline:

```text
drop character image
    ↓
brightness/contrast processing
    ↓
crop
    ↓
transparent/vector representation
    ↓
SVG
```

Instead of treating the result as merely an inline picture, register it as:

```text
ProjectGlyph
```

and insert:

```xml
<g ref="#chhiv-0051"/>
```

The image-derived glyph can later acquire:

- IDS;
    
- Unicode correspondence;
    
- GlyphWiki correspondence;
    
- KAGE reconstruction;
    
- notes.
    

Thus a scholar can work immediately without having to solve the character's identity first.

---

# 21. Conversion between representations

Do not assume that every representation can automatically convert losslessly into every other representation.

In particular:

```text
IDS → KAGE
```

may allow useful initial composition but is not guaranteed to determine exact glyph geometry.

Similarly:

```text
image → KAGE
```

should not be assumed.

Think instead in terms of progressively enriched records.

Example:

```text
DAY 1

image
↓
ProjectGlyph #17
```

Later:

```text
image
IDS
↓
ProjectGlyph #17
```

Later:

```text
image
IDS
GlyphWiki ID
KAGE
SVG
↓
ProjectGlyph #17
```

The ID remains stable throughout.

---

# 22. Editing existing project glyphs

A project glyph must be editable after insertion.

Suggested interaction:

```text
right-click / double-click glyph
    ↓
Edit project character
```

Show:

- rendered form;
    
- local ID;
    
- Unicode correspondence if any;
    
- GlyphWiki correspondence if any;
    
- IDS;
    
- source;
    
- composition editor where applicable;
    
- notes.
    

Changes should propagate to every occurrence referencing that glyph.

---

# 23. Duplicate detection

When creating a new project glyph, check whether the project already contains an equivalent or related object.

At minimum detect:

- same GlyphWiki ID;
    
- same Unicode mapping;
    
- identical KAGE data;
    
- perhaps identical IDS.
    

Do not automatically merge merely because IDS is identical: palaeographically distinct forms can share the same structural description.

Offer:

> This project already contains a related glyph.

and let the scholar decide.

---

# 24. Search within the project

The project glyph registry should eventually support queries such as:

- all non-Unicode glyphs;
    
- all image-derived glyphs;
    
- all GlyphWiki-derived glyphs;
    
- all glyphs containing component X;
    
- all glyphs with IDS matching a pattern;
    
- all occurrences of project glyph #17;
    
- all unresolved glyphs.
    

This turns the gaiji system into useful research data rather than merely a workaround for Unicode.

---

# 25. Offline-first principle

Once imported into a project, a glyph must continue working without internet access.

Never require a remote request simply to render an existing transcription.

Store locally whatever is required for stable reproduction.

Online GlyphWiki access should enhance discovery/update, not be necessary for document integrity.

---

# 26. Updating GlyphWiki data

Implement GlyphWiki data as an independently updateable resource.

Conceptually:

```text
CHHIV
  ↓
GlyphWiki service/index adapter
  ↓
local GlyphWiki database
  ↓
periodic dump update
```

Possible command/UI:

```text
Update GlyphWiki data
Last updated: YYYY-MM-DD
```

Do not silently overwrite project glyphs merely because GlyphWiki upstream changes.

Project data and reference-data updates must remain separate.

---

# 27. Architecture

Keep external systems behind explicit adapters.

Suggested boundaries:

```python
GlyphRepository
ProjectGlyphRepository
GlyphWikiIndex
GlyphWikiImporter
KageRenderer
GlyphSearchService
GlyphCompositionService
SvgCache
```

For example:

```python
class GlyphWikiIndex:
    def find_by_components(self, components, layout=None):
        ...

    def get_glyph(self, glyphwiki_id):
        ...
```

and:

```python
class KageRenderer:
    def render(self, kage_data):
        ...
```

This prevents UI code from becoming entangled with GlyphWiki/KAGE internals.

---

# 28. Candidate ranking

For the initial version, keep ranking conservative.

Useful evidence may include:

1. contains all requested components;
    
2. matches specified broad layout;
    
3. direct component references rather than deeply nested coincidences;
    
4. exact component identities;
    
5. possibly geometric similarity later.
    

Do not pretend the highest-ranked result is necessarily the correct palaeographic identification.

Present it as a candidate.

---

# 29. Suggested MVP

Do not implement the entire system at once.

## Phase 1 — Infrastructure

Implement:

- `ProjectGlyph` model;
    
- stable local identifiers;
    
- glyph registry;
    
- `<g ref>` insertion/rendering;
    
- SVG caching;
    
- support existing image-derived SVG glyphs.
    

Goal:

**All nonstandard characters become first-class project objects.**

**Status (2026-09-24): done, adjusted for the "smallest vertical slice" scope decision.**
Landed in `grognard`:

- `utilities/projectGlyphRegistry.ts` — pure `ProjectGlyph` model + registry
  operations (id allocation, lookup, component map), unit tested.
- `utilities/projectGlyphStore.ts` — project-level persistence
  (`<projectRoot>/project-glyphs.json`, cached SVGs under
  `<projectRoot>/_glyphs/`) via the existing `window.electronAPI`
  read/write-file bridge, plus the compose→render→validate→save→insert
  orchestration (`composeAndInsertProjectGlyph`). Rejects a save outright if
  any component is unresolved, rather than persisting a silently-incomplete
  glyph.
- `utilities/kageCompose.ts` — pure construction of a composed glyph's own
  KAGE data from two component names + an IDS operator (⿰⿱⿴⿸⿹⿺⿻), with a
  fixed default bounding box per operator. No manual drag/scale geometry
  editing in this pass (explicitly deferred, per §14).
- `utilities/kageRenderer.ts` — adapter around `@kurgm/kage-engine`, loading
  the bundled `resources/glyphwiki/kageCore.json` (the extraction script's
  validated output, §9) plus any already-composed project glyphs as
  recursive components; surfaces `unresolvedComponents` explicitly rather
  than trusting "no render exception" as proof of correctness (the lesson
  from the extraction decision gate).
- `glyphCharDecl.ts` extended with an optional `mappings` field
  (`<mapping type="ids">`/`<mapping type="kage">`), and `glyphEditor.ts`'s
  `insertGlyph` threads it through - so a composed glyph's `<g ref="#id">`
  insertion also writes a document-local `<charDecl><glyph>` cache entry
  carrying its IDS/KAGE data, same mechanism as an image-derived glyph.
- `dialogs/composeCharacter/ComposeCharacterDialog.tsx` — the composer UI:
  operator picker, two free-text component fields (a typed/pasted Unicode
  character, or an existing project glyph id), live SVG preview, save. Wired
  into the existing CHHIV toolbar as "Compose character…".
- `@kurgm/kage-engine` added as a real dependency of `cwrc-leafwriter`
  (GPL-3.0, logged in `THIRD_PARTY_NOTICES.md`).

Deliberately not done (per the agreed scope): GlyphWiki search/adoption UI,
component/DAG search, manual drag/scale geometry editing, stroke-level
editing, geometric similarity, live GlyphWiki integration, image-compositing
fallback (Option B was never needed - genuine KAGE composition held up).

## Phase 2 — GlyphWiki lookup

Implement:

- download/import GlyphWiki data;
    
- local SQLite index;
    
- retrieve glyph by GlyphWiki ID;
    
- component graph;
    
- search by components;
    
- candidate thumbnails;
    
- adopt GlyphWiki glyph into project.
    

Goal:

**Find before compose.**

**Status (2026-09-24): done, scoped narrower than originally described here -
direct containment, not the general SQLite/component-graph search.** After
Phase 1 shipped, this was deliberately rescoped down to the smallest slice
that still delivers "find before compose": not a general SQLite index +
nested component-graph search (`gwsearch`'s own territory, still deferred),
but a **direct-containment lookup** answering exactly what the composer ever
asks - "does some GlyphWiki entry combine these two specific components as
its two direct parts?" - restricted to compounds whose both components are
already in the bundled `kageCore.json`, so every candidate is guaranteed
renderable offline with data already shipped.

Landed in `grognard`:

- `scripts/build-glyphwiki-compound-index.mjs` - parses the full dump,
  keeps only entries with exactly two "99:" component records where both
  components are already known, writes `glyphwikiCompoundIndex.json` as
  compact `[name, kageData, componentA, componentB]` tuples (object keys
  would have cost ~30% more for no benefit at 280k+ entries).
- Real numbers from the 2026-09-23 dump: 467,216 total two-component
  entries in the full dump; **282,518** have both components in
  `kageCore.json`; bundle size **29.07 MB uncompressed / 5.31 MB
  compressed**; 224,075 distinct component pairs, 43,396 of them with more
  than one candidate.
- `utilities/glyphwikiIndex.ts` - loads the bundle, builds an in-memory
  unordered-pair index once, `findGlyphwikiCandidates(a, b)`.
- `utilities/kageCompose.ts`'s `guessOperatorFromKageData` - a best-effort
  IDS-operator label for an adopted candidate's real (not composer-default)
  geometry; informational only, doesn't affect rendering.
- `utilities/projectGlyphStore.ts` - `previewComposition` now also returns
  `glyphwikiCandidates`; `persistAndInsertProjectGlyph` factored out as a
  shared tail so `composeAndInsertProjectGlyph` and the new
  `adoptGlyphwikiCandidateAndInsert` don't duplicate the
  save-SVG/registry/insert plumbing. Adopting keeps the source entry's name
  as `glyphwikiId` (provenance, per §19 - never presents an adopted glyph as
  a purely local composition).
- `ProjectGlyph.sourceType` gained `'glyphwiki'`.
- Composer UI: below the compose preview, a row of candidate thumbnails
  ("GlyphWiki already has N matching glyphs") appears whenever the two
  typed components have any - independent of the currently-selected
  operator, since GlyphWiki's real geometry for a pair may not match the
  composer's own default box formula for whichever operator happens to be
  selected. Clicking one adopts it instead of composing fresh.
- Spot-checked against real (non-synthetic) bundled data, not just the
  composer's own generated compositions: `u23e8` (a real GlyphWiki entry
  combining "1" and "0") renders correctly through `@kurgm/kage-engine`
  using only the bundled files - confirms the pipeline works on genuine
  "found via search" geometry, not only entries this codebase's own
  composer produced.

Deliberately not done: the general SQLite index, nested/recursive component
search (`gwsearch`'s actual algorithm), sandbox/variant filtering beyond
what building the KAGE core already required, and any live GlyphWiki
network access - all still Phase-2-proper territory, left for if/when
direct-containment search turns out not to be enough.

## Phase 3 — Basic KAGE composer

Implement:

- basic IDS-like layouts;
    
- component selection;
    
- automatic placement;
    
- drag/scale components;
    
- KAGE generation;
    
- local SVG rendering;
    
- save as ProjectGlyph.
    

Goal:

**Compose when not found.**

## Phase 4 — Progressive search

Connect composition state to GlyphWiki search.

As components/layout are specified, dynamically update candidate existing glyphs.

Goal:

**Searching and composing become one workflow.**

## Phase 5 — Advanced KAGE editing

Implement:

- explode component;
    
- stroke selection;
    
- control-point editing;
    
- stroke addition/deletion;
    
- advanced KAGE parameters.
    

Goal:

**Permit genuinely new palaeographic forms to be reconstructed accurately.**

## Phase 6 — Scholarly enrichment

Add:

- IDS editing;
    
- notes;
    
- correspondences;
    
- provenance display;
    
- unresolved/identified status;
    
- project-wide component search;
    
- TEI `<charDecl>` import/export.
    

---

# 30. UX principle

The ordinary palaeographer should experience this:

> I can't type this character.

Then:

```text
Insert missing character
```

She recognizes two components.

She selects them.

CHHIV says:

```text
We found 6 possible existing characters.
```

She sees thumbnails.

If one is correct:

```text
click
```

Done.

If none is correct:

```text
Continue composing
```

CHHIV gives her the components already arranged.

She adjusts one slightly.

```text
Save
```

Done.

If the graph is too strange:

```text
Import image
```

Done.

Everything underneath—GlyphWiki, KAGE, IDS, SVG, XML `<g>`, local identifiers, caching, provenance—is implementation machinery.

---

# 31. Core principle for development decisions

Whenever choosing between technical elegance and scholarly workflow, preserve this invariant:

**The scholar must be able to record what she sees even when she does not yet know what it is.**

Identification, Unicode mapping, IDS analysis, GlyphWiki correspondence, and KAGE reconstruction can all happen later.

Never make successful identification a prerequisite for transcription.

At the same time, never throw away structure once the scholar supplies it.

Therefore:

**unknown image → reusable glyph**

**known components → structured reusable glyph**

**known GlyphWiki form → externally identified reusable glyph**

**known Unicode character → normal encoded text**

These are points on a continuum of knowledge, not four unrelated features.

---

# 32. Initial investigation before coding

Before modifying the application, inspect:

1. the current Grognard plugin architecture;
    
2. the existing CHHIV image→SVG implementation;
    
3. current handling of `<g>`, SVG, inline images, and project resources;
    
4. persistence/database mechanisms already used by Grognard;
    
5. ~~GlyphWiki's current dump format and licensing~~ — **done, see §9**: pipe-delimited
   dump, ~109 MB compressed / ~295 MB uncompressed for `dump_newest_only.txt` alone,
   freely reusable with no attribution requirement;
    
6. ~~`gwsearch` and its component-indexing strategy~~ — **done, see §9**: real, current,
   JS, GPL-2.0, DAG over the same dump, offline;
    
7. ~~available maintained KAGE renderers~~ — **done, see §16**: `@kurgm/kage-engine`
   (npm, JS/TS, GPL-3.0) — the Python framing in the original brief doesn't apply, wrong
   stack;
    
8. ~~GlyphWiki/KAGE licensing implications~~ — **done**: GlyphWiki data itself is
   attribution-free to reuse/modify (§9); `kage-engine` is GPL-3.0, combinable with
   Grognard's AGPL-3.0-only license under each license's §13 compatibility clause, log it
   in `THIRD_PARTY_NOTICES.md`;
    
9. ~~whether GlyphWiki provides useful live endpoints in addition to dumps~~ — **done,
   see §9**: no documented public API found, wiki pages are behind Cloudflare bot
   protection for scripted access, the dump is the only integration path (which is what
   `gwsearch` itself relies on too);
    
10. how project-local resources are currently packaged/exported.
    

Do not begin by building a second parallel persistence or rendering architecture if Grognard already has suitable abstractions.

---

# 33. First deliverable

Do **not** immediately implement everything above.

First inspect the existing codebase and produce a technical proposal containing:

- relevant existing Grognard/CHHIV classes and files;
    
- proposed `ProjectGlyph` schema;
    
- proposed XML representation;
    
- proposed local GlyphWiki database schema;
    
- proposed KAGE renderer/library;
    
- GlyphWiki data acquisition strategy;
    
- UI integration points;
    
- dependency/licensing concerns;
    
- migration implications;
    
- phased implementation plan;
    
- tests required for Phase 1 and Phase 2.
    

Identify any assumptions in this brief that conflict with the existing codebase.

After that proposal has been reviewed, implement Phase 1 first.

The intended final architecture is:

```text
                    ┌── Unicode ───────────────→ ordinary text
                    │
Scholar sees graph ─┼── recognizable parts
                    │       ↓
                    │   GlyphWiki search
                    │      ↙       ↘
                    │   found     not found
                    │     ↓           ↓
                    │   adopt       KAGE compose
                    │     ↓           ↓
                    │     └────┬──────┘
                    │          ↓
                    │    ProjectGlyph
                    │          ↓
                    │      <g ref="…"/>
                    │
                    └── image ─→ SVG ─→ ProjectGlyph
```

The result should not merely be a mechanism for displaying characters Unicode lacks. It should be a **scholarly gaiji system in which uncertain observations can progressively become identified, structured, editable, searchable character data.**