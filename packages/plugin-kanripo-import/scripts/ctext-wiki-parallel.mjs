/**
 * Fetch punctuated rows/sections from ctext.org wiki chapter pages.
 * Keeps <span class="inlinecomment">…</span> for segmented parallel punctuation.
 */

const ROW_PATTERN =
  /<tr\b[^>]*\bclass="result"[^>]*\bid="(p\d+)"[^>]*>([\s\S]*?)<\/tr>/gi;

const HEADING_IN_ROW =
  /<h3\b[^>]*\bid="([^"]*)"[^>]*\bclass="wikisubsectiontitle"[^>]*>([\s\S]*?)<\/h3>/i;

const CONTENT_CELL =
  /<td\b[^>]*\bclass="ctext"[^>]*>\s*(\d+)\s*[\s\S]*?<\/td>\s*<td\b[^>]*\bclass="ctext"[^>]*>([\s\S]*?)<\/td>/i;

const SINGLE_CELL =
  /<td\b[^>]*\bclass="ctext"[^>]*>([\s\S]*?)<\/td>/i;

const CHAPTER_LINK =
  /href="wiki\.pl\?if=([^&"]+)&amp;chapter=(\d+)(?:#[^"]*)?">([^<]*)</gi;

const FETCH_HEADERS = {
  'User-Agent': 'grognard-plugin-kanripo-import/0.1 (+https://github.com/leJeanBaptiste)',
};

const CAPTCHA_MARKERS = [
  'Please confirm that you are human',
  '敬請輸入認證圖案',
  'unban.pl',
];

const CHAPTER_FETCH_DELAY_MS = 1500;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function isCtextCaptchaPage(html) {
  return CAPTCHA_MARKERS.some((marker) => html.includes(marker));
}

function assertReadableWikiHtml(html) {
  if (isCtextCaptchaPage(html)) {
    throw new Error(
      'ctext.org is asking for human verification (captcha). Wait a few minutes, open the URL in your browser to confirm you are human, then try again. Fetching many chapters quickly can trigger this.',
    );
  }
}

export function cleanRowHtml(raw) {
  return raw
    .replace(/<a\b[^>]*>[\s\S]*?<\/a>/gi, '')
    .replace(/<img\b[^>]*>/gi, '')
    .replace(/<\/?(td|tr|table|tbody|thead|div|br)\b[^>]*>/gi, '')
    .replace(/>\s+</g, '><')
    .trim();
}

export function normalizeSectionQuery(value) {
  return String(value || '')
    .replace(/[《》·\s]/g, '')
    .trim();
}

export function headingTitleFromHtml(html) {
  return cleanRowHtml(html)
    .replace(/<span\b[^>]*>[\s\S]*?<\/span>/gi, '')
    .replace(/<[^>]+>/g, '')
    .trim();
}

/** Parse ``wiki.pl?chapter=…`` or ``wiki.pl?res=…`` ctext wiki URLs. */
export function parseCtextWikiUrl(url) {
  let parsed;
  try {
    parsed = new URL(String(url || '').trim());
  } catch {
    return null;
  }
  if (!/(^|\.)ctext\.org$/i.test(parsed.hostname)) return null;
  if (!/wiki\.pl/i.test(parsed.pathname)) return null;

  const ifParam = parsed.searchParams.get('if') || 'gb';
  const chapter = parsed.searchParams.get('chapter');
  const res = parsed.searchParams.get('res');
  const base = { origin: parsed.origin, wikiPath: parsed.pathname, if: ifParam };

  if (chapter) return { kind: 'chapter', chapter, ...base };
  if (res) return { kind: 'res', res, ...base };
  return null;
}

export function chapterUrlFrom(wiki, chapterId) {
  const params = new URLSearchParams({ if: wiki.if, chapter: String(chapterId) });
  return `${wiki.origin}${wiki.wikiPath}?${params.toString()}`;
}

/** Chapter links from a ``res=`` wiki index (table of contents). */
export function parseWikiResIndex(html) {
  const chapters = new Map();

  for (const match of html.matchAll(CHAPTER_LINK)) {
    const ifParam = match[1];
    const id = match[2];
    const title = match[3].trim();
    const hasFragment = match[0].includes('#');

    if (!chapters.has(id)) {
      chapters.set(id, { id, if: ifParam, title: title || id });
      continue;
    }
    const existing = chapters.get(id);
    if (!hasFragment && title) {
      existing.title = title;
    }
  }

  return [...chapters.values()];
}

export function parseWikiPage(html) {
  const rows = [];
  const sections = [];
  let currentSection = null;

  for (const match of html.matchAll(ROW_PATTERN)) {
    const id = match[1];
    const inner = match[2];
    const heading = HEADING_IN_ROW.exec(inner);
    if (heading) {
      const slug = heading[1];
      const title = headingTitleFromHtml(heading[2]);
      currentSection = {
        id,
        slug,
        title,
        normalized: normalizeSectionQuery(title || slug),
        rows: [],
      };
      sections.push(currentSection);
      rows.push({ id, kind: 'heading', section: currentSection, text: title });
      continue;
    }

    const content = CONTENT_CELL.exec(inner);
    if (content) {
      const text = cleanRowHtml(content[2]);
      const row = {
        id,
        kind: 'content',
        number: Number.parseInt(content[1], 10),
        text,
        section: currentSection,
      };
      rows.push(row);
      currentSection?.rows.push(row);
      continue;
    }

    const single = SINGLE_CELL.exec(inner);
    if (single && !inner.includes('colspan="2"')) {
      const text = cleanRowHtml(single[1]);
      if (text) {
        const row = { id, kind: 'content', number: null, text, section: currentSection };
        rows.push(row);
        currentSection?.rows.push(row);
      }
    }
  }

  return { rows, sections };
}

export function listWikiSections(html) {
  return parseWikiPage(html).sections.map((section) => ({
    id: section.id,
    slug: section.slug,
    title: section.title,
    rowCount: section.rows.length,
  }));
}

/** Sections inside a chapter page, or top-level chapters on a ``res=`` index. */
export function listWikiCatalog(html) {
  const sections = listWikiSections(html);
  if (sections.length) return sections;
  return parseWikiResIndex(html).map((chapter) => ({
    id: chapter.id,
    slug: chapter.id,
    title: chapter.title || chapter.id,
    rowCount: 0,
  }));
}

async function fetchWikiHtml(url, { attempts = 4 } = {}) {
  let lastError = null;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, { headers: FETCH_HEADERS });
      if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
      const html = await response.text();
      assertReadableWikiHtml(html);
      return html;
    } catch (error) {
      lastError = error;
      if (error instanceof Error && error.message.includes('human verification')) {
        throw error;
      }
      if (attempt === attempts) break;
      await sleep(1000 * 2 ** (attempt - 1));
    }
  }

  const detail = lastError instanceof Error ? lastError.message : String(lastError);
  throw new Error(`Could not fetch ${url}: ${detail}`);
}

function chooseRow(rows, { row, id, contains }) {
  const contentRows = rows.filter((item) => item.kind === 'content');
  if (!contentRows.length) {
    throw new Error('No wiki content rows found. The page layout may have changed.');
  }
  if (contains) {
    const hit = contentRows.find((item) => item.text.includes(contains));
    if (!hit) throw new Error(`No row contains ${JSON.stringify(contains)}.`);
    return hit;
  }
  if (id) {
    const target = id.startsWith('p') ? id : `p${id}`;
    const hit = contentRows.find((item) => item.id === target);
    if (!hit) {
      throw new Error(`Row id ${id} not found. Available: ${contentRows.map((item) => item.id).join(', ')}`);
    }
    return hit;
  }
  if (row != null) {
    const number = Number.parseInt(String(row), 10);
    const hit = contentRows.find((item) => item.number === number);
    if (!hit) {
      throw new Error(`Row number ${row} not found.`);
    }
    return hit;
  }
  return contentRows[0];
}

function chooseSection(sections, sectionQuery) {
  const needle = normalizeSectionQuery(sectionQuery);
  if (!needle) throw new Error('Section query is empty.');
  const hit =
    sections.find((section) => section.normalized.includes(needle)) ||
    sections.find((section) => section.slug.includes(needle)) ||
    sections.find((section) => section.title.includes(sectionQuery.trim()));
  if (!hit) {
    const titles = sections.map((section) => section.title || section.slug).filter(Boolean);
    throw new Error(`Section ${JSON.stringify(sectionQuery)} not found. Available: ${titles.join(', ')}`);
  }
  if (!hit.rows.length) {
    throw new Error(`Section ${hit.title || hit.slug} has no content rows.`);
  }
  return hit;
}

async function fetchCtextWikiChapterParallel(url, options, html = null) {
  const pageHtml = html ?? (await fetchWikiHtml(url));
  const parsed = parseWikiPage(pageHtml);
  const hasFilter =
    options?.section || options?.contains || options?.row != null || options?.id;

  if (!hasFilter) {
    const contentRows = parsed.rows.filter((item) => item.kind === 'content');
    if (!contentRows.length) {
      throw new Error('No wiki content rows found. The page layout may have changed.');
    }
    const text = contentRows.map((row) => row.text).join('');
    return {
      text,
      label: 'ctext: whole chapter',
      rowIds: contentRows.map((row) => row.id),
      sections: listWikiSections(pageHtml),
    };
  }

  if (options?.section) {
    const section = chooseSection(parsed.sections, options.section);
    const text = section.rows.map((row) => row.text).join('');
    return {
      text,
      label: `ctext: ${section.title || section.slug}`,
      section: section.title || section.slug,
      rowIds: section.rows.map((row) => row.id),
      sections: listWikiSections(pageHtml),
    };
  }

  const chosen = chooseRow(parsed.rows, options);
  return {
    text: chosen.text,
    label: `ctext ${chosen.id}`,
    rowId: chosen.id,
    sections: listWikiSections(pageHtml),
  };
}

async function fetchCtextWikiResIndexParallel(wiki, url, options) {
  const indexHtml = await fetchWikiHtml(url);
  const chapters = parseWikiResIndex(indexHtml);
  if (!chapters.length) {
    throw new Error(
      'This ctext wiki index has no chapter links. The page layout may have changed.',
    );
  }

  const hasFilter =
    options?.section || options?.contains || options?.row != null || options?.id;

  if (hasFilter) {
    let lastError = null;
    for (let index = 0; index < chapters.length; index += 1) {
      const chapter = chapters[index];
      if (index > 0) await sleep(CHAPTER_FETCH_DELAY_MS);
      const chapterUrl = chapterUrlFrom(wiki, chapter.id);
      try {
        return await fetchCtextWikiChapterParallel(chapterUrl, options);
      } catch (error) {
        lastError = error;
        if (options?.section && error instanceof Error && /Section .* not found/.test(error.message)) {
          continue;
        }
        throw error instanceof Error
          ? new Error(`Failed on chapter ${chapter.title || chapter.id}: ${error.message}`)
          : error;
      }
    }
    const message =
      lastError instanceof Error
        ? lastError.message
        : 'No matching section found in this wiki index.';
    throw new Error(message);
  }

  if (!options?.fetchAll) {
    throw new Error(
      `This ctext URL is a whole-work index (${chapters.length} chapters), not one commentary page. ` +
        'Click “List ctext sections” and pick a chapter, or paste a …&chapter=… URL instead.',
    );
  }

  const parts = [];
  const rowIds = [];
  const skipped = [];
  for (let index = 0; index < chapters.length; index += 1) {
    const chapter = chapters[index];
    if (index > 0) await sleep(CHAPTER_FETCH_DELAY_MS);
    const chapterUrl = chapterUrlFrom(wiki, chapter.id);
    try {
      const result = await fetchCtextWikiChapterParallel(chapterUrl, {});
      parts.push(result.text);
      rowIds.push(...(result.rowIds || []));
    } catch (error) {
      if (error instanceof Error && error.message.includes('No wiki content rows found')) {
        skipped.push(chapter.title || chapter.id);
        continue;
      }
      throw error instanceof Error
        ? new Error(`Failed on chapter ${chapter.title || chapter.id}: ${error.message}`)
        : error;
    }
  }

  if (!parts.length) {
    throw new Error('No commentary rows found in any chapter of this wiki index.');
  }

  const skippedNote = skipped.length ? ` (${skipped.length} empty chapters skipped)` : '';
  return {
    text: parts.join(''),
    label: `ctext: ${parts.length} chapters${skippedNote}`,
    rowIds,
    sections: chapters.map((chapter) => ({
      id: chapter.id,
      slug: chapter.id,
      title: chapter.title || chapter.id,
      rowCount: 0,
    })),
  };
}

export async function fetchCtextWikiParallel(options) {
  const url = String(options?.url || '').trim();
  if (!url) throw new Error('Missing ctext wiki URL.');

  const wiki = parseCtextWikiUrl(url);
  if (!wiki) {
    throw new Error(
      'Not a ctext wiki URL (expected …/wiki.pl?…&chapter=… or …/wiki.pl?…&res=…).',
    );
  }

  if (wiki.kind === 'res') {
    return fetchCtextWikiResIndexParallel(wiki, url, options);
  }

  return fetchCtextWikiChapterParallel(url, options);
}
