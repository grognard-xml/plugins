/**
 * CHHIV (Character Handling for Historical Inscription Variants) plugin entry.
 *
 * UI is loaded from the Grognard host (webpack bundle) via loadHostModule so
 * this plugin package stays small and does not duplicate React/MUI
 * dependencies - same pattern as plugin-norbert and plugin-cjk-dates.
 */

/** @typedef {import('@grognard/plugin-sdk/register-context').PluginRegisterContext} PluginRegisterContext */

const HOST_UI_MODULE = 'chhiv-symbol-palette-ui';

/**
 * @param {PluginRegisterContext} context
 */
export async function register(context) {
  context.log('loading CHHIV symbol palette UI from host');
  const ui = await context.loadHostModule(HOST_UI_MODULE);
  if (typeof ui.registerChhivSymbolPaletteUi !== 'function') {
    throw new Error(`${HOST_UI_MODULE} is missing registerChhivSymbolPaletteUi`);
  }
  ui.registerChhivSymbolPaletteUi(context);
}
