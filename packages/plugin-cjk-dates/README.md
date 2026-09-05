# East Asian dates (`cjk-dates`)

Premodern date tagging and disambiguation for China, Japan, and Korea using [Sanmiao](https://pypi.org/project/sanmiao/).

## Build

```bash
cd plugins
npm install
npm run build:cjk-dates
npm run smoke:cjk-dates
```

`dist/register.mjs` is a thin entry (~400 bytes) that loads UI from the Grognard host via `loadHostModule('cjk-dates-ui')`.

## Python runtime

```bash
npm run python:download -w @grognard/plugin-cjk-dates
```

## Development with Grognard desktop

1. Build the plugin (`npm run build:cjk-dates`)
2. Start Grognard: `npm run dev:desktop` from `grognard`
3. Enable **East Asian dates** in Tools → Plugins

On first dev launch with no plugins installed, Grognard seeds this package from `plugins/packages/` and auto-enables it.

## Smoke test

```bash
npm run smoke:cjk-dates
```

Checks manifest validation, `register()` wiring, host UI module, python script presence, and bundle size — no Electron required.

## Architecture

| Layer | Location |
|-------|----------|
| Plugin manifest + Python runtime | This package |
| Thin `dist/register.mjs` | This package (esbuild) |
| Calendar UI + curator panels | Grognard host module `plugins/hostModules/cjkDatesUi.ts` |
| Generic plugin host | `grognard` — `plugins:invokePython`, extension registry |
| TEI schema merge | Desktop main process (gated on plugin enable) |
