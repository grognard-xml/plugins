/**
 * East Asian dates plugin entry.
 *
 * UI is loaded from the Grognard host (webpack bundle) via loadHostModule so the plugin
 * package stays small and does not duplicate React/MUI dependencies.
 */

/** @typedef {import('@grognard/plugin-sdk/register-context').PluginRegisterContext} PluginRegisterContext */

const HOST_UI_MODULE = 'cjk-dates-ui';

/**
 * @param {PluginRegisterContext} context
 */
export async function register(context) {
  context.log('loading East Asian dates UI from host');
  const ui = await context.loadHostModule(HOST_UI_MODULE);
  if (typeof ui.registerCjkDatesUi !== 'function') {
    throw new Error(`${HOST_UI_MODULE} is missing registerCjkDatesUi`);
  }
  ui.registerCjkDatesUi(context);
}
