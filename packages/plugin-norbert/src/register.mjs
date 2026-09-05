import surnamesData from '../data/surnames.json';
import { romanizeSplitParts, segmentPersonName } from './segmentPersonName.mjs';
import { inferConcatenatedOfficeRelation } from './officeRelations.mjs';
import { extractNorbertEntityData } from './entityDataExtractor.mjs';
import { registerNobleTitlePatternProducer } from './nobleTitlePatternProducer.mjs';

/** @typedef {import('@grognard/plugin-sdk/register-context').PluginRegisterContext} PluginRegisterContext */

const HOST_NOBLE_TITLE_UI_MODULE = 'norbert-noble-title-ui';

/**
 * @param {PluginRegisterContext} context
 */
export async function register(context) {
  const surnames = surnamesData.surnames ?? [];
  context.registerPersonNameSegmenter(({ name, romanize }) => {
    const split = segmentPersonName(name, surnames);
    if (!split) return null;
    return {
      ...split,
      romanizedName: romanizeSplitParts(split, romanize, name),
    };
  });
  context.registerOfficeRelationExtractor?.(inferConcatenatedOfficeRelation);
  context.registerEntityDataExtractor?.(extractNorbertEntityData);
  registerNobleTitlePatternProducer(context);
  context.log(`person-name segmenter ready (${surnames.length} surnames)`);

  // Toolbar/dialog UI is loaded from the Grognard host (webpack bundle) via
  // loadHostModule, same as plugin-cjk-dates, so this package stays small
  // and does not duplicate React/MUI.
  const ui = await context.loadHostModule(HOST_NOBLE_TITLE_UI_MODULE);
  if (typeof ui.registerNorbertNobleTitleUi !== 'function') {
    throw new Error(`${HOST_NOBLE_TITLE_UI_MODULE} is missing registerNorbertNobleTitleUi`);
  }
  ui.registerNorbertNobleTitleUi(context);
}
