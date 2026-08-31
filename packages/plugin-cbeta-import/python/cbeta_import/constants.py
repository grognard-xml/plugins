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
