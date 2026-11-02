import os
import stat
import unittest
from unittest import mock

from helpers import REVISION, TempDirTest, make_git_repo, make_hf_model, make_image_archive

from hakobune import docker
from hakobune.config import Local, LocalSource, ModelSpec, RecipeSpec
from hakobune.errors import HakobuneError
from hakobune.lock import resolve_model, resolve_recipe
from hakobune.store import Store


class StoreTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.model_dir = make_hf_model(self)
        self.repo, self.commit = make_git_repo(self, {"maps/d.json": b'{"ids": [1, 2]}\n', "LICENSE": b"Apache\n"})
        model, _ = resolve_model(ModelSpec("m", "org/m", REVISION, (".gitattributes",)), LocalSource(self.model_dir))
        recipe = resolve_recipe(RecipeSpec("r", "", self.commit, ("maps/d.json", "LICENSE")), self.repo)
        self.lock = {"schema": 1, "images": [], "models": [model], "recipes": [recipe]}
        self.store_dir = os.path.join(self.tmp, "store")
        self.local = Local(self.store_dir, {"m": LocalSource(self.model_dir)}, {"r": self.repo})

    def collect(self):
        store = Store(self.store_dir, self.lock)
        with store.open():
            store.collect(self.local)
        return store

    def test_collect_then_verify(self):
        self.collect()
        weight = os.path.join(self.store_dir, "models/m/model.safetensors")
        self.assertTrue(os.path.isfile(weight))
        self.assertFalse(os.stat(weight).st_mode & stat.S_IWUSR, "store files are read-only")
        self.assertFalse(os.path.exists(os.path.join(self.store_dir, "models/m/.gitattributes")))
        store = Store(self.store_dir, self.lock)
        with store.open():
            self.assertEqual(store.verify(), [])
            self.assertTrue(all(r[2] == "verified" for r in store.status()))

    def test_rerun_skips_verified_files(self):
        self.collect()
        with mock.patch("hakobune.hashing.copy_and_hash", side_effect=AssertionError("copied again")), \
             mock.patch("hakobune.hashing.sha256_file", side_effect=AssertionError("re-hashed")):
            self.collect()

    def test_corrupt_source_stores_nothing(self):
        with open(os.path.join(self.model_dir, "model.safetensors"), "r+b") as f:
            f.write(b"\0\0\0\0")
        with self.assertRaisesRegex(HakobuneError, "does not match the lock"):
            self.collect()
        leftovers = os.listdir(os.path.join(self.store_dir, "models/m"))
        self.assertNotIn("model.safetensors", leftovers)
        self.assertFalse([x for x in leftovers if x.endswith(".partial")])

    def test_verify_finds_tampering_and_extras(self):
        self.collect()
        weight = os.path.join(self.store_dir, "models/m/model.safetensors")
        os.chmod(weight, 0o644)
        with open(weight, "r+b") as f:
            f.write(b"\xff")
        self.write("store/models/m/stray.bin", b"?")
        store = Store(self.store_dir, self.lock)
        with store.open():
            problems = store.verify()
        self.assertTrue(any("does not match" in p for p in problems), problems)
        self.assertTrue(any("stray.bin" in p for p in problems), problems)

    def test_collect_replaces_bad_store_copy(self):
        self.collect()
        weight = os.path.join(self.store_dir, "models/m/model.safetensors")
        os.chmod(weight, 0o644)
        with open(weight, "r+b") as f:
            f.write(b"\xff")
        os.utime(weight, ns=(1, 1))  # defeat the state cache
        self.collect()
        store = Store(self.store_dir, self.lock)
        with store.open():
            self.assertEqual(store.verify(), [])

    def test_not_enough_space(self):
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=1)):
            with self.assertRaisesRegex(HakobuneError, "GB free"):
                self.collect()

    def test_second_process_is_refused(self):
        store = Store(self.store_dir, self.lock)
        with store.open():
            with self.assertRaisesRegex(HakobuneError, "another hakobune"):
                with Store(self.store_dir, self.lock).open():
                    pass

    def test_unknown_only_name(self):
        store = Store(self.store_dir, self.lock)
        with store.open(), self.assertRaisesRegex(HakobuneError, "not in the lock"):
            store.collect(self.local, {"nope"})


class ImageTest(TempDirTest):
    def test_archive_chain_verifies(self):
        path = os.path.join(self.tmp, "img.tar")
        image_id = make_image_archive(path, [b"layer-one", b"layer-two"])
        check = docker.verify_archive(path, image_id)
        self.assertEqual(check.layers, 2)
        self.assertEqual(check.size, os.path.getsize(path))

    def test_wrong_image(self):
        path = os.path.join(self.tmp, "img.tar")
        make_image_archive(path, [b"layer"])
        with self.assertRaisesRegex(HakobuneError, "does not contain"):
            docker.verify_archive(path, "sha256:" + "0" * 64)

    def test_corrupt_layer(self):
        path = os.path.join(self.tmp, "img.tar")
        image_id = make_image_archive(path, [b"layer"], tamper_layer=True)
        with self.assertRaisesRegex(HakobuneError, "corrupt"):
            docker.verify_archive(path, image_id)

    def test_layers_must_match_config(self):
        path = os.path.join(self.tmp, "img.tar")
        image_id = make_image_archive(path, [b"layer"], diff_ids=["f" * 64])
        with self.assertRaisesRegex(HakobuneError, "diff_ids"):
            docker.verify_archive(path, image_id)

    def test_not_a_tar(self):
        path = self.write("img.tar", b"not a tar at all" * 100)
        with self.assertRaises(HakobuneError):
            docker.verify_archive(path, "sha256:" + "0" * 64)

    def _image_store(self):
        src = os.path.join(self.tmp, "src.tar")
        image_id = make_image_archive(src, [b"layer"])
        entry = {"name": "img", "ref": "test:1", "image_id": image_id, "platform": "linux/arm64", "size": 10}
        store = Store(os.path.join(self.tmp, "store"), {"schema": 1, "images": [entry], "models": [], "recipes": []})
        saves = []

        def fake_save(ref, platform, out):
            saves.append(ref)
            with open(src, "rb") as a, open(out, "wb") as b:
                b.write(a.read())

        patches = (
            mock.patch("hakobune.docker.inspect", return_value=docker.LocalImage(image_id, "linux/arm64", 10, ())),
            mock.patch("hakobune.docker.save", side_effect=fake_save),
        )
        return store, saves, patches

    def test_collect_image_once_and_reverify_without_state(self):
        store, saves, (p1, p2) = self._image_store()
        with p1, p2:
            with store.open():
                store.collect(Local(store.root))
                store.collect(Local(store.root))
            self.assertEqual(len(saves), 1)
            os.unlink(store.state_path)
            store2 = Store(store.root, store.lock)
            with store2.open():
                store2.collect(Local(store.root))
                self.assertEqual(store2.status()[0][2], "verified")
            self.assertEqual(len(saves), 1, "an archive already in the store is verified, not re-exported")

    def test_collect_image_refuses_moved_tag(self):
        store, _saves, (_p1, p2) = self._image_store()
        other = docker.LocalImage("sha256:" + "e" * 64, "linux/arm64", 10, ())
        with mock.patch("hakobune.docker.inspect", return_value=other), p2:
            with store.open(), self.assertRaisesRegex(HakobuneError, "lock pins"):
                store.collect(Local(store.root))

    def test_docker_wrapper_is_read_only(self):
        for args in (["run", "x"], ["rm", "x"], ["image", "rm", "x"], ["pull", "x"], ["load"],
                     ["compose", "up"], ["stop", "x"], ["image", "prune"]):
            with self.assertRaisesRegex(HakobuneError, "read-only", msg=args):
                docker.run_docker(args)


if __name__ == "__main__":
    unittest.main()
