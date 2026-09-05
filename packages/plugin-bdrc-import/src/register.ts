/**
 * BDRC import plugin entry. UI + fetch/emit pipeline live in the Grognard host bundle;
 * this package only carries the manifest and this stub.
 *
 * Design: leaf-writer/docs/bdrc-import-planning.md
 */

/** @typedef {import('@grognard/plugin-sdk/register-context').PluginRegisterContext} PluginRegisterContext */

const HOST_UI_MODULE = 'bdrc-import-ui';

/**
 * @param {PluginRegisterContext} context
 */
export async function register(context) {
  context.log('loading BDRC import UI from host');
  const ui = await context.loadHostModule(HOST_UI_MODULE);
  if (typeof ui.registerBdrcImportUi !== 'function') {
    throw new Error(`${HOST_UI_MODULE} is missing registerBdrcImportUi`);
  }
  ui.registerBdrcImportUi(context);
}
