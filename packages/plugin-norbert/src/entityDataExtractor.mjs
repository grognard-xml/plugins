/**
 * Extract refreshable facts from a Norbert person wrapper.
 *
 * Recognizes both Norbert's original wrapper element names (`placeOfOrigin`,
 * `officeName`) and the canonical TEI shape LJB's own wrapper builder now
 * produces (a bare top-level `placeName`/`roleName` — see
 * `PERSON_WRAPPER_CHILD_ORDER` in cwrc-leafwriter's
 * `personWrapperValidation.ts`): nationality → roleName → nobleTitle →
 * placeName → persName. Mirrors `extractPersonWrapperFacts` in
 * cwrc-leafwriter's `hygiene/harvest.ts`, which already handles both forms
 * as a fallback when this plugin isn't loaded — keep the two in sync.
 */
export function extractNorbertEntityData({ wrapper }) {
  const assertions = [];
  const descendants = (name) => Array.from(wrapper.getElementsByTagName(name));
  for (const node of descendants('nationality')) {
    const value = node.textContent?.trim();
    if (value) assertions.push({ element: 'nationality', value, ref: node.getAttribute('ref') ?? undefined });
  }

  // Norbert uses <placeOfOrigin>; the canonical TEI shape uses a bare
  // top-level <placeName> (never nested inside <nobleTitle> — that one is
  // the title's own fief, not the person's origin).
  for (const node of descendants('placeOfOrigin')) {
    const value = node.textContent?.trim();
    if (value) assertions.push({ element: 'placeName', value, ref: node.getAttribute('ref') ?? undefined });
  }
  for (const node of Array.from(wrapper.children)) {
    if (node.localName !== 'placeName') continue;
    if (node.parentElement?.localName === 'nobleTitle') continue;
    const value = node.textContent?.trim();
    if (value) assertions.push({ element: 'placeName', value, ref: node.getAttribute('ref') ?? undefined });
  }

  // Norbert uses <officeName>; the canonical TEI shape uses a bare
  // top-level <roleName> (an ordinary office, distinct from the rank
  // nested inside <nobleTitle>).
  for (const node of descendants('officeName')) {
    const value = node.textContent?.trim();
    if (value) assertions.push({ element: 'state', value, ref: node.getAttribute('ref') ?? undefined });
  }
  for (const node of Array.from(wrapper.children)) {
    if (node.localName !== 'roleName') continue;
    const value = node.textContent?.trim();
    if (value) assertions.push({ element: 'state', value, ref: node.getAttribute('ref') ?? undefined });
  }

  for (const node of descendants('nobleTitle')) {
    const place = node.getElementsByTagName('placeName')[0];
    const role = node.getElementsByTagName('roleName')[0];
    const posthumous = Array.from(node.getElementsByTagName('persName'))
      .find((person) => person.getAttribute('type') === 'posthumous');
    const value = node.textContent?.trim();
    if (value) {
      assertions.push({
        element: 'nobleTitle',
        value,
        ref: node.getAttribute('ref') ?? undefined,
        children: [
          ...(place ? [{ element: 'placeName', value: place.textContent?.trim() ?? '', ref: place.getAttribute('ref') ?? undefined }] : []),
          ...(role ? [{ element: 'roleName', value: role.textContent?.trim() ?? '', ref: role.getAttribute('ref') ?? undefined }] : []),
          ...(posthumous ? [{ element: 'persName', value: posthumous.textContent?.trim() ?? '', ref: posthumous.getAttribute('ref') ?? undefined }] : []),
        ],
      });
    }
  }
  return assertions;
}
