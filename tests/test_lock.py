import json
import os
import unittest

from helpers import BIG, REVISION, SMALL, TempDirTest, git_blob, make_git_repo, make_hf_model, sha

from hakobune import hashing
from hakobune.config import LocalSource, ModelSpec, RecipeSpec, check_relpath, load_components
from hakobune.errors import HakobuneError
from hakobune.lock import resolve_model, resolve_recipe


class HashingTest(unittest.TestCase):
    def test_git_blob_matches_git(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"hello\n")
            f.flush()
            self.assertEqual(hashing.git_blob_sha1(f.name), "ce013625030ba8dba906f756967f9e9ca394464a")


class ModelLockTest(TempDirTest):
    spec = ModelSpec("m", "org/m", REVISION, (".gitattributes",))

    def test_tree_gives_upstream_hashes(self):
        base = make_hf_model(self)
        entry, extra = resolve_model(self.spec, LocalSource(base))
        self.assertEqual(entry["verified_against"], "hf-tree")
        files = {f["path"]: f for f in entry["files"]}
        self.assertEqual(set(files), {"config.json", "model.safetensors"})  # .gitattributes excluded
        self.assertEqual(files["model.safetensors"]["sha256"], sha(BIG))
        self.assertEqual(files["config.json"]["sha256"], sha(SMALL))
        self.assertEqual(extra, [])

    def test_download_metadata_fallback(self):
        base = make_hf_model(self, tree=False)
        entry, extra = resolve_model(self.spec, LocalSource(base))
        self.assertEqual(entry["verified_against"], "hf-download-metadata")
        self.assertEqual(len(entry["files"]), 2)

    def test_modified_small_file_is_refused(self):
        base = make_hf_model(self)
        self.write("model/config.json", SMALL.replace(b"Test", b"Tost"))
        with self.assertRaisesRegex(HakobuneError, "differs from upstream"):
            resolve_model(self.spec, LocalSource(base))

    def test_wrong_size_is_refused(self):
        base = make_hf_model(self)
        self.write("model/model.safetensors", BIG[:-1])
        with self.assertRaisesRegex(HakobuneError, "upstream says"):
            resolve_model(self.spec, LocalSource(base))

    def test_missing_file_is_refused(self):
        base = make_hf_model(self)
        os.unlink(os.path.join(base, "config.json"))
        with self.assertRaisesRegex(HakobuneError, "missing"):
            resolve_model(self.spec, LocalSource(base))

    def test_other_revision_is_refused(self):
        base = make_hf_model(self, tree=False, revision="b" * 40)
        with self.assertRaisesRegex(HakobuneError, "expected"):
            resolve_model(self.spec, LocalSource(base))

    def test_no_metadata_is_a_provenance_gap(self):
        base = make_hf_model(self)
        import shutil
        shutil.rmtree(os.path.join(base, ".cache"))
        with self.assertRaisesRegex(HakobuneError, "cannot prove"):
            resolve_model(self.spec, LocalSource(base))

    def test_local_extra_file_is_reported_not_locked(self):
        base = make_hf_model(self)
        self.write("model/notes.txt", b"mine")
        entry, extra = resolve_model(self.spec, LocalSource(base))
        self.assertEqual(extra, ["notes.txt"])
        self.assertNotIn("notes.txt", [f["path"] for f in entry["files"]])


class RecipeLockTest(TempDirTest):
    def test_reads_the_commit_not_the_working_tree(self):
        repo, commit = make_git_repo(self, {"map.json": b"{}\n"})
        self.write("recipe/map.json", b"edited\n")  # uncommitted change
        entry = resolve_recipe(RecipeSpec("r", "", commit, ("map.json",)), repo)
        self.assertEqual(entry["files"][0]["sha256"], sha(b"{}\n"))
        self.assertEqual(entry["files"][0]["git_blob"], git_blob(b"{}\n"))

    def test_missing_file_at_commit(self):
        repo, commit = make_git_repo(self, {"a": b"1"})
        with self.assertRaises(HakobuneError):
            resolve_recipe(RecipeSpec("r", "", commit, ("b",)), repo)


class ComponentsTest(TempDirTest):
    def load(self, data):
        path = self.write("components.json", json.dumps(data).encode())
        return load_components(path)

    def test_mutable_tag_needs_image_id(self):
        with self.assertRaisesRegex(HakobuneError, "mutable"):
            self.load({"schema": 1, "images": [{"name": "a", "ref": "x/y:1"}]})

    def test_short_revision_refused(self):
        with self.assertRaisesRegex(HakobuneError, "40-hex"):
            self.load({"schema": 1, "models": [{"name": "m", "hf_repo": "o/m", "revision": "abc"}]})

    def test_unsafe_paths(self):
        for bad in ("/etc/passwd", "../x", "a/../../b", "a//b", ""):
            with self.assertRaises(HakobuneError, msg=bad):
                check_relpath(bad, "t")
        check_relpath("recipe/draft-token-maps/x.json", "t")


if __name__ == "__main__":
    unittest.main()
