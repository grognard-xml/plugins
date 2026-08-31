import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from _corpus import build_fake_corpus
from cbeta_import import corpus_sync


class CorpusSyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cache = self.tmp / "cache"
        self.cache.mkdir()
        self.src = self.tmp / "src"
        build_fake_corpus(self.src)  # src/ now holds T/ and L/ canon folders

    def tearDown(self):
        self._tmp.cleanup()

    def test_status_empty(self):
        st = corpus_sync.corpus_status(self.cache)
        self.assertFalse(st["present"])
        self.assertEqual(st["pinned_tag"], corpus_sync.DATA_VERSION_TAG)

    def test_install_from_directory(self):
        res = corpus_sync.install_from_source(self.src, self.cache)
        self.assertEqual(res["kind"], "directory")
        checkout = self.cache / "corpus" / "xml-p5"
        self.assertTrue((checkout / "T" / "T01" / "T01n0001.xml").is_file())
        st = corpus_sync.corpus_status(self.cache)
        self.assertTrue(st["present"])
        self.assertTrue(str(st["source"]).startswith("install_from_source:directory"))

    def test_install_from_nested_directory(self):
        nested = self.tmp / "wrap"
        (nested / "cbeta-xml-p5-main").mkdir(parents=True)
        for child in self.src.iterdir():
            shutil.move(str(child), nested / "cbeta-xml-p5-main" / child.name)
        res = corpus_sync.install_from_source(nested, self.cache)
        self.assertEqual(res["kind"], "directory")
        self.assertTrue(
            (self.cache / "corpus" / "xml-p5" / "L" / "L130" / "L130n1557.xml").is_file()
        )

    def test_install_from_zip(self):
        archive = self.tmp / "corpus.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for path in self.src.rglob("*.xml"):
                zf.write(path, path.relative_to(self.src.parent))
        res = corpus_sync.install_from_source(archive, self.cache)
        self.assertEqual(res["kind"], "archive:zip")
        self.assertTrue(
            (self.cache / "corpus" / "xml-p5" / "T" / "T05" / "T05n0220a.xml").is_file()
        )

    def test_install_missing_source(self):
        with self.assertRaises(FileNotFoundError):
            corpus_sync.install_from_source(self.tmp / "nope", self.cache)

    def test_install_replaces_previous(self):
        corpus_sync.install_from_source(self.src, self.cache)
        (self.src / "T" / "T01" / "T01n0001.xml").unlink()
        corpus_sync.install_from_source(self.src, self.cache)
        self.assertFalse(
            (self.cache / "corpus" / "xml-p5" / "T" / "T01" / "T01n0001.xml").is_file()
        )

    def test_sync_refuses_nongit_dir_without_force(self):
        (self.cache / "corpus" / "xml-p5").mkdir(parents=True)
        (self.cache / "corpus" / "xml-p5" / "stray.txt").write_text("x", "utf-8")
        if shutil.which("git") is None:
            with self.assertRaises(RuntimeError):
                corpus_sync.sync_corpus(self.cache)
        else:
            with self.assertRaises(RuntimeError):
                corpus_sync.sync_corpus(self.cache)

    @unittest.skipUnless(os.environ.get("CBETA_SYNC_IT"), "network integration test")
    def test_sync_clone_live(self):
        res = corpus_sync.sync_corpus(self.cache)
        self.assertIn(res["action"], {"cloned", "updated"})
        self.assertTrue((self.cache / "corpus" / "xml-p5" / "T").is_dir())


if __name__ == "__main__":
    unittest.main()
