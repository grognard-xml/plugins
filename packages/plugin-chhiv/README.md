# CHHIV (`chhiv`)

**C**haracter **H**andling for **H**istorical **I**nscription **V**ariants — palaeography tools for transcribing Chinese manuscripts and inscriptions. Chinese only.

## Features

1. **Symbol palette** — a CHHIV toolbar menu (like the Norbert menu) listing the palaeography symbols and bracket conventions from `plugins/paleo-clever-idea.md`. Clicking a plain symbol inserts it at the cursor; clicking a bracket pair wraps the current selection (or inserts both halves with the cursor left between them, if nothing is selected). No semantic tagging - plain text only.

More features to follow.

## Build

```bash
cd plugins
npm install
npm run build -w @grognard/plugin-chhiv
```

`dist/register.mjs` is a thin entry that loads UI from the Grognard host via `loadHostModule('chhiv-symbol-palette-ui')` - same pattern as `plugin-norbert` and `plugin-cjk-dates`.

## Development with Grognard desktop

1. Build the plugin (`npm run build -w @grognard/plugin-chhiv`)
2. Start Grognard: `npm run dev:desktop` from `grognard`
3. Enable **CHHIV** in Tools → Plugins (not enabled by default; stays enabled until turned off)

## Architecture

| Layer | Location |
|-------|----------|
| Plugin manifest | This package |
| Thin `dist/register.mjs` | This package (esbuild) |
| Symbol palette UI | Grognard host module `plugins/hostModules/chhivSymbolPaletteUi.ts` |
| Generic plugin host | `grognard` — extension registry, Tools → Plugins enable/disable |
