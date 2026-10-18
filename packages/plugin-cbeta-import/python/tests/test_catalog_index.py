import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _corpus import build_fake_corpus
from cbeta_import import _paths, catalog_index


class CatalogIndexTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name)
        self.corpus = self.cache / "corpus" / "xml-p5"
        build_fake_corpus(self.corpus)
        # isolate from any real bundled catalog_index.json
        self._orig_bundled = _paths.bundled_catalog_index_path
        _paths.bundled_catalog_index_path = lambda: self.cache / "no-bundled.json"

    def tearDown(self):
        _paths.bundled_catalog_index_path = self._orig_bundled
        self._tmp.cleanup()

    def index(self):
        return catalog_index.load_index(cache_root=self.cache, corpus_root=self.corpus)

    def test_work_grouping(self):
        ids = {h.work_id for h in self.index()}
        self.assertEqual(
            ids,
            {"T0001", "T0128a", "T0128b", "T0150A", "T0150B", "L1557", "T0220"},
        )

    def test_multi_file_works(self):
        by_id = {h.work_id: h for h in self.index()}
        self.assertEqual(len(by_id["L1557"].files), 2)
        self.assertEqual(by_id["L1557"].files, ("L130n1557", "L131n1557"))
        self.assertEqual(len(by_id["T0220"].files), 2)
        self.assertEqual(by_id["T0001"].files, ("T01n0001",))

    def test_header_fields(self):
        t1 = {h.work_id: h for h in self.index()}["T0001"]
        self.assertIn("長阿含經", t1.title)
        self.assertEqual(t1.dynasty, "後秦")
        self.assertEqual(t1.juan_count, 2)

    def test_multi_file_juan_count_summed(self):
        l1557 = {h.work_id: h for h in self.index()}["L1557"]
        self.assertEqual(l1557.juan_count, 7)  # 3 + 4

    def test_search(self):
        self.assertEqual(catalog_index.search("T0001", cache_root=self.cache)[0].work_id, "T0001")
        titles = [h.title for h in catalog_index.search("大般若", cache_root=self.cache)]
        self.assertTrue(any("大般若" in t for t in titles))
        self.assertEqual(
            {h.work_id for h in catalog_index.search("玄奘", cache_root=self.cache)},
            {"L1557", "T0220"},
        )

    def test_resolve_by_work_id(self):
        paths = catalog_index.resolve_work_files("T0001", cache_root=self.cache)
        self.assertEqual([p.name for p in paths], ["T01n0001.xml"])
        multi = catalog_index.resolve_work_files("L1557", cache_root=self.cache)
        self.assertEqual([p.name for p in multi], ["L130n1557.xml", "L131n1557.xml"])

    def test_resolve_by_filename_stem(self):
        paths = catalog_index.resolve_work_files("T01n0001", cache_root=self.cache)
        self.assertEqual([p.name for p in paths], ["T01n0001.xml"])

    def test_resolve_unknown_raises(self):
        with self.assertRaises(KeyError):
            catalog_index.resolve_work_files("T9999", cache_root=self.cache)

    def test_cache_written_and_reused(self):
        self.index()
        cached = self.cache / "catalog_index.json"
        self.assertTrue(cached.is_file())
        # remove the corpus; a cached load must still work
        for p in self.corpus.rglob("*.xml"):
            p.unlink()
        again = catalog_index.load_index(cache_root=self.cache, corpus_root=self.corpus)
        self.assertEqual({h.work_id for h in again}, {"T0001", "T0128a", "T0128b", "T0150A", "T0150B", "L1557", "T0220"})

    def test_missing_corpus_raises(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(RuntimeError):
                catalog_index.load_index(cache_root=Path(empty), corpus_root=Path(empty) / "nope")


class GroupStemsTest(unittest.TestCase):
    """File grouping from a bare path list (no corpus checkout) — planning §5.7."""

    def test_multi_and_single_and_distinct(self):
        g = catalog_index.group_stems(
            [
                "T/T01/T01n0001.xml",
                "T/T05/T05n0220a.xml",
                "T/T06/T06n0220b.xml",
                "T/T07/T07n0220c.xml",
                "L/L130/L130n1557.xml",
                "L131n1557",  # bare stem also accepted
                "T02n0128a",
                "T02n0128b",
                "T02n0150A",
                "T02n0150B",
                "README.md",  # ignored
            ]
        )
        self.assertEqual(g["T0001"], ("T01n0001",))
        self.assertEqual(g["T0220"], ("T05n0220a", "T06n0220b", "T07n0220c"))
        self.assertEqual(g["L1557"], ("L130n1557", "L131n1557"))
        self.assertEqual(g["T0128a"], ("T02n0128a",))  # lowercase suffix, same vol → distinct
        self.assertEqual(g["T0128b"], ("T02n0128b",))
        self.assertEqual(g["T0150A"], ("T02n0150A",))  # uppercase suffix → distinct
        self.assertNotIn("README", str(g))


if __name__ == "__main__":
    unittest.main()


class BundledCorpusFallbackTest(unittest.TestCase):
    """The host passes a cache folder (``cache_root`` / ``GROGNARD_PLUGIN_CACHE_PATH``) that has no
    corpus of its own. The corpus bundled with the installed plugin must still be used.

    Regression: ``resolve_work_files`` raised ``FileNotFoundError: work T2128: missing
    T54n2128.xml`` because an explicit cache root hid ``<plugin>/data/corpus/xml-p5``."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.plugin_data = self.tmp / "plugin" / "data"
        self.bundled = self.plugin_data / "corpus" / "xml-p5"
        build_fake_corpus(self.bundled)
        (self.plugin_data / "corpus.json").write_text(json.dumps({"commit": "bundled-commit"}), "utf-8")
        self.cache = self.tmp / "userData" / "plugin-cache" / "cbeta-import"  # does not exist
        for target, value in (
            ("data_dir", lambda: self.plugin_data),
            ("bundled_catalog_index_path", lambda: self.tmp / "no-bundled-index.json"),
        ):
            patcher = mock.patch.object(_paths, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"GROGNARD_PLUGIN_CACHE_PATH": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_explicit_empty_cache_root_uses_bundled_corpus(self):
        self.assertEqual(_paths.corpus_dir(self.cache), self.bundled)
        paths = catalog_index.resolve_work_files("T0001", cache_root=self.cache)
        self.assertEqual([p.name for p in paths], ["T01n0001.xml"])
        self.assertTrue(all(p.is_file() and self.bundled in p.parents for p in paths))

    def test_multi_file_work_resolves_from_bundled_corpus(self):
        paths = catalog_index.resolve_work_files("L1557", cache_root=self.cache)
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(p.is_file() for p in paths))

    def test_cache_path_from_environment_uses_bundled_corpus(self):
        with mock.patch.dict(os.environ, {"GROGNARD_PLUGIN_CACHE_PATH": str(self.cache)}):
            paths = catalog_index.resolve_work_files("T0001")
        self.assertTrue(all(p.is_file() and self.bundled in p.parents for p in paths))

    def test_cache_corpus_wins_when_it_has_one(self):
        cached = self.cache / "corpus" / "xml-p5"
        build_fake_corpus(cached)
        self.assertEqual(_paths.corpus_dir(self.cache), cached)
        paths = catalog_index.resolve_work_files("T0001", cache_root=self.cache)
        self.assertTrue(all(cached in p.parents for p in paths))

    def test_no_corpus_anywhere_keeps_the_sync_target(self):
        shutil.rmtree(self.bundled)
        self.assertEqual(_paths.corpus_dir(self.cache), self.cache / "corpus" / "xml-p5")
        with self.assertRaises(RuntimeError):
            catalog_index.resolve_work_files("T0001", cache_root=self.cache)

    def test_manifest_follows_the_corpus_in_use(self):
        self.assertEqual(_paths.corpus_manifest_path(self.cache), self.plugin_data / "corpus.json")
        self.assertEqual(catalog_index._corpus_commit(self.cache), "bundled-commit")
        self.cache.mkdir(parents=True)
        (self.cache / "corpus.json").write_text(json.dumps({"commit": "cache-commit"}), "utf-8")
        self.assertEqual(catalog_index._corpus_commit(self.cache), "cache-commit")

    def test_status_reports_the_bundled_corpus_as_present(self):
        from cbeta_import import corpus_sync

        st = corpus_sync.corpus_status(self.cache)
        self.assertTrue(st["present"])
        self.assertEqual(st["path"], str(self.bundled))
        self.assertEqual(st["commit"], "bundled-commit")
