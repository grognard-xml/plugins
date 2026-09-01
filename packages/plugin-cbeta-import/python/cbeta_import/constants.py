"""Shared constants for the CBETA corpus. See leaf-writer/docs/cbeta-import-planning.md."""

from __future__ import annotations

# --- upstream repos (fetched with git; see corpus_sync) -----------------------
# Public P5 corpus — https://github.com/cbeta-org/xml-p5 (not DILA-edu/cbeta-xml-p5).
XML_P5_REPO = "https://github.com/cbeta-org/xml-p5.git"
METADATA_REPO = "https://github.com/DILA-edu/cbeta-metadata.git"
# TODO(cbeta-import-planning §1): confirm the exact name/URL of the split-out
# catalog repo (the cbeta-metadata `catalog/` folder was deprecated 2026-05-21).
CATALOG_REPO = "https://github.com/DILA-edu/cbeta-catalog.git"
GAIJI_HAN_REPO = "https://github.com/cbeta-org/gaiji-CB.git"
GAIJI_SIDDHAM_REPO = "https://github.com/cbeta-org/sd-gif.git"
GAIJI_RANJANA_REPO = "https://github.com/cbeta-org/rj-gif.git"

# Pin. Recorded in every imported file's <revisionDesc><change> for provenance.
# Latest public release tag on cbeta-org/xml-p5 (2026-08-31); bump when CBETA ships R2.
DATA_VERSION_TAG = "2026R1"

# --- namespaces --------------------------------------------------------------
TEI_NS = "http://www.tei-c.org/ns/1.0"
CB_NS = "http://www.cbeta.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS, "cb": CB_NS, "xml": XML_NS}

# --- canon codes -----------------------------------------------------------
# ordering per cbeta-documentation/README (目錄排序)
CANON_ORDER = "T X A K S F C U P J L G M D N ZS I ZW B GA GB".split()

# Every CBETA canon code (xml-p5 ``canons.json``). Used to split a catalogue
# work id into canon + text number: only ``J`` (Jiaxing) carries a series
# letter in its number — ``JA042``, ``JB122`` — so ``JB`` must not be read as a
# two-letter canon the way ``CC``/``LC``/``TX``/``GA`` are.
CBETA_CANONS = frozenset(
    "A B C CC D F G GA GB I J K L LC M N P Q R S T TX U X Y YP Z ZS ZW".split()
)

# Canon code -> (edition label, first printing year, last printing year). The
# leading code of a work id identifies the printed edition a text was collated
# from; the CBETA file itself carries nothing more specific. ``build_tei_header``
# maps it to ``<edition>`` + ``<imprint><date>`` (``@when`` when the two years
# match, else ``@from``/``@to``). Names follow xml-p5 ``canons.json``; dates are
# the conventional printing spans. Kept in sync with the host
# ``apps/commons/src/desktop/cbetaCanons.ts`` table. Modern compilations and
# reprints (A, C, D, F, G, GA, GB, I, ZS) are intentionally omitted until their
# dates are pinned down.
CANON_EDITIONS: dict[str, tuple[str, str, str]] = {
    "T": ("大正新脩大藏經 (Taishō Shinshū Daizōkyō)", "1924", "1934"),
    "X": ("卍新纂大日本續藏經 (Manji Shinsan Dai Nihon Zokuzōkyō)", "1975", "1989"),
    "J": ("明版嘉興大藏經 (Jiaxing Canon)", "1589", "1712"),
    "L": ("乾隆大藏經 (Qianlong Canon / 龍藏)", "1733", "1738"),
    "K": ("高麗大藏經 (Tripiṭaka Koreana)", "1236", "1251"),
    "M": ("卍正藏經 (Manji Zōkyō)", "1902", "1905"),
    "P": ("永樂北藏 (Yongle Northern Canon)", "1419", "1440"),
    "S": ("宋藏遺珍 (Song Canon Fragments)", "1935", "1935"),
    "U": ("洪武南藏 (Hongwu Southern Canon)", "1372", "1398"),
    "N": ("漢譯南傳大藏經 (元亨寺版) (Chinese Translation of the Pāli Canon)", "1990", "1998"),
    "B": ("大藏經補編 (Supplement to the Canon)", "1985", "1985"),
}

# --- transform policy (cbeta-import-planning §7, decided 2026-08-31) ---------
# <lb>/<pb> @ed values to drop: 新文豐 reprint line refs on 卍續藏 texts.
DROP_ED = {"R135", "R138"}

# <note> @type not carried into the working file (superseded by type="mod").
DROP_NOTE_TYPES = {"orig"}

# <note> @type kept in <back> alongside the <app>.
KEEP_BACK_NOTE_TYPES = {"mod", "add", "rest", "equivalent"} | {
    f"cf{i}" for i in range(1, 7)
} | {"cf."}

# @style is indentation-only in public P5 — dropped wholesale.
DROP_STYLE = True

# juan boundary markers in <body>
JUAN_MILESTONE_UNIT = "juan"
