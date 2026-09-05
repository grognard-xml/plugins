/** Noble rank suffixes (爵位), longest first where multi-char. */
export const NT_SUFFIXES = [
  '王',
  '侯',
  '公',
  '伯',
  '子',
  '男',
  '帝',
  '太子',
  '皇后',
  '太后',
  '太妃',
];

/** Wikipedia category seed for three-character title disambiguation pages. */
export const DEFAULT_WIKI_CATEGORY = 'Category:三字封號消歧義';

/** Section headers to skip when crawling holder lists. */
export const SKIP_SECTIONS = new Set([
  '参考资料',
  '參考資料',
  '参见',
  '參見',
  '相关条目',
  '相關條目',
  '外部链接',
  '外部連結',
  '注释',
  '註釋',
  '脚注',
  '腳註',
]);

export const WIKI_API = 'https://zh.wikipedia.org/w/api.php';

/** Required by Wikimedia API etiquette. */
export const WIKI_USER_AGENT = 'Grognard-Norbert-Plugin/0.1 (digital humanities; norbert wiki noble titles fetch)';
