/**
 * CBETA import plugin entry. UI lives in the Grognard host webpack bundle
 * (packages/cwrc-leafwriter/src/plugins/hostModules/cbetaImportUi.ts — TODO).
 */

/** @typedef {import('@grognard/plugin-sdk/register-context').PluginRegisterContext} PluginRegisterContext */

const HOST_UI_MODULE = 'cbeta-import-ui';

/**
 * @param {PluginRegisterContext} context
 */
export async function register(context) {
  context.log('loading CBETA import UI from host');
  const ui = await context.loadHostModule(HOST_UI_MODULE);
  if (typeof ui.registerCbetaImportUi !== 'function') {
    throw new Error(`${HOST_UI_MODULE} is missing registerCbetaImportUi`);
  }
  ui.registerCbetaImportUi(context);
}
