import {
  buildApplyPlan,
  effectiveFief,
  effectivePn,
  mergeCorrections,
  resolveApplyAction,
} from './applyWikiReview.mjs';

export { mergeCorrections, resolveApplyAction, buildApplyPlan };

/**
 * @param {{ dyn?: string|null, fief?: string|null, pn?: string|null, pnAbr?: string|null, nt?: string|null, person?: string|null }} parts
 */
export function buildNtSearchStrings(parts) {
  const { dyn, fief, pn, pnAbr, nt, person } = parts;
  /** @type {string[]} */
  const strings = [];
  const add = (s) => {
    if (s && !strings.includes(s)) strings.push(s);
  };

  if (fief && pn && nt) add(`${fief}${pn}${nt}`);
  if (fief && nt) add(`${fief}${nt}`);
  if (fief && pn && nt && person) add(`${fief}${pn}${nt}${person}`);
  if (fief && nt && person) add(`${fief}${nt}${person}`);
  if (!fief && pn && nt) add(`${pn}${nt}`);
  if (!fief && pn && nt && person) add(`${pn}${nt}${person}`);
  if (fief && pnAbr && nt) add(`${fief}${pnAbr}${nt}`);
  if (fief && pnAbr && nt && person) add(`${fief}${pnAbr}${nt}${person}`);
  if (!fief && pnAbr && nt) add(`${pnAbr}${nt}`);
  if (!fief && pnAbr && nt && person) add(`${pnAbr}${nt}${person}`);
  // Skip the dyn-prefixed variants when dyn === fief (e.g. Liu Bei's 漢昭烈帝,
  // where Norbert records both dyn and fief as "漢") — they'd otherwise
  // duplicate into a garbled "漢漢昭烈帝".
  if (dyn && fief && dyn !== fief && pn && nt) add(`${dyn}${fief}${pn}${nt}`);
  if (dyn && fief && dyn !== fief && pn && nt && person) add(`${dyn}${fief}${pn}${nt}${person}`);
  if (dyn && !fief && pn && nt) add(`${dyn}${pn}${nt}`);
  if (dyn && !fief && pn && nt && person) add(`${dyn}${pn}${nt}${person}`);
  if (dyn && fief && dyn !== fief && pnAbr && nt) add(`${dyn}${fief}${pnAbr}${nt}`);
  if (dyn && fief && dyn !== fief && pnAbr && nt && person) add(`${dyn}${fief}${pnAbr}${nt}${person}`);
  if (dyn && !fief && pnAbr && nt) add(`${dyn}${pnAbr}${nt}`);
  if (dyn && !fief && pnAbr && nt && person) add(`${dyn}${pnAbr}${nt}${person}`);

  return strings;
}

/**
 * @param {{ dyn?: string|null, fief?: string|null, pn?: string|null, nt?: string|null, person?: string|null }} parts
 */
export function buildMatchKey(parts) {
  return [parts.dyn ?? '', parts.fief ?? '', parts.pn ?? '', parts.nt ?? '', parts.person ?? ''].join('|');
}

/**
 * @param {ReturnType<buildApplyPlan>} plan
 * @param {Record<string, unknown>} row
 * @param {number} index
 */
export function planToAssetRecord(plan, row, index) {
  if (plan.action === 'skip') return null;

  const action = plan.action === 'link_title' ? 'title_only' : plan.action;
  const wiki = {
    sourcePage: plan.sourcePage,
    sourcePageId: plan.sourcePageId ?? null,
    sourcePageUrl: row.sourcePageUrl ?? null,
    sourceWikidataId: plan.sourceWikidataId ?? null,
    dynastySection: row.dynastySection ?? row.wiki_dynastySection ?? null,
    dyn: plan.dyn,
    fief: plan.fief,
    pn: plan.pn,
    nt: plan.nt,
    person: plan.personBare,
    startYear: plan.startYear ?? null,
    endYear: plan.endYear ?? null,
    wikidataId: plan.wikidataId ?? null,
    wikiPersonUrl: plan.wikiPersonUrl ?? null,
  };

  const norbertPersonId = plan.personId ? String(plan.personId) : null;
  const norbertNtInd = plan.ntInd ? String(plan.ntInd) : null;
  const canName = row.norbert?.can_name ?? row.norbert_can_name ?? plan.personBare ?? null;

  /** @type {Record<string, unknown>|null} */
  let norbert = null;
  if (norbertPersonId || norbertNtInd) {
    norbert = {
      personId: norbertPersonId,
      ntInd: norbertNtInd,
      canName,
      dyn: row.norbert?.dyn ?? row.norbert_dyn ?? plan.dyn ?? null,
      fief: row.norbert?.fief ?? row.norbert_fief ?? null,
      pn: row.norbert?.pn ?? row.norbert_pn ?? null,
      nt: row.norbert?.nt ?? row.norbert_nt ?? null,
      dynId: row.norbert?.dyn_id ?? row.norbert_dyn_id ?? plan.dynId ?? null,
      startYear: row.norbert?.start_year ?? row.norbert_start_year ?? null,
      endYear: row.norbert?.end_year ?? row.norbert_end_year ?? null,
    };
  }

  /** @type {Record<string, unknown>|null} */
  let proposedNt = null;
  if (action === 'insert_nt' || action === 'update_nt') {
    proposedNt = {
      dyn: plan.dyn,
      fief: plan.fief,
      pn: plan.pn,
      nt: plan.nt,
      dynId: plan.dynId ?? null,
      startYear: plan.startYear ?? null,
      endYear: plan.endYear ?? null,
    };
  }

  const matchKey = buildMatchKey({
    dyn: plan.dyn,
    fief: plan.fief,
    pn: plan.pn,
    nt: plan.nt,
    person: plan.personBare,
  });

  // The wiki asset is deliberately still a compact, structured input to the
  // Norbert runtime.  It is not the output of name expansion.  These fields
  // provide the AuthorityCandidate envelope required by Grognard's strict NDJSON
  // loader while retaining the original structured payload below.
  const personAuthorityId =
    norbertPersonId ?? (wiki.wikidataId ? `wikidata:${wiki.wikidataId}` : null);
  const titleSurface = [wiki.fief, wiki.pn, wiki.nt].filter(Boolean).join('');
  const primaryName = wiki.person || titleSurface || wiki.sourcePage;
  const searchStrings = buildNtSearchStrings(wiki);
  // Some review rows are person/Wikidata links from pages whose title
  // components could not be recovered. They are useful review evidence, but
  // they are not taggable noble-title records and must not be emitted as
  // malformed authority rows.
  if (searchStrings.length === 0) return null;
  const wrapperSearchStrings = wiki.person
    ? searchStrings.filter((surface) => surface.endsWith(wiki.person))
    : [];
  const titleSearchStrings = wiki.person
    ? searchStrings.filter((surface) => !surface.endsWith(wiki.person))
    : searchStrings;
  const components = {
    nationality: undefined,
    fief: wiki.fief ?? undefined,
    roleName: wiki.nt ?? undefined,
    posthumousName: wiki.pn ?? undefined,
    persName: wiki.person ?? undefined,
  };
  const wrapper = personAuthorityId && wiki.person
    ? {
        personId: personAuthorityId,
        titleRowId: `wnt-${String(index + 1).padStart(4, '0')}`,
        components,
      }
    : undefined;

  return {
    id: `wnt-${String(index + 1).padStart(4, '0')}`,
    source: 'norbert-wikipedia',
    authorityId: `wiki-nt:${String(index + 1).padStart(4, '0')}`,
    kind: 'person',
    primaryName,
    action,
    matchKey,
    searchStrings,
    names: wiki.person ? [{ text: wiki.person, type: 'wrapper-person' }] : [],
    wiki,
    norbert,
    proposedNt,
    reviewerNotes: row.reviewer_notes ?? null,
    metadata: {
      isNobleTitle: true,
      teiTag: wrapper ? undefined : 'nobleTitle',
      sourceRef: wiki.sourcePageUrl ?? wiki.sourcePage ?? undefined,
      dynasty: wiki.dyn ?? undefined,
      startYear: wiki.startYear ?? undefined,
      endYear: wiki.endYear ?? undefined,
      crosswalk: {
        ...(wiki.wikidataId ? { wikidata: [wiki.wikidataId] } : {}),
        ...(norbertPersonId ? { norbert: norbertPersonId } : {}),
      },
      wrapper,
      wrapperSearchStrings,
      titleSearchStrings,
      nobleTitle: {
        fief: wiki.fief ?? undefined,
        roleName: wiki.nt ?? undefined,
        posthumousName: wiki.pn ?? undefined,
      },
    },
  };
}

/**
 * @param {Record<string, unknown>[]} rows
 * @param {Record<string, Record<string, string>>} correctionsByReviewId
 * @param {Map<string, number>} [dynIdByName]
 */
export function compileWikiNtAsset(rows, correctionsByReviewId, dynIdByName = new Map()) {
  /** @type {Record<string, unknown>[]} */
  const records = [];
  /** @type {Record<string, number>} */
  const actionCounts = {};

  for (const [index, row] of rows.entries()) {
    const merged = mergeCorrections(row, correctionsByReviewId);
    const plan = buildApplyPlan(merged, dynIdByName);
    const record = planToAssetRecord(plan, merged, records.length);
    if (!record) continue;
    records.push(record);
    const key = String(record.action);
    actionCounts[key] = (actionCounts[key] ?? 0) + 1;
  }

  return {
    id: 'norbert-wiki-nt',
    source: 'zh.wikipedia',
    assetVersion: '1',
    compiledAt: new Date().toISOString(),
    license: 'CC-BY-SA-4.0',
    attribution: 'Noble title holders from zh.wikipedia; Norbert person ids/names curated locally.',
    recordCount: records.length,
    actionCounts,
    records,
  };
}
