import surnamesData from '../data/surnames.json';
import geoAdminSuffixes from '../data/geo-admin-suffixes.json';

/** @typedef {import('@grognard/plugin-sdk/register-context').PluginRegisterContext} PluginRegisterContext */

const PRINCELY_RANKS = new Set(['王', '公', '侯', '伯', '子', '男']);

/**
 * Generates rank+surname wrapper candidates (e.g. 王恢, "Prince [surname]")
 * for princely titles abbreviated to just a surname in the source text —
 * the pattern the closed wiki-nt-links pack can't cover, since it only lists
 * titles already linked to a specific Wikipedia/Wikidata person. Confidence
 * is left to the reviewer: these are cert="unknown" wrapper suggestions like
 * any other, not asserted identifications.
 */
export function buildNobleTitlePatternCandidates() {
  const ranks = (geoAdminSuffixes.suffixes ?? [])
    .map((entry) => entry.string)
    .filter((string) => PRINCELY_RANKS.has(string));
  const surnames = surnamesData.surnames ?? [];

  const candidates = [];
  for (const rank of ranks) {
    for (const surname of surnames) {
      const id = `pattern:${rank}:${surname}`;
      candidates.push({
        source: 'norbert-pattern',
        authorityId: id,
        kind: 'person',
        primaryName: surname,
        searchStrings: [`${rank}${surname}`],
        metadata: {
          wrapper: {
            personId: id,
            titleRowId: id,
            components: { roleName: rank, persName: surname },
          },
        },
      });
    }
  }
  return candidates;
}

/**
 * @param {PluginRegisterContext} context
 */
export function registerNobleTitlePatternProducer(context) {
  context.registerPatternTagProducer?.(buildNobleTitlePatternCandidates);
}
