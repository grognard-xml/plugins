import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from _corpus import write_work

_PKG = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "build_cbeta_metadata", _PKG / "scripts" / "build-cbeta-metadata.py"
)
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


CATALOG_T = {
    "T0001": {
        "title": "長阿含經",
        "byline": "後秦 佛陀耶舍共竺佛念譯",
        "dynasty": "後秦",
        "category": "阿含部類",
        "orig_category": "阿含部",
        "juans": 22,
        "vol": "T01",
        "type": "textbody",
        "authorityID": "CA0000427",
        "contributors": [
            {"id": "A000439", "name": "佛陀耶舍"},
            {"id": "A000435", "name": "竺佛念"},
        ],
    },
    "T0220": {
        "title": "大般若波羅蜜多經",
        "byline": "唐 玄奘譯",
        "dynasty": "唐",
        "category": "般若部類",
        "orig_category": "般若部",
        "juans": 600,
        "vol": "T05..T07",
        "type": "textbody",
        "contributors": [{"id": "A000294", "name": "玄奘"}],
    },
}
CATALOG_L = {
    "L1557": {
        "title": "阿毘達磨大毘婆沙論",
        "byline": "唐 玄奘譯",
        "dynasty": "唐",
        "orig_category": "毘曇部",
        "juans": 7,
        "vol": "L130..L131",
        "type": "textbody",
        "contributors": [{"id": "A000294", "name": "玄奘"}],
    }
}


class BuildMetadataTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

        self.cat_dir = self.tmp / "authority_catalog" / "json"
        self.cat_dir.mkdir(parents=True)
        (self.cat_dir / "T.json").write_text(json.dumps(CATALOG_T), "utf-8")
        (self.cat_dir / "L.json").write_text(json.dumps(CATALOG_L), "utf-8")

        self.corpus = self.tmp / "xml-p5"
        write_work(self.corpus, "T01n0001", title="長阿含經", author="後秦 佛陀耶舍共竺佛念譯", juan=22)
        write_work(self.corpus, "T05n0220a", title="大般若", author="唐 玄奘譯", juan=1)
        write_work(self.corpus, "T06n0220b", title="大般若", author="唐 玄奘譯", juan=1)
        write_work(self.corpus, "L130n1557", title="大毘婆沙論", author="唐 玄奘譯", juan=3)
        write_work(self.corpus, "L131n1557", title="大毘婆沙論", author="唐 玄奘譯", juan=4)

        self.xw = self.tmp / "crosswalk.csv"
        self.xw.write_text(
            "dila_id,norbert_id,wikidata_qid\nA000294,50123,Q188528\nA000439,50777,\n", "utf-8"
        )

        self.person = self.tmp / "persons.xml"
        self.person.write_text(
            '<list xmlns:xml="http://www.w3.org/XML/1998/namespace">'
            '<person xml:id="A000294"><birth>602</birth><death>664</death>'
            '<ref>https://www.wikidata.org/wiki/Q188528</ref></person>'
            '<person xml:id="A000435"><death>413</death></person>'
            "</list>",
            "utf-8",
        )

        self.out = self.tmp / "data"

    def tearDown(self):
        self._tmp.cleanup()

    def run_build(self, *extra):
        rc = build.main(
            [
                "--authority-catalog", str(self.cat_dir),
                "--corpus", str(self.corpus),
                "--out", str(self.out),
                *extra,
            ]
        )
        self.assertEqual(rc, 0)
        wi = json.loads((self.out / "metadata" / "work_info.json").read_text("utf-8"))
        ci = json.loads((self.out / "metadata" / "catalog_index.json").read_text("utf-8"))
        return wi, ci

    def test_work_info_basic(self):
        wi, _ = self.run_build()
        self.assertEqual(wi["T0001"]["dynasty"], "後秦")
        self.assertEqual(wi["T0001"]["category"], "阿含部")  # orig_category preferred
        self.assertEqual(wi["T0001"]["juan_count"], 22)
        names = [c["person_name"] for c in wi["T0001"]["contributors"]]
        self.assertEqual(names, ["佛陀耶舍", "竺佛念"])
        self.assertTrue(all(c["role"] == "translator" for c in wi["T0001"]["contributors"]))
        self.assertEqual(wi["T0001"]["contributors"][0]["dila_id"], "A000439")

    def test_crosswalk_and_person_enrichment(self):
        wi, _ = self.run_build("--crosswalk", str(self.xw), "--authority-person", str(self.person))
        xuanzang = wi["T0220"]["contributors"][0]
        self.assertEqual(xuanzang["dila_id"], "A000294")
        self.assertEqual(xuanzang["norbert_id"], "50123")
        self.assertEqual(xuanzang["wikidata_qid"], "Q188528")
        self.assertEqual(xuanzang["dates"], "602–664")

    def test_catalog_index_file_grouping(self):
        _, ci = self.run_build()
        by_id = {w["work_id"]: w for w in ci["works"]}
        self.assertEqual(by_id["T0001"]["files"], ["T01n0001"])
        self.assertEqual(by_id["T0220"]["files"], ["T05n0220a", "T06n0220b"])  # from corpus
        self.assertEqual(by_id["L1557"]["files"], ["L130n1557", "L131n1557"])
        self.assertEqual(by_id["T0220"]["juan_count"], 600)  # from authority catalog

    def test_catalog_index_without_corpus_uses_vol(self):
        rc = build.main(
            ["--authority-catalog", str(self.cat_dir), "--out", str(self.out)]
        )
        self.assertEqual(rc, 0)
        ci = json.loads((self.out / "metadata" / "catalog_index.json").read_text("utf-8"))
        by_id = {w["work_id"]: w for w in ci["works"]}
        self.assertEqual(by_id["T0001"]["files"], ["T01n0001"])  # reconstructed from vol
        self.assertEqual(by_id["T0220"]["files"], [])  # range → unknown without corpus

    def test_consumed_by_catalog_index_load(self):
        """The built catalog_index.json is loadable by the runtime module."""
        self.run_build()
        import shutil

        from cbeta_import import _paths, catalog_index

        # point the runtime bundled path at our freshly built file
        orig = _paths.bundled_catalog_index_path
        try:
            _paths.bundled_catalog_index_path = lambda: self.out / "metadata" / "catalog_index.json"
            hits = catalog_index.load_index(cache_root=self.tmp)
            self.assertIn("T0220", {h.work_id for h in hits})
        finally:
            _paths.bundled_catalog_index_path = orig
            shutil.rmtree(self.out, ignore_errors=True)

    def test_no_sources_writes_placeholders(self):
        rc = build.main(["--out", str(self.out)])
        self.assertEqual(rc, 0)
        self.assertEqual(
            json.loads((self.out / "metadata" / "work_info.json").read_text("utf-8")), {}
        )


if __name__ == "__main__":
    unittest.main()
